"""cadview server: keeps the last-shown scene and replays it to late joiners.

Deliberately CAD-free — no OCP/build123d imports — so it starts in well under a
second and never version-couples to the CAD stack. Scenes arrive pre-tessellated
from cadview.client as three-cad-viewer JSON.

    python -m cadview.server [--host H] [--port 3941]

Scenes survive restarts via ~/.local/share/cadview/scene-<project>.json.gz.

One scene per PROJECT: show() tags a push with its project (CADVIEW_SCENE or the script's cwd
basename), and viewers subscribe by path — http://host:3941/mega-desk shows mega-desk's last
scene only, http://host:3941/ shows whatever was pushed last, any project.
"""

import argparse
import array
import asyncio
import base64
import collections
import gzip
import hashlib
import math
import tempfile
import uuid
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import aiohttp
from aiohttp import WSMsgType, web

log = logging.getLogger("cadview")

STATIC_DIR = Path(__file__).parent / "static"
DATA_DIR = Path(os.environ.get("CADVIEW_DATA", "~/.local/share/cadview")).expanduser()
SCENE_FILE = DATA_DIR / "scene.json.gz"          # legacy single-scene cache -> project "default"
DEFAULT_PROJECT = "default"
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# ---- device gate (security audit F2) ----------------------------------------
# Everything on this server is gated to the operator's OWN devices (or the
# hub-remote Bearer): scenes are unpublished models (read/write/delete was
# previously open to the whole tailnet — the Codex review's top finding), and
# /say reaches agent sessions. The GENERIC install is loopback-only — a
# normal local chrome tab against python -m cadview.server just works;
# additional device IPs come from CADVIEW_PEERS (a tailnet deployment sets
# its devices in the service environment).
ALLOWED_PEERS = {p.strip() for p in (
    os.environ.get("CADVIEW_PEERS") or "127.0.0.1,::1"
).split(",") if p.strip()}

HUB_TOKEN_FILE = Path(os.environ.get("CADVIEW_HUB_TOKEN",
                                     "~/.config/hub-remote/token")).expanduser()
# device labels for the audit trail ("ip=label,ip=label" via env) — the tmux
# bridge only ever sees loopback, so the REAL requester travels in `origin`
DEVICE_LABELS = {"127.0.0.1": "loopback", "::1": "loopback",
                 **dict(p.split("=", 1) for p in
                        os.environ.get("CADVIEW_DEVICE_LABELS", "").split(",") if "=" in p)}


def _hub_token():
    """Read at request time so a rotated token needs no restart. Never sent to browsers."""
    try:
        return HUB_TOKEN_FILE.read_text().strip() or None
    except OSError:
        return None


def _peer(request) -> str:
    return (request.remote or "").removeprefix("::ffff:")


@web.middleware
async def device_gate(request, handler):
    if _peer(request) in ALLOWED_PEERS:
        return await handler(request)
    tok = _hub_token()
    if tok and request.headers.get("Authorization", "") == f"Bearer {tok}":
        return await handler(request)
    log.warning("gate refused %s %s from %s", request.method, request.path, request.remote)
    raise web.HTTPForbidden(text="cadview only answers this operator's own devices")


def _reject_cross_site(request, require_json=False):
    """CSRF guard for state-changing routes (astra review P1): the device gate
    trusts source IPs, so a malicious page in a browser ON an allowed device
    could fire a CORS-safelisted (no-preflight) POST here. A cross-site browser
    request carries the foreign Origin — reject it; script clients (curl,
    cadview.client) send no Origin and pass. require_json additionally forces
    a preflight-triggering Content-Type, which we never CORS-approve."""
    origin = request.headers.get("Origin")
    if origin and urllib.parse.urlsplit(origin).netloc != request.host:
        log.warning("cross-site %s %s refused (Origin %s)", request.method, request.path, origin)
        raise web.HTTPForbidden(text="cross-site request refused")
    if require_json and request.content_type != "application/json":
        raise web.HTTPForbidden(text="want Content-Type: application/json")


def scene_file(project: str) -> Path:
    return DATA_DIR / f"scene-{project}.json.gz"


HISTORY_LIMIT = 5  # current plus four previous revisions per project
REVISION_RE = re.compile(r"^[a-f0-9]{32,64}$")


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def part_fingerprints(data):
    """Hash shared geometry once; include ancestor transforms and appearance."""
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    instances = [digest(i) for i in data.get("instances", [])]
    result = {}
    def walk(node, parent="", transforms=()):
        path = node.get("id") or parent + "/" + node.get("name", "part")
        transforms = (*transforms, node.get("loc"))
        if "parts" in node:
            for child in node["parts"]:
                walk(child, path, transforms)
        else:
            shape = node.get("shape")
            if isinstance(shape, dict) and isinstance(shape.get("ref"), int):
                shape = instances[shape["ref"]]
            result[path] = digest({"shape": shape, "loc": transforms,
                                   **{k: node.get(k) for k in ("color", "alpha", "material", "texture", "subtype")}})
    walk(data.get("shapes", {}))
    return result


class SceneStore:
    """Current scenes in memory, bounded revision history on disk."""

    def __init__(self):
        self.text, self.meta, self.history, self.compressed = {}, {}, {}, {}
        self.latest = None
        self.load()

    def load(self):
        files = [(SCENE_FILE, DEFAULT_PROJECT)] + [
            (f, f.name[len("scene-"):-len(".json.gz")]) for f in DATA_DIR.glob("scene-*.json.gz")]
        for f, project in sorted(files, key=lambda item: item[0].stat().st_mtime if item[0].exists() else 0):
            if not f.exists() or not PROJECT_RE.fullmatch(project):
                continue
            try:
                compressed = f.read_bytes()
                text = gzip.decompress(compressed).decode()
                message = json.loads(text)
                meta = message.setdefault("meta", {})
                if not meta.get("revision") or meta.get("project") != project:
                    meta.setdefault("revision", hashlib.sha256(text.encode()).hexdigest())
                    meta["project"] = project
                    text = json.dumps(message)
                    compressed = gzip.compress(text.encode(), compresslevel=3)
                self.install(project, text, meta, compressed)
                old = []
                for archive in self.history_dir(project).glob("*.json.gz"):
                    try:
                        old_meta = json.loads(gzip.decompress(archive.read_bytes()))["meta"]
                        if old_meta["revision"] != meta["revision"]:
                            old.append((archive.stat().st_mtime_ns, old_meta))
                    except (OSError, ValueError, KeyError):
                        log.warning("skipping unreadable history %s", archive)
                self.history[project] = [m for _, m in sorted(old, key=lambda pair: pair[0], reverse=True)][:HISTORY_LIMIT - 1]
            except Exception:
                log.exception("could not load %s, skipping", f)

    def history_dir(self, project):
        return DATA_DIR / "history" / project

    def prepare(self, project, message):
        # Serialize the large payload once. Metadata changes alone should not
        # force a browser to download/decode/rebuild unchanged geometry.
        payload = json.dumps({k: v for k, v in message.items() if k != "meta"}, separators=(",", ":"))
        meta = {**message.get("meta", {}), "received_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "revision": uuid.uuid4().hex, "project": project,
                "content_hash": hashlib.sha256(payload.encode()).hexdigest(),
                "part_fingerprints": part_fingerprints(message["data"])}
        text = payload[:-1] + ",\"meta\":" + json.dumps(meta, separators=(",", ":")) + "}"
        return text, meta, gzip.compress(text.encode(), compresslevel=3)

    def persist(self, project, compressed, old_compressed, old_meta, keep):
        if old_compressed:
            atomic_write(self.history_dir(project) / (old_meta["revision"] + ".json.gz"), old_compressed)
        atomic_write(scene_file(project), compressed)
        # The current file is the commit point. Cleanup failures must not make
        # a successfully committed scene appear to have failed to its caller.
        for f in self.history_dir(project).glob("*.json.gz"):
            if f.name.removesuffix(".json.gz") not in keep:
                try:
                    f.unlink()
                except OSError:
                    log.exception("history cleanup failed: %s", f)

    def install(self, project, text, meta, compressed):
        self.text[project], self.meta[project], self.compressed[project] = text, meta, compressed
        # Dict order records the latest push even when deleting another project.
        self.text[project] = self.text.pop(project)
        self.latest = project

    async def push(self, project, message):
        text, meta, compressed = await asyncio.to_thread(self.prepare, project, message)
        previous = ([self.meta[project]] if project in self.meta else []) + self.history.get(project, [])
        previous = previous[:HISTORY_LIMIT - 1]
        await asyncio.to_thread(self.persist, project, compressed, self.compressed.get(project), self.meta.get(project),
                                {m["revision"] for m in previous})
        self.install(project, text, meta, compressed)
        self.history[project] = previous
        return text, meta

    def clear_files(self, project):
        scene_file(project).unlink(missing_ok=True)
        if project == DEFAULT_PROJECT:
            SCENE_FILE.unlink(missing_ok=True)
        for f in self.history_dir(project).glob("*.json.gz"):
            f.unlink(missing_ok=True)

    async def clear(self, project):
        await asyncio.to_thread(self.clear_files, project)
        self.text.pop(project, None)
        self.meta.pop(project, None)
        self.compressed.pop(project, None)
        self.history.pop(project, None)
        self.latest = next(reversed(self.text), None)

    def get(self, project):
        key = project if project is not None else self.latest
        return self.text.get(key)

    def revisions(self, project):
        return ([self.meta[project]] if project in self.meta else []) + self.history.get(project, [])

    def revision_meta(self, project, revision):
        return next((m for m in self.revisions(project) if m["revision"] == revision), None)

    def get_revision(self, project, revision):
        if not REVISION_RE.fullmatch(revision) or not self.revision_meta(project, revision):
            return None
        if self.meta.get(project, {}).get("revision") == revision:
            return self.get(project)
        try:
            return gzip.decompress((self.history_dir(project) / (revision + ".json.gz")).read_bytes()).decode()
        except OSError:
            return None


def project_of(request, allow_none=True):
    """?name= (API) or the first path segment (viewer pages). None = the latest scene, any project."""
    name = request.query.get("name") or request.query.get("scene") or request.match_info.get("project")
    if not name:
        if allow_none:
            return None
        return DEFAULT_PROJECT
    if not PROJECT_RE.match(name):
        raise web.HTTPBadRequest(text="bad project name")
    return name


async def handle_lite(request):
    """The lite viewer (static ES modules on bare three.js): /lite/<project>.
    Served from a path route, so inject <base> to point its relative asset
    URLs at /static/lite/ — a static-host deployment needs no injection
    because the files sit next to each other there."""
    project_of(request)
    # with a TLS listener configured, upgrade page loads to it — embedded
    # browser panes only run scripts on secure origins. Loopback is exempt
    # (the cert names the public host, not 127.0.0.1).
    if (os.environ.get("CADVIEW_TLS_CERT") and request.scheme == "http"
            and _peer(request) not in ("127.0.0.1", "::1")):
        host = request.host.rsplit(":", 1)[0]
        port = os.environ.get("CADVIEW_TLS_PORT", "3943")
        raise web.HTTPTemporaryRedirect(f"https://{host}:{port}{request.path_qs}")
    lite_dir = STATIC_DIR / "lite"
    stamp = str(max(int(p.stat().st_mtime) for p in lite_dir.glob("*")
                    if p.is_file()))
    text = (lite_dir / "index.html").read_text().replace(
        "<!--__CADVIEW_BASE__-->",
        f'<base href="/static/lite/"><meta name="lite-stamp" content="{stamp}">')
    # cache-bust the module: a soft location.reload() revalidates the HTML
    # but browsers happily keep the cached ES module, leaving pages one
    # deploy behind (bit James's desk windows)
    text = text.replace('src="./lite.js"', f'src="./lite.js?v={stamp}"')
    return web.Response(text=text, content_type="text/html",
                        headers={"Cache-Control": "no-cache"})


async def handle_get_scene(request):
    store = request.app["store"]
    project = project_of(request) or store.latest
    revision = request.query.get("revision")
    current = not revision or revision == store.meta.get(project, {}).get("revision")
    compressed = store.compressed.get(project) if current else None
    text = store.get(project) if current else await asyncio.to_thread(store.get_revision, project, revision)
    if text is None:
        raise web.HTTPNotFound(text="no scene pushed yet")
    headers = {"X-Scene-Bytes": str(len(text)), "Cache-Control": "no-store"}
    # Current scenes are compressed once, during commit. Reuse those exact
    # bytes for every viewer instead of recompressing a large JSON per request.
    if compressed is not None and re.search(r"(?:^|,)\s*gzip\s*(?:,|$)", request.headers.get("Accept-Encoding", "")):
        return web.Response(body=compressed, content_type="application/json",
                            headers={**headers, "Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    resp = web.Response(text=text, content_type="application/json", headers=headers)
    resp.enable_compression()
    return resp


async def handle_post_scene(request):
    _reject_cross_site(request)
    store = request.app["store"]
    # aiohttp auto-decompresses Content-Encoding: gzip; the magic check keeps
    # this working for clients whose gzip slips through untouched
    body = await request.read()
    try:
        if body[:2] == b"\x1f\x8b":
            body = await asyncio.to_thread(gzip.decompress, body)
        message = await asyncio.to_thread(json.loads, body)
        if not (isinstance(message, dict) and message.get("type") == "data"
                and isinstance(message.get("data"), dict) and isinstance(message.get("meta", {}), dict)):
            raise ValueError("invalid scene")
    except (ValueError, OSError):
        raise web.HTTPBadRequest(text="expected JSON {type: 'data', data: ...}")

    project = project_of(request, allow_none=False)
    async with request.app["scene_lock"]:
        try:
            text, meta = await store.push(project, message)
        except (IndexError, TypeError, ValueError, KeyError):
            raise web.HTTPBadRequest(text="invalid scene geometry")
        n = await broadcast(request.app, project, text, meta)
    if _peer(request) in AUTOREG_PEERS:
        p = _runnable_path(meta.get("source_file"))
        if p:
            _register(p, project)
            _ensure_watch(request.app, project, p)
    log.info("scene %s revision %s -> %d viewer(s)", project, meta["revision"], n)
    return web.json_response({"ok": True, "project": project, "revision": meta["revision"], "viewers": n})


async def handle_delete_scene(request):
    _reject_cross_site(request)
    store = request.app["store"]
    project = project_of(request, allow_none=False)
    async with request.app["scene_lock"]:
        await store.clear(project)
        n = await broadcast(request.app, project, json.dumps({"type": "clear", "project": project}))
    log.info("scene %s cleared -> %d viewer(s)", project, n)
    return web.json_response({"ok": True, "project": project, "viewers": n})


async def handle_status(request):
    store = request.app["store"]
    return web.json_response({
        "latest": store.latest,
        "projects": {p: {"meta": store.meta.get(p, {}), "bytes": len(t)} for p, t in store.text.items()},
        "viewers": len(request.app["websockets"]),
    })


async def handle_history(request):
    store = request.app["store"]
    project = project_of(request) or store.latest
    return web.json_response({"project": project, "revisions": [
        {k: v for k, v in m.items() if k != "part_fingerprints"} for m in store.revisions(project)]})


def validate_view(view):
    if view is None:
        return None
    if not isinstance(view, dict):
        raise ValueError("invalid camera")
    clean = {}
    for key, length in (("position", 3), ("quaternion", 4), ("target", 3)):
        value = view.get(key)
        if not isinstance(value, list) or len(value) != length or not all(
                isinstance(n, (float, int)) and math.isfinite(n) and abs(n) <= 1e12 for n in value):
            raise ValueError("invalid camera " + key)
        clean[key] = value
    zoom = view.get("zoom")
    if not isinstance(zoom, (float, int)) or not math.isfinite(zoom) or not 1e-6 <= zoom <= 1e6:
        raise ValueError("invalid camera zoom")
    clean["zoom"] = zoom
    return clean


# ---- run: re-execute the module that pushed a scene (James's dev loop) ------
# Executing python on the hub from a browser button is RCE *by design*, so it
# is fenced three ways (design agreed with James 2026-09-30): (1) the device
# gate + the same CSRF guard as /say; (2) the viewer never supplies a path —
# it names a project, and the server resolves the module stamped into that
# scene's meta at push time; (3) the module must be in the runnable REGISTRY,
# which only gains entries when a push arrived from the hub itself (loopback/
# hub peer = the script already executed here as James, so blessing it adds
# no new capability). A path stamped by a phone/mbp push is display-only
# until it earns registry entry.
RUN_REGISTRY = DATA_DIR / "runnable.txt"
RUN_LOG = DATA_DIR / "run-log.tsv"
RUN_ROOTS = [Path(p).expanduser() for p in
             os.environ.get("CADVIEW_RUN_ROOTS", "~/Projects").split(":") if p]
# CADVIEW_HOME_ALIAS: a bind-mount alias of $HOME (bind mounts, unlike
# symlinks, survive resolve()) — accept the alias of home-relative roots too
try:
    _ALIAS = Path(os.environ.get("CADVIEW_HOME_ALIAS", "")) if os.environ.get("CADVIEW_HOME_ALIAS") else None
    if _ALIAS and _ALIAS.exists() and _ALIAS.samefile(Path.home()):
        RUN_ROOTS += [_ALIAS / r.relative_to(Path.home())
                      for r in list(RUN_ROOTS) if r.is_relative_to(Path.home())]
except OSError:
    pass
RUN_TIMEOUT = int(os.environ.get("CADVIEW_RUN_TIMEOUT", "600"))
# the interpreter with the CAD stack (build123d/OCP) for module re-runs.
# Default = the server's own interpreter, so the one-venv install just
# works; split deployments set CADVIEW_CAD_PYTHON.
CAD_PYTHON = os.environ.get("CADVIEW_CAD_PYTHON") or sys.executable
# peers whose pushes may auto-register modules as runnable: loopback (the
# script already ran here) plus any extras (e.g. the server's own tailnet
# address when clients push to it by name)
AUTOREG_PEERS = {"127.0.0.1", "::1"} | {
    p.strip() for p in os.environ.get("CADVIEW_AUTOREG_PEERS", "").split(",") if p.strip()}


def _runnable_path(src):
    """Absolute existing .py under an allowed root, symlink-resolved — or None."""
    if not isinstance(src, str) or not src:
        return None
    try:
        p = Path(src).resolve(strict=True)
    except OSError:
        return None
    if p.suffix != ".py" or not p.is_file():
        return None
    if not any(p.is_relative_to(r.resolve()) for r in RUN_ROOTS):
        return None
    return p


def _registered():
    """path -> project it last pushed (TSV, append-only, last line wins;
    bare-path lines from the first registry format map to "")."""
    out = {}
    try:
        for line in RUN_REGISTRY.read_text().splitlines():
            if line.strip():
                path, _, project = line.partition("\t")
                out[path] = project
    except OSError:
        pass
    return out


def _register(p: Path, project: str):
    if _registered().get(str(p)) != project:
        RUN_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        with RUN_REGISTRY.open("a") as f:
            f.write(f"{p}\t{project}\n")
        log.info("runnable registry += %s (%s)", p, project)


def _module_for(store, project):
    """The registered module behind a project's scene: the stamped source if
    it earned registry entry, else the last module registered AS that project
    (covers scenes pushed before source stamping existed)."""
    reg = _registered()
    p = _runnable_path(store.meta.get(project, {}).get("source_file"))
    if p and str(p) in reg:
        return p
    for path, proj in reversed(list(reg.items())):
        if proj == project:
            return _runnable_path(path)
    return None


async def _broadcast_run(app, project, event):
    await broadcast(app, project, json.dumps({"type": "run", "project": project, **event}))


async def _run_module(app, project, path: Path):
    started = time.time()
    await _broadcast_run(app, project, {"status": "start", "path": path.name})
    proc = await asyncio.create_subprocess_exec(
        CAD_PYTHON, str(path), cwd=str(path.parent),
        env={**os.environ, "CADVIEW_SCENE": project},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=RUN_TIMEOUT)
        ok, tail = proc.returncode == 0, out.decode(errors="replace").strip().splitlines()[-4:]
    except asyncio.TimeoutError:
        proc.kill()
        ok, tail = False, [f"timed out after {RUN_TIMEOUT}s"]
    seconds = round(time.time() - started, 1)
    with RUN_LOG.open("a") as f:
        f.write("\t".join([time.strftime("%Y-%m-%dT%H:%M:%S%z"), project, str(path),
                           "ok" if ok else "fail", str(seconds)]) + "\n")
    log.info("run %s (%s): %s in %.1fs", path.name, project, "ok" if ok else "FAIL", seconds)
    event = {"status": "done" if ok else "error", "seconds": seconds,
             "tail": [t[-200:] for t in tail]}
    await _broadcast_run(app, project, event)
    return event


async def _run_target(request):
    """Shared validation for /api/run and /api/watch -> (project, path, body)."""
    _reject_cross_site(request, require_json=True)
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="want JSON")
    project = body.get("project", "")
    if not isinstance(project, str) or not PROJECT_RE.fullmatch(project):
        raise web.HTTPBadRequest(text="bad project")
    p = _module_for(request.app["store"], project)
    if p is None:
        raise web.HTTPForbidden(text="no registered runnable module for this project")
    return project, p, body


def _titles():
    """Human display names for scenes, editable server-side without a
    re-push (data dir titles.json) — the org-facing label; slugs stay
    for engineers/agents."""
    try:
        data = json.loads((DATA_DIR / "titles.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


async def handle_runnable(request):
    """The lite picker: every project with a scene, newest first, with the
    module behind it when one is registered. Paths stay server-side — the
    page only ever sees basenames and project names."""
    store = request.app["store"]
    titles = _titles()
    rows = []
    for project, meta in store.meta.items():
        module = _module_for(store, project)
        group = None
        src = meta.get("source_file")
        if src:
            try:
                group = _repo_root(Path(src)).name   # the project FOLDER
            except OSError:
                pass
        rows.append({"project": project, "name": meta.get("name"),
                     "title": meta.get("title") or titles.get(project),
                     "received_at": meta.get("received_at"),
                     "module": module.name if module else None,
                     "group": group})
    # scenes without a stamped source inherit their family's group by name
    # prefix (drop-in-panels-frame -> drop-in-panels), else stand alone
    named = {r["project"]: r for r in rows}
    for r in rows:
        if r["group"]:
            continue
        best = None
        for p in named:
            if p != r["project"] and r["project"].startswith(p + "-"):
                if best is None or len(p) > len(best):
                    best = p
        r["group"] = (named[best]["group"] or best) if best else r["project"]
    rows.sort(key=lambda r: r["received_at"] or "", reverse=True)
    return web.json_response({"projects": rows})


def _spawn_run(app, project, path: Path) -> bool:
    lock = app["run_locks"].setdefault(project, asyncio.Lock())
    if lock.locked():
        return False

    async def go():
        async with lock:
            await _run_module(app, project, path)
    task = asyncio.create_task(go())
    app["run_tasks"].add(task)
    task.add_done_callback(app["run_tasks"].discard)
    return True


async def handle_run(request):
    project, path, _body = await _run_target(request)
    if not _spawn_run(request.app, project, path):
        raise web.HTTPConflict(text="already running")
    return web.json_response({"ok": True, "project": project, "module": path.name}, status=202)


def _repo_root(path: Path) -> Path:
    """The module's git repo root (a scene script's imports usually span the
    repo — v7_3_stack edits must retrigger a tools/ script), else its dir."""
    for parent in [path.parent, *path.parent.parents]:
        if (parent / ".git").exists():
            return parent
    return path.parent


def _has_viewers(app, project) -> bool:
    return any(scope is None or scope == project for scope in app["websockets"].values())


async def _watch_loop(app, project, path: Path):
    """Watch is the DEFAULT (James, 2026-09-30): every registered module is
    re-run when *.py under its repo changes, no button involved. Poll —
    inotify isn't worth a dependency; scan capped so a huge tree can't spin
    the disk. Runs wait for the tree to go quiet one interval (an editor
    save burst = one rebuild), and with no viewer on the project the scene
    is only marked dirty — the rebuild fires when someone next opens it."""
    root = _repo_root(path)

    def snap():
        out = {}
        for i, f in enumerate(root.rglob("*.py")):
            if i >= 4000:
                break
            try:
                out[str(f)] = f.stat().st_mtime_ns
            except OSError:
                pass
        return out

    last = await asyncio.to_thread(snap)
    pending = False
    while True:
        await asyncio.sleep(1.5)
        try:
            cur = await asyncio.to_thread(snap)
            if cur != last:
                last = cur
                pending = True          # keep waiting for a quiet interval
                continue
            if not pending:
                continue
            pending = False
            if not _has_viewers(app, project):
                app["dirty"].add(project)
                continue
            _spawn_run(app, project, path)   # its push rewrites no *.py
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("watch loop for %s", project)


def _ensure_watch(app, project, path: Path):
    if project not in app["watchers"]:
        app["watchers"][project] = asyncio.create_task(_watch_loop(app, project, path))
        log.info("watch on: %s (%s)", project, path)


async def _start_watchers(app):
    for path_s, project in _registered().items():
        p = _runnable_path(path_s)
        if p and project and PROJECT_RE.fullmatch(project):
            _ensure_watch(app, project, p)


async def handle_watch(request):
    """Watch is on by default; this remains as an override (curl/agents) to
    pause a hot repo's auto-rebuilds or resume them — no UI drives it."""
    project, path, body = await _run_target(request)
    watchers = request.app["watchers"]
    if body.get("on", True):
        _ensure_watch(request.app, project, path)
    else:
        task = watchers.pop(project, None)
        if task:
            task.cancel()
            log.info("watch off: %s", project)
    return web.json_response({"ok": True, "watching": project in watchers})


# ---- live selection: the lite viewer streams what's selected; agents pull --
# Replaces say for the lite viewer (James, 2026-10-01): instead of typing a
# message AT an agent, he selects geometry and tells the agent in its own
# terminal/desktop session — the agent reads the selection via GET
# /api/selection or the cadview MCP tool (plain MCP, no channels preview).

async def handle_boot_error(request):
    """Startup-failure beacons from environments with no devtools (embedded
    panes) — log-only, so the fix can target the real exception."""
    body = (await request.read())[:2000]
    peer = _peer(request)
    log.warning("BOOT-ERROR from %s(%s): %s", DEVICE_LABELS.get(peer, peer), peer,
                body.decode(errors="replace"))
    return web.json_response({"ok": True})


async def handle_selection_post(request):
    _reject_cross_site(request, require_json=True)
    project = project_of(request, allow_none=False)
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="want JSON")
    selection = body.get("selection")
    if not isinstance(selection, list) or len(selection) > 100:
        raise web.HTTPBadRequest(text="want {selection: [...]} (≤100 items)")
    try:
        camera = validate_view(body.get("camera"))
    except ValueError:
        camera = None
    peer = _peer(request)
    request.app["selections"][project] = {
        "project": project,
        "selection": selection,
        "camera": camera,
        "revision": body.get("revision"),
        "device": DEVICE_LABELS.get(peer, peer),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    return web.json_response({"ok": True})


async def handle_selection_get(request):
    store = request.app["store"]
    project = project_of(request) or store.latest
    sel = request.app["selections"].get(project)
    meta = store.meta.get(project, {})
    return web.json_response({
        "project": project,
        "name": meta.get("title") or meta.get("name"),
        "scene_revision": meta.get("revision"),
        "units": meta.get("units", "mm"),
        **(sel or {"selection": [], "updated_at": None}),
    })


# ---- geometry: world-space part boxes from the stored scene -----------------
# Pure-python (no numpy): agents ask /api/parts for anchors instead of
# reading model source, and /api/clearance replays animation tracks against
# coarse AABBs server-side — the same check the viewer runs, minus the
# browser, so an authoring agent can verify its own choreography.

def _qmul(a, b):
    x1, y1, z1, w1 = a
    x2, y2, z2, w2 = b
    return (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)


def _qrot(q, v):
    x, y, z, w = q
    tx = 2 * (y * v[2] - z * v[1])
    ty = 2 * (z * v[0] - x * v[2])
    tz = 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + y * tz - z * ty,
            v[1] + w * ty + z * tx - x * tz,
            v[2] + w * tz + x * ty - y * tx)


def _axis_quat(axis, deg):
    h = math.radians(deg) / 2
    s_, c = math.sin(h), math.cos(h)
    return (axis[0] * s_, axis[1] * s_, axis[2] * s_, c)


def _scene_geometry(message):
    """-> (nodes, inst_bboxes): flat node list (parent links, base loc, leaf
    instance ref) + each instance's local vertex bbox."""
    inst_bb = []
    for inst in message["data"]["instances"]:
        buf = base64.b64decode(inst["vertices"]["buffer"])
        a = array.array("f", buf)
        xs, ys, zs = a[0::3], a[1::3], a[2::3]
        inst_bb.append(((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
                       if len(a) else ((0, 0, 0), (0, 0, 0)))
    nodes = []

    def walk(node, parent):
        idx = len(nodes)
        loc = node.get("loc") or [[0, 0, 0], [0, 0, 0, 1]]
        shape = node.get("shape")
        ref = shape.get("ref") if isinstance(shape, dict) else None
        nodes.append({"id": node.get("id"), "name": node.get("name"),
                      "t": tuple(loc[0]), "q": tuple(loc[1]), "parent": parent,
                      "ref": ref if node.get("type") == "shapes" else None})
        for child in node.get("parts") or []:
            walk(child, idx)
    walk(message["data"]["shapes"], -1)
    return nodes, inst_bb


def _world_boxes(nodes, inst_bb, overrides=None):
    """Per node: (translation, quaternion, visible); per LEAF: world AABB."""
    state = []
    boxes = {}
    for i, n in enumerate(nodes):
        t, q, vis = n["t"], n["q"], True
        if overrides and i in overrides:
            ot, oq, ovis = overrides[i]
            t = ot if ot is not None else t
            q = oq if oq is not None else q
            vis = ovis
        if n["parent"] >= 0:
            pt, pq, pvis = state[n["parent"]]
            t = tuple(a + b for a, b in zip(pt, _qrot(pq, t)))
            q = _qmul(pq, q)
            vis = vis and pvis
        state.append((t, q, vis))
        if n["ref"] is not None:
            lo, hi = inst_bb[n["ref"]]
            mins = [1e30] * 3
            maxs = [-1e30] * 3
            for cx in (lo[0], hi[0]):
                for cy in (lo[1], hi[1]):
                    for cz in (lo[2], hi[2]):
                        w = _qrot(q, (cx, cy, cz))
                        for k in range(3):
                            v = w[k] + t[k]
                            if v < mins[k]:
                                mins[k] = v
                            if v > maxs[k]:
                                maxs[k] = v
            boxes[i] = (tuple(mins), tuple(maxs))
    return state, boxes


def _geometry_for(app, project):
    store = app["store"]
    text = store.get(project)
    if text is None:
        raise web.HTTPNotFound(text="no scene pushed yet")
    revision = store.meta.get(project, {}).get("revision")
    cache = app["geom_cache"]
    key = (project, revision)
    if key not in cache:
        if len(cache) > 8:
            cache.clear()
        message = json.loads(text)
        nodes, inst_bb = _scene_geometry(message)
        cache[key] = (nodes, inst_bb, message.get("animations")
                      or ([{"name": "animation", **message["animation"]}]
                          if message.get("animation") else []))
    return cache[key]


async def handle_parts(request):
    """Anchors for agents: every node's path with its world bbox/center."""
    project = project_of(request) or request.app["store"].latest
    nodes, inst_bb, _ = await asyncio.to_thread(_geometry_for, request.app, project)
    _, boxes = _world_boxes(nodes, inst_bb)
    # group boxes = union of descendant leaves
    union = {}
    for i in range(len(nodes) - 1, -1, -1):
        own = boxes.get(i)
        for j in (k for k, n in enumerate(nodes) if n["parent"] == i):
            child = union.get(j)
            if child:
                own = child if own is None else (
                    tuple(map(min, own[0], child[0])), tuple(map(max, own[1], child[1])))
        if own:
            union[i] = own
    rows = []
    for i, n in enumerate(nodes):
        bb = union.get(i)
        if not bb or not n["id"]:
            continue
        lo, hi = bb
        rows.append({
            "path": n["id"], "kind": "part" if n["ref"] is not None else "group",
            "center": [round((a + b) / 2, 3) for a, b in zip(lo, hi)],
            "size": [round(b - a, 3) for a, b in zip(lo, hi)],
            "min": [round(v, 3) for v in lo], "max": [round(v, 3) for v in hi],
        })
    return web.json_response({"project": project, "units":
                              request.app["store"].meta.get(project, {}).get("units", "mm"),
                              "parts": rows})


def _sample_track(times, values, t):
    if t <= times[0]:
        return values[0]
    if t >= times[-1]:
        return values[-1]
    i = 1
    while times[i] < t:
        i += 1
    f = (t - times[i - 1]) / (times[i] - times[i - 1])
    f = f * f * (3 - 2 * f)          # smoothstep, like the viewer
    a, b = values[i - 1], values[i]
    if isinstance(a, list):
        return [x + (y - x) * f for x, y in zip(a, b)]
    return a + (b - a) * f


_CLEAR_EPS = 0.4


def _overlap(a, b):
    return all(a[0][k] < b[1][k] - _CLEAR_EPS and b[0][k] < a[1][k] - _CLEAR_EPS
               for k in range(3))


async def handle_clearance(request):
    """Replay animation tracks and report NEW AABB overlaps (pairs already
    touching at t=0 are baseline, parts rigid together are skipped) — the
    viewer's ⚠ check, callable by agents. Body: {project, tracks | clip,
    step}. `clip` is a pushed animation's name or index (default 0)."""
    _reject_cross_site(request, require_json=True)
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="want JSON")
    project = body.get("project") or request.app["store"].latest
    if not project or not PROJECT_RE.fullmatch(project):
        raise web.HTTPBadRequest(text="bad project")
    nodes, inst_bb, clips = await asyncio.to_thread(_geometry_for, request.app, project)
    raw = body.get("tracks")
    if raw is None:
        clip = body.get("clip", 0)
        match = [c for i, c in enumerate(clips)
                 if i == clip or c.get("name") == clip]
        if not match:
            raise web.HTTPBadRequest(text="no such clip and no tracks given")
        raw = match[0]["tracks"]
    tracks = []
    duration = 0.0
    for tr in raw:
        selector, action, times, values = (tr if isinstance(tr, list)
                                           else (tr["selector"], tr["action"], tr["times"], tr["values"]))
        targets = [i for i, n in enumerate(nodes)
                   if n["id"] and (n["id"] == selector or n["id"].endswith("/" + str(selector)))]
        if not targets or len(times) < 2:
            continue
        duration = max(duration, times[-1])
        tracks.append((targets, action, list(times), list(values)))
    if not tracks or duration <= 0:
        raise web.HTTPBadRequest(text="no resolvable tracks")
    step = min(max(float(body.get("step", 0.25)), 0.05), duration)

    def overrides_at(t):
        acc = {}
        for targets, action, times, values in tracks:
            v = _sample_track(times, values, t)
            for i in targets:
                st = acc.setdefault(i, [[0.0, 0.0, 0.0], (0.0, 0.0, 0.0, 1.0), True])
                if action == "t":
                    for k in range(3):
                        st[0][k] += v[k]
                elif action in ("tx", "ty", "tz"):
                    st[0][("tx", "ty", "tz").index(action)] += v
                elif action in ("rx", "ry", "rz"):
                    axis = {"rx": (1, 0, 0), "ry": (0, 1, 0), "rz": (0, 0, 1)}[action]
                    st[1] = _qmul(st[1], _axis_quat(axis, v))
                elif action == "vis":
                    st[2] = v > 0.5
        out = {}
        for i, (dt, dq, vis) in acc.items():
            base_t, base_q = nodes[i]["t"], nodes[i]["q"]
            out[i] = (tuple(a + b for a, b in zip(base_t, dt)),
                      _qmul(base_q, dq), vis)
        return out

    def run():
        animated = set()
        for targets, *_ in tracks:
            animated.update(targets)
        sig = {}
        for i, n in enumerate(nodes):
            if n["ref"] is None:
                continue
            chain, p = [], i
            while p >= 0:
                if p in animated:
                    chain.append(p)
                p = nodes[p]["parent"]
            sig[i] = tuple(chain)
        moving = [i for i, c in sig.items() if c]
        others = list(sig)
        _, base_boxes = _world_boxes(nodes, inst_bb, overrides_at(0.0))
        baseline = set()
        for m in moving:
            for o in others:
                if o == m or sig[m] == sig[o]:
                    continue
                key = (min(m, o), max(m, o))
                if key not in baseline and _overlap(base_boxes[m], base_boxes[o]):
                    baseline.add(key)
        hits = {}
        t = step
        samples = 0
        while t <= duration + 1e-9 and samples < 400:
            samples += 1
            state, boxes = _world_boxes(nodes, inst_bb, overrides_at(t))
            for m in moving:
                if not state[m][2]:
                    continue
                for o in others:
                    if o == m or sig[m] == sig[o] or not state[o][2]:
                        continue
                    key = (min(m, o), max(m, o))
                    if key in baseline or key in hits:
                        continue
                    if _overlap(boxes[m], boxes[o]):
                        hits[key] = round(t, 3)
            t += step
        return baseline, hits, samples

    baseline, hits, samples = await asyncio.to_thread(run)
    return web.json_response({
        "project": project, "duration": duration, "step": step,
        "samples": samples, "baseline_pairs": len(baseline),
        "hits": [{"a": nodes[a]["id"], "b": nodes[b]["id"], "first_t": t}
                 for (a, b), t in sorted(hits.items(), key=lambda kv: kv[1])],
    })


async def broadcast(app, project: str, text: str, meta=None) -> int:
    """Send text to viewers of that project and to unscoped viewers ("/"), pruning dead sockets."""
    notice = json.dumps({"type": "revision", "meta": {k: v for k, v in meta.items() if k != "part_fingerprints"}}) if meta else text
    async def send(ws):
        try:
            await asyncio.wait_for(ws.send_str(notice if ws in app["revision_sockets"] else text), timeout=5)
            return 1
        except (ConnectionError, RuntimeError, asyncio.TimeoutError):
            app["websockets"].pop(ws, None)
            asyncio.create_task(ws.close())
            return 0
    return sum(await asyncio.gather(*(send(ws) for ws, scope in list(app["websockets"].items())
                                      if scope is None or scope == project)))


async def handle_ws(request):
    scope = project_of(request)          # None = follow whatever project pushes
    ws = web.WebSocketResponse(heartbeat=30, compress=True)
    await ws.prepare(request)
    peer = request.remote
    log.info("viewer connected from %s scope=%s (%d total)", peer, scope, len(request.app["websockets"]))
    try:
        # current shell stamp: a page built from an older shell reloads itself
        # (old shells ignore unknown message types, so this is backward-safe)
        await ws.send_str(json.dumps({"type": "hello"}))
        # a watched project that changed while nobody was looking rebuilds now
        if scope and scope in request.app["dirty"]:
            request.app["dirty"].discard(scope)
            p = _module_for(request.app["store"], scope)
            if p:
                log.info("dirty %s: rebuilding for new viewer", scope)
                _spawn_run(request.app, scope, p)
        async with request.app["scene_lock"]:
            request.app["websockets"][ws] = scope
            if request.query.get("updates") == "revision":
                request.app["revision_sockets"].add(ws)
            store = request.app["store"]
            text = store.get(scope)
            meta = store.meta.get(scope or store.latest, {})
            if text is not None and request.query.get("revision") != meta.get("revision"):
                if ws in request.app["revision_sockets"]:
                    await ws.send_json({"type": "revision", "meta": {k: v for k, v in meta.items() if k != "part_fingerprints"}})
                else:
                    await asyncio.wait_for(ws.send_str(text), timeout=5)
            elif text is None:
                await ws.send_json({"type": "clear", "project": scope})
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
            # viewers don't need to send anything; ignore chatter
    finally:
        request.app["revision_sockets"].discard(ws)
        request.app["websockets"].pop(ws, None)
        log.info("viewer %s disconnected (%d left)", peer, len(request.app["websockets"]))
    return ws


async def _http_client(app):
    app["http"] = aiohttp.ClientSession()
    yield
    await app["http"].close()


def make_app() -> web.Application:
    app = web.Application(client_max_size=512 * 1024**2, middlewares=[device_gate])
    app["store"] = SceneStore()
    app["scene_lock"] = asyncio.Lock()
    app["revision_sockets"] = set()
    app["websockets"] = {}          # ws -> project scope (None = any)
    app["run_locks"] = {}           # project -> asyncio.Lock
    app["run_tasks"] = set()        # keep background runs alive
    app["watchers"] = {}            # project -> watch task (default-on)
    app["dirty"] = set()            # changed while unviewed -> rebuild on open
    app["selections"] = {}          # project -> current viewer selection
    app["geom_cache"] = {}          # (project, revision) -> nodes/instance boxes
    app.on_startup.append(_start_watchers)
    app.cleanup_ctx.append(_http_client)
    app.router.add_get("/", handle_lite)            # lite IS the viewer now
    app.router.add_get("/api/scene", handle_get_scene)
    app.router.add_post("/api/scene", handle_post_scene)
    app.router.add_delete("/api/scene", handle_delete_scene)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/history", handle_history)
    app.router.add_get("/ws", handle_ws)
    app.router.add_static("/static", STATIC_DIR)
    app.router.add_post("/api/boot-error", handle_boot_error)
    app.router.add_get("/api/parts", handle_parts)
    app.router.add_post("/api/clearance", handle_clearance)
    app.router.add_get("/api/selection", handle_selection_get)
    app.router.add_post("/api/selection", handle_selection_post)
    app.router.add_get("/api/runnable", handle_runnable)
    app.router.add_post("/api/run", handle_run)
    app.router.add_post("/api/watch", handle_watch)
    async def _lite_redirect(request):
        raise web.HTTPMovedPermanently("/" + request.match_info.get("project", ""))
    app.router.add_get("/lite", _lite_redirect)         # old URLs -> canonical
    app.router.add_get("/lite/{project}", _lite_redirect)
    app.router.add_get("/{project}", handle_lite)       # per-project viewer page, e.g. /mega-desk
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("CADVIEW_BIND", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("CADVIEW_PORT", "3941")))
    # optional HTTPS listener alongside HTTP — some embedded browsers only
    # run scripts on secure origins. Any cert works (mkcert, LetsEncrypt,
    # your mesh's cert tool); provisioning belongs to deployment, not here.
    parser.add_argument("--tls-cert", default=os.environ.get("CADVIEW_TLS_CERT"))
    parser.add_argument("--tls-key", default=os.environ.get("CADVIEW_TLS_KEY"))
    parser.add_argument("--tls-port", type=int,
                        default=int(os.environ.get("CADVIEW_TLS_PORT", "3943")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    access = (logging.getLogger("cadview.access")
              if os.environ.get("CADVIEW_ACCESS_LOG") else None)

    async def run():
        app = make_app()
        runner = web.AppRunner(app, access_log=access)
        await runner.setup()
        await web.TCPSite(runner, args.host, args.port).start()
        urls = [f"http://{args.host}:{args.port}"]
        if args.tls_cert and args.tls_key:
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(args.tls_cert, args.tls_key)
            await web.TCPSite(runner, args.host, args.tls_port, ssl_context=ctx).start()
            urls.append(f"https://{args.host}:{args.tls_port}")
        log.info("cadview server on %s (cache: %s)", " + ".join(urls), DATA_DIR)
        await asyncio.Event().wait()

    asyncio.run(run())


if __name__ == "__main__":
    main()
