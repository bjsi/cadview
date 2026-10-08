import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web, WSMsgType
from aiohttp.test_utils import TestClient, TestServer
from openworkshop import server
from scene_fixture import box_scene


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [patch.object(server, 'DATA_DIR', root), patch.object(server, 'SCENE_FILE', root/'legacy.gz')]
        for p in self.patches: p.start()
        self.app = server.make_app()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    async def test_running_openworkshop_recognises_a_live_server_only(self):
        # `openworkshop` started twice (terminal + desktop preview) must park on
        # the first instead of failing — the probe is what decides that
        port = self.client.port
        self.assertTrue(await asyncio.to_thread(server.running_openworkshop, '127.0.0.1', port))
        self.assertFalse(await asyncio.to_thread(server.running_openworkshop, '127.0.0.1', 1))

    async def test_manifest_designs_are_cards_before_their_first_build(self):
        # a fresh clone's gallery lists every design in openworkshop.json at once;
        # the server builds them (serially) and the rows say so meanwhile
        root = Path(self.tmp.name) / 'repo'
        (root / 'parts').mkdir(parents=True)
        (root / 'parts' / 'widget.py').write_text('print("hi")\n')
        (root / 'openworkshop.json').write_text(json.dumps({'designs': [
            {'scene': 'widget', 'title': 'The widget', 'script': 'parts/widget.py'},
            {'scene': 'bad name!', 'script': 'parts/widget.py'},
            {'scene': 'ghost', 'script': 'parts/missing.py'}]}))
        with patch.object(server, 'MANIFEST', root / 'openworkshop.json'), \
                patch.object(server, 'RUN_ROOTS', [root]), \
                patch.object(server, 'RUN_REGISTRY', root / 'runnable.txt'):
            self.assertEqual([s for s, _t, _p in server._manifest()], ['widget'])
            self.assertEqual([(s, sc) for s, _t, sc in server._manifest_missing()], [('ghost', 'parts/missing.py')])
            self.app['queued'].add('widget')
            rows = (await (await self.client.get('/api/runnable')).json())['projects']
            self.assertEqual([r['project'] for r in rows], ['widget', 'ghost'])
            self.assertIn('script not found', rows[1]['error'][0])   # a moved script is a visible failure
            self.assertEqual(rows[0]['title'], 'The widget')
            self.assertFalse(rows[0]['built'])
            self.assertTrue(rows[0]['queued'])
            self.assertEqual(rows[0]['group'], 'repo')
            await self.push(project='widget')
            rows = (await (await self.client.get('/api/runnable')).json())['projects']
            self.assertTrue(rows[0]['built'])
            self.assertEqual(rows[0]['title'], 'The widget')   # manifest title survives a push
            # a helper the design runpy'd stamped itself and got registered:
            # the manifest script still owns the scene (watch re-runs IT)
            helper = root / 'parts' / 'helper.py'
            helper.write_text('')
            server._register(helper, 'widget')
            self.app['store'].meta['widget']['source_file'] = str(helper)
            # resolved on both sides: macOS tmp is /private/var, Windows runners use 8.3 short names
            self.assertEqual(server._module_for(self.app['store'], 'widget'), (root / 'parts' / 'widget.py').resolve())

    async def test_prebuilt_bundle_seeds_unbuilt_designs_and_git_decides_rebuild(self):
        import gzip, io, subprocess, tarfile
        root = Path(self.tmp.name) / 'repo'
        root.mkdir()
        (root / 'widget.py').write_text('print(1)\n')
        bundle = Path(self.tmp.name) / 'openworkshop-scenes.tar.gz'
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tar:
            def add(name, data):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            add('scene-widget.json.gz', gzip.compress(json.dumps(box_scene(7)).encode()))
            add('scene-other.json.gz', gzip.compress(json.dumps(box_scene(9)).encode()))
            add('bundle.json', b'{"commit": "deadbeef"}')
        bundle.write_bytes(buf.getvalue())
        (root / 'openworkshop.json').write_text(json.dumps({
            'designs': [{'scene': 'widget', 'script': 'widget.py'}],
            'prebuilt': {'url': bundle.as_uri()}}))
        with patch.object(server, 'MANIFEST', root / 'openworkshop.json'), patch.object(server, 'RUN_ROOTS', [root]):
            seeded, commit = server._seed_prebuilt(self.app['store'], {'widget'})
            self.assertEqual((seeded, commit), (['widget'], 'deadbeef'))
            self.assertIn('widget', self.app['store'].meta)
            self.assertFalse((server.DATA_DIR / 'scene-other.json.gz').exists())   # only what was asked for
            self.assertEqual(server._seed_prebuilt(self.app['store'], set()), ([], None))
            rows = (await (await self.client.get('/api/runnable')).json())['projects']
            self.assertTrue(rows[0]['built'])
            # staleness: unknown commit -> rebuild; clean tree at the bundle's commit -> no rebuild
            self.assertTrue(server._sources_changed_since('deadbeef'))
            g = ['git', '-C', str(root)]
            subprocess.run(g + ['init', '-q'], check=True)
            subprocess.run(g + ['-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.'], check=True)
            subprocess.run(g + ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'x'], check=True)
            head = subprocess.run(g + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
            self.assertFalse(server._sources_changed_since(head))
            (root / 'widget.py').write_text('print(2)\n')
            self.assertTrue(server._sources_changed_since(head))

    async def test_snapshot_is_rendered_by_an_open_page_never_a_helper_frame(self):
        await self.push(project='demo')
        # nothing open -> tell the agent what to do, don't hang
        self.assertEqual((await self.client.get('/api/snapshot?name=demo')).status, 503)
        self.assertEqual((await self.client.get('/api/snapshot?name=nope')).status, 404)
        helper = await self.client.ws_connect('/ws?scene=demo&helper=1')
        self.assertEqual((await self.client.get('/api/snapshot?name=demo')).status, 503)
        page = await self.client.ws_connect('/ws?role=renderer')     # a gallery page
        getting = asyncio.create_task(self.client.get('/api/snapshot?name=demo&view=top&focus=box&w=640'))
        for _ in range(5):
            msg = json.loads((await asyncio.wait_for(page.receive(), 5)).data)
            if msg['type'] == 'snapshot':
                break
        self.assertEqual(msg['name'], 'demo')
        self.assertEqual(msg['params'], {'view': 'top', 'focus': 'box', 'w': '640'})
        png = b'\x89PNG\r\n\x1a\n' + b'fake'
        bad = await self.client.post('/api/snapshot?id=' + msg['id'], data=b'not a png')
        self.assertEqual(bad.status, 400)
        ok = await self.client.post('/api/snapshot?id=' + msg['id'], data=png)
        self.assertEqual(ok.status, 200)
        resp = await asyncio.wait_for(getting, 5)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers['Content-Type'], 'image/png')
        self.assertEqual(await resp.read(), png)
        # a renderer page never receives scene data on a push
        await self.push(width=12, project='demo')
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(page.receive(), 0.5)
        await helper.close()
        await page.close()

    async def test_bake_single_file_pages_and_changed_vs_bundle(self):
        import base64, gzip, io, tarfile
        from openworkshop import bake
        await self.push(width=10, project='same')
        await self.push(width=10, project='moved')
        before = {'same': box_scene(10), 'moved': box_scene(11)}    # main's bundle: 'moved' differs
        bundle = Path(self.tmp.name) / 'openworkshop-scenes.tar.gz'
        with tarfile.open(bundle, 'w:gz') as tar:
            for p, msg in before.items():
                data = gzip.compress(json.dumps(msg).encode())
                info = tarfile.TarInfo(f'scene-{p}.json.gz')
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        out = Path(self.tmp.name) / 'review'
        url = str(self.client.make_url('')).rstrip('/')
        rc = await asyncio.to_thread(bake.main, ['--single-file', '--changed-vs', str(bundle), '--url', url, str(out)])
        self.assertEqual(rc, 0)
        report = json.loads((out / 'changed.json').read_text())
        self.assertEqual((report['changed'], report['unchanged']), (['moved'], ['same']))
        self.assertEqual(report['scenes']['same'], {'changed': [], 'added': [], 'removed': [], 'animation': False})
        self.assertTrue(report['scenes']['moved']['changed'])                    # the wider box, by part path
        self.assertTrue(all(p.startswith('/Assembly/') for p in report['scenes']['moved']['changed']))
        # the signature is what survives a rebuild: re-encoding the same mesh in a different vertex order is no change
        from openworkshop import bake as _bake
        same = box_scene(10)
        self.assertEqual(_bake.scene_diff(same, json.loads(json.dumps(same))), {'changed': [], 'added': [], 'removed': [], 'animation': False})
        self.assertFalse((out / 'same.html').exists())
        page = (out / 'moved.html').read_text()
        self.assertNotIn('./vendor/', page)                    # nothing fetched: modules are data: URLs
        self.assertIn('"three-core": "data:text/javascript;base64,', page)
        b64 = page.split('window.OPENWORKSHOP_INLINE_SCENE = "')[1].split('"')[0]
        inline = json.loads(gzip.decompress(base64.b64decode(b64)))
        self.assertEqual(inline['data'], box_scene(10)['data'])
        self.assertNotIn('source_file', inline['meta'])          # push-side meta stripped

    async def test_scoped_listener_shows_one_scene_family_read_only(self):
        await self.push(project='demo')
        await self.push(project='arenas-v71')
        await self.push(project='arenas')
        # make the test listener a scoped one for the "arenas*" family
        with patch.object(server, 'SCOPES', [('127.0.0.1', self.client.port, ['arenas', 'arenas-*'])]):
            rows = (await (await self.client.get('/api/runnable')).json())['projects']
            self.assertEqual(sorted(r['project'] for r in rows), ['arenas', 'arenas-v71'])
            status = await (await self.client.get('/api/status')).json()
            self.assertEqual(sorted(status['projects']), ['arenas', 'arenas-v71'])
            self.assertEqual((await self.client.get('/api/scene?name=arenas-v71')).status, 200)
            self.assertEqual((await self.client.get('/api/scene?name=demo')).status, 404)
            self.assertEqual((await self.client.get('/demo')).status, 404)
            self.assertEqual((await self.client.get('/thumbs/demo.png')).status, 404)
            self.assertEqual((await self.client.get('/api/parts?name=demo')).status, 404)
            self.assertEqual((await self.client.get('/arenas-v71')).status, 200)
            self.assertEqual((await self.client.get('/')).status, 200)
            # read-only: pushes, deletes, runs refused; a page's own posts still work
            self.assertEqual((await self.client.post('/api/scene?name=arenas', json=box_scene(3))).status, 403)
            self.assertEqual((await self.client.delete('/api/scene?name=arenas')).status, 403)
            self.assertEqual((await self.client.post('/api/run', json={'project': 'arenas'})).status, 403)
            sel = await self.client.post('/api/selection?name=arenas', json={'items': [], 'camera': None})
            self.assertIn(sel.status, (200, 400))
            # websockets: must name an in-scope scene; never a snapshot renderer
            with self.assertRaises(Exception):
                await self.client.ws_connect('/ws')
            with self.assertRaises(Exception):
                await self.client.ws_connect('/ws?scene=demo')
            ws = await self.client.ws_connect('/ws?scene=arenas')
            self.assertTrue(any(w in self.app['helpers'] for w in self.app['websockets']))
            self.assertEqual((await self.client.get('/api/snapshot?name=arenas')).status, 503)
            await ws.close()
        # off the scoped listener everything is back
        self.assertEqual((await self.client.get('/api/scene?name=demo')).status, 200)

    def test_client_scene_name_comes_from_the_nearest_manifest(self):
        from openworkshop import client
        root = Path(self.tmp.name) / 'repo'
        (root / 'tools').mkdir(parents=True)
        script = root / 'tools' / 'show_thing.py'
        script.write_text('')
        (root / 'openworkshop.json').write_text(json.dumps({'designs': [
            {'scene': 'thing', 'title': 'A thing', 'script': 'tools/show_thing.py'}]}))
        self.assertEqual(client._manifest_design(str(script)), ('thing', 'A thing'))
        other = root / 'tools' / 'other.py'
        other.write_text('')
        self.assertEqual(client._manifest_design(str(other)), (None, None))

    async def push(self, width=10, project='demo'):
        resp = await self.client.post('/api/scene?name='+project, json=box_scene(width))
        self.assertEqual(resp.status, 200, await resp.text())
        return (await resp.json())['revision']

    async def test_rapid_pushes_have_unique_revisions_and_bounded_durable_history(self):
        # concurrent pushes COMPLETE in event-loop order, which differs by
        # platform (Windows proactor reorders the batch) — assert the
        # retention contract, not a scheduling order
        with patch.object(server.time, 'strftime', return_value='same-second'):
            revisions = await asyncio.gather(*(self.push(10+i) for i in range(7)))
        self.assertEqual(len(set(revisions)), 7)
        history = await (await self.client.get('/api/history?name=demo')).json()
        kept = [m['revision'] for m in history['revisions']]
        self.assertEqual(len(kept), 5)
        self.assertTrue(set(kept) <= set(revisions))
        current = self.app['store'].meta['demo']['revision']
        self.assertEqual(kept[0], current)
        reloaded = server.SceneStore()
        self.assertEqual(reloaded.meta['demo']['revision'], current)
        self.assertEqual(len(reloaded.revisions('demo')), 5)
        old = await self.client.get('/api/scene?name=demo&revision='+kept[-1])
        self.assertEqual((await old.json())['meta']['revision'], kept[-1])
        dropped = next(r for r in revisions if r not in kept)
        self.assertEqual((await self.client.get('/api/scene?name=demo&revision='+dropped)).status, 404)
        self.assertEqual(len(list((server.DATA_DIR/'history/demo').glob('*.gz'))), 4)

    async def test_failed_persist_does_not_publish(self):
        revision = await self.push()
        with self.assertLogs("aiohttp.server", level="ERROR"), patch.object(self.app['store'], 'persist', side_effect=OSError('disk full')):
            resp = await self.client.post('/api/scene?name=demo', json=box_scene(11))
        self.assertEqual(resp.status, 500)
        self.assertEqual(self.app['store'].meta['demo']['revision'], revision)

    async def test_websocket_skips_only_known_revision_and_catches_up(self):
        revision = await self.push()
        ws = await self.client.ws_connect('/ws?scene=demo&revision='+revision)
        self.assertEqual((await ws.receive_json())['type'], 'hello')
        # Next frame must be a new push, not the HTTP scene replay.
        second = await self.push(11)
        self.assertEqual((await ws.receive_json())['meta']['revision'], second)
        await ws.close()
        ws = await self.client.ws_connect('/ws?scene=demo&revision='+revision)
        await ws.receive_json()
        self.assertEqual((await ws.receive_json())['meta']['revision'], second)
        await ws.close()

    async def test_delete_clears_history_and_keeps_latest_other_project(self):
        await self.push(project='a'); await self.push(project='b'); await self.push(project='c')
        await self.client.delete('/api/scene?name=c')
        self.assertEqual(self.app['store'].latest, 'b')
        await self.client.delete('/api/scene?name=b')
        self.assertEqual(self.app['store'].latest, 'a')
        await self.push(11, 'a')
        await self.client.delete('/api/scene?name=a')
        self.assertEqual(self.app['store'].revisions('a'), [])
        self.assertEqual(server.SceneStore().meta, {})

    async def test_clear_between_http_and_ws_does_not_leave_stale_model(self):
        revision = await self.push()
        await self.client.delete('/api/scene?name=demo')
        ws = await self.client.ws_connect('/ws?scene=demo&revision='+revision)
        await ws.receive_json()
        self.assertEqual((await ws.receive_json())['type'],'clear')
        await ws.close()

    def test_part_hashes_follow_geometry_appearance_and_parent_transform(self):
        scene = box_scene()
        baseline = server.part_fingerprints(scene['data'])
        scene['data']['shapes']['parts'][0]['color'] = '#ffffff'
        changed = server.part_fingerprints(scene['data'])
        self.assertNotEqual(baseline['/Assembly/Block A'], changed['/Assembly/Block A'])
        self.assertEqual(baseline['/Assembly/Block B'], changed['/Assembly/Block B'])
        scene['data']['shapes']['loc'][0][0] = 5
        moved = server.part_fingerprints(scene['data'])
        self.assertTrue(all(moved[k] != changed[k] for k in changed))
        reordered = copy.deepcopy(scene['data'])
        reordered['instances'].insert(0, {})
        for part in reordered['shapes']['parts']: part['shape']['ref'] = 1
        self.assertEqual(moved, server.part_fingerprints(reordered))

    async def test_modern_updates_are_small_notices_and_http_reuses_gzip(self):
        revision = await self.push()
        ws = await self.client.ws_connect('/ws?scene=demo&updates=revision&revision='+revision)
        await ws.receive_json()
        next_revision = await self.push(11)
        notice = await ws.receive_json()
        self.assertEqual(notice['type'],'revision')
        self.assertEqual(notice['meta']['revision'],next_revision)
        self.assertNotIn('data',notice)
        with patch.object(server.gzip,'compress',side_effect=AssertionError('must reuse bytes')):
            response = await self.client.get('/api/scene?name=demo',headers={'Accept-Encoding':'gzip'})
            self.assertEqual(response.headers['Content-Encoding'],'gzip')
            self.assertEqual((await response.json())['meta']['revision'],next_revision)
        await ws.close()


class SelectionAndGroupingTests(ServerTests):
    async def test_selection_roundtrip_and_scene_meta(self):
        await self.push(project='widget')
        sel = [{"part": "box", "solidPath": "/scene/box", "topo": "face", "face": 2,
                "center": [1, 2, 3], "size": [10, 0, 10], "area": 100.0}]
        resp = await self.client.post('/api/selection?name=widget', json={
            "selection": sel, "revision": "r1",
            "camera": {"position": [1, 2, 3], "quaternion": [0, 0, 0, 1],
                       "target": [0, 0, 0], "zoom": 1}})
        self.assertEqual(resp.status, 200, await resp.text())
        got = await (await self.client.get('/api/selection?name=widget')).json()
        self.assertEqual(got['selection'], sel)
        self.assertEqual(got['project'], 'widget')
        self.assertIsNotNone(got['updated_at'])
        self.assertIsNotNone(got['scene_revision'])
        empty = await (await self.client.get('/api/selection?name=never-pushed')).json()
        self.assertEqual(empty['selection'], [])

    async def test_selection_rejects_junk(self):
        self.assertEqual((await self.client.post('/api/selection?name=w', json={"selection": "no"})).status, 400)
        self.assertEqual((await self.client.post('/api/selection?name=w', data=b'x',
                                                 headers={'Content-Type': 'text/plain'})).status, 403)
        resp = await self.client.post('/api/selection?name=w', json={"selection": []},
                                      headers={'Origin': 'https://evil.example'})
        self.assertEqual(resp.status, 403)

    async def test_runnable_groups_by_prefix_and_merges_titles(self):
        for name in ('acme', 'acme-sub', 'other'):
            await self.push(project=name)
        (server.DATA_DIR / 'titles.json').write_text(json.dumps({"acme-sub": "The Sub"}))
        rows = (await (await self.client.get('/api/runnable')).json())['projects']
        by = {r['project']: r for r in rows}
        self.assertEqual(by['acme-sub']['group'], by['acme']['group'])
        self.assertNotEqual(by['other']['group'], by['acme']['group'])
        self.assertEqual(by['acme-sub']['title'], 'The Sub')
        self.assertIsNone(by['other']['title'])


class GeometryTests(ServerTests):
    async def test_parts_returns_world_anchors(self):
        await self.push(width=10, project='geo')
        rows = (await (await self.client.get('/api/parts?name=geo')).json())['parts']
        by = {r['path']: r for r in rows}
        a = by['/Assembly/Block A']
        self.assertEqual(a['kind'], 'part')
        self.assertEqual(a['center'], [5.0, 5.0, 5.0])
        self.assertEqual(a['size'], [10.0, 10.0, 10.0])
        self.assertEqual(by['/Assembly/Block B']['center'], [30.0, 5.0, 5.0])
        self.assertEqual(by['/Assembly']['kind'], 'group')
        self.assertEqual(by['/Assembly']['min'], [0.0, 0.0, 0.0])
        self.assertEqual(by['/Assembly']['max'], [35.0, 10.0, 10.0])

    async def test_clearance_finds_new_overlap_and_keeps_baseline(self):
        await self.push(width=10, project='geo')
        # slide Block A into Block B: gap is 15, overlap from ~tx>15.4
        resp = await self.client.post('/api/clearance', json={
            'project': 'geo', 'step': 0.1,
            'tracks': [['Block A', 'tx', [0, 2.0], [0, 25]]]})
        body = await resp.json()
        self.assertEqual(resp.status, 200, body)
        self.assertEqual(len(body['hits']), 1)
        hit = body['hits'][0]
        self.assertEqual({hit['a'], hit['b']},
                         {'/Assembly/Block A', '/Assembly/Block B'})
        self.assertGreater(hit['first_t'], 0.5)
        # moving away: no hits
        away = await (await self.client.post('/api/clearance', json={
            'project': 'geo',
            'tracks': [['Block A', 'tx', [0, 2.0], [0, -40]]]})).json()
        self.assertEqual(away['hits'], [])

    async def test_clearance_uses_pushed_clip(self):
        msg = box_scene(10)
        msg['animations'] = [{'name': 'crash', 'tracks': [
            ['Block A', 'tx', [0, 1.0], [0, 25]]], 'speed': 1}]
        resp = await self.client.post('/api/scene?name=geo2', json=msg)
        self.assertEqual(resp.status, 200)
        body = await (await self.client.post('/api/clearance', json={
            'project': 'geo2', 'clip': 'crash'})).json()
        self.assertEqual(len(body['hits']), 1)
