import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web, WSMsgType
from aiohttp.test_utils import TestClient, TestServer
from cadview import server
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

    async def push(self, width=10, project='demo'):
        resp = await self.client.post('/api/scene?name='+project, json=box_scene(width))
        self.assertEqual(resp.status, 200, await resp.text())
        return (await resp.json())['revision']

    async def test_rapid_pushes_have_unique_revisions_and_bounded_durable_history(self):
        with patch.object(server.time, 'strftime', return_value='same-second'):
            revisions = await asyncio.gather(*(self.push(10+i) for i in range(7)))
        self.assertEqual(len(set(revisions)), 7)
        history = await (await self.client.get('/api/history?name=demo')).json()
        self.assertEqual([m['revision'] for m in history['revisions']], list(reversed(revisions[-5:])))
        reloaded = server.SceneStore()
        self.assertEqual(reloaded.meta['demo']['revision'], revisions[-1])
        self.assertEqual(len(reloaded.revisions('demo')), 5)
        old = await self.client.get('/api/scene?name=demo&revision='+revisions[-2])
        self.assertEqual((await old.json())['meta']['revision'], revisions[-2])
        self.assertEqual((await self.client.get('/api/scene?name=demo&revision='+revisions[0])).status, 404)
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
