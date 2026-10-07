# cadview — details

![mega desk in the viewer](ui.png)

## Using it from a script

Import swap only — everything else stays the same:

```python
from cadview import show      # was: from ocp_vscode import show
show(scene)
```

Nested `Compound` trees with `.label` / `.color` (alpha = transparency) come
through as the named part tree with per-part show/hide, colors and ghosting,
exactly like ocp_vscode. `names=`, `colors=`, `alphas=` lists work; unknown
ocp_vscode kwargs are accepted and ignored. `set_port()` / `set_host()` or
`CADVIEW_PORT` / `CADVIEW_HOST` override the push target (default
`127.0.0.1:3941`).

## Revisions

The server retains the current scene plus four prior revisions per project
(`GET /api/scene?name=<p>&revision=<id>`, `GET /api/history?name=<p>`).
Scenes survive restarts; camera and per-part visibility survive re-pushes.

## Animating — notes for agents

The conventions that matter when authoring tracks programmatically:

- **Anchors come from the server, not model source**: `GET
  /api/parts?name=<project>` lists every part/group path with its
  world-space bbox/center/size (mm). Selectors in tracks match these
  paths by trailing segment.
- **Joint origins**: a part rotates about its own node's origin — build
  articulated pieces as a `Compound` whose `.locate()` sits on the joint
  axis, with geometry extending away from it.
- **Tracks add**: two tracks on one node (a slide + a lift) sum; never
  encode combined motion into one track.
- **Verify before showing the human**: `POST /api/clearance` with
  `{project, tracks}` (or `{clip: "name"}` for a pushed animation)
  replays the motion against coarse AABBs and reports NEW collisions,
  with baseline contact and rigid groups excluded — the same check as
  the viewer's ⚠, headless. Intended contact (a probe entering a port)
  will flag; everything else flagging is a choreography bug.
- `cadview.Timeline` compiles phase-style calls into tracks if the
  parallel arrays get unwieldy (see its docstring).

The MCP plugin exposes all of this as `cadview_parts` /
`cadview_clearance` / `cadview_selection` tools.

## Faster iteration

Normal `show()` keeps the original tessellation quality. Transport now uses
faster gzip compression, compresses each stored scene once, and serves those
bytes to every viewer. WebSockets notify modern viewers of a revision; they
fetch only when needed. Unchanged geometry/settings skip browser download and
rendering entirely when `reset_camera="keep"` (the default).

For intentionally coarser previews:

```python
show(scene, quality="preview")
# Or for all subsequent calls in this process:
from cadview import set_defaults
set_defaults(quality="preview")
```

Preview uses deviation 0.4 / angular tolerance 0.4, versus standard 0.1 / 0.2.
Explicit `deviation=` and `angular_tolerance=` still take precedence. Edge
geometry remains available. `units="mm"` supplies a display label; it does not
convert geometry. `show()` prints tessellation, encoding/compression and send/store times;
browser-side timings sit on `cadviewLite.timings` in the page console.

## Architecture

- `cadview/client.py`: ocp-tessellate conversion and gzipped JSON POST.
- `cadview/server.py`: aiohttp, no CAD imports. Atomic per-project cache files
  at `~/.local/share/cadview/scene-<project>.json.gz`; four prior snapshots in
  `history/<project>/`. Mutations are serialized, revisions are UUIDs, and
  failed persistence leaves the published scene intact. Existing caches migrate
  automatically on load.
- `GET /api/scene?name=<project>[&revision=<id>]`, `GET /api/history?name=<project>`,
  `GET /api/status`; POST/DELETE `/api/scene?name=<project>`.
- `/ws?scene=<project>&updates=revision&revision=<known-id>` avoids replaying
  already-loaded scenes. Older WebSocket clients still receive full data.
- `static/lite/`: the viewer — buildless ES modules on vendored three.js.
- `GET /api/runnable` lists every scene (grouped by the pushing module's
  repo — the designs picker); display titles come from `show(title=...)`
  or the data dir's `titles.json`.
- **Live rebuilds**: a push from the server's own machine registers its
  script in the data dir's `runnable.txt`; the server then watches that
  repo's `*.py` and re-runs the script on change (`POST /api/run` /
  `/api/watch` to drive it manually), so editing a model updates every
  open tab hands-free.
- **Agent surface**: `GET /api/selection` (what's selected in the viewer),
  `GET /api/parts` (world bboxes), `POST /api/clearance` (headless
  collision replay) — all wrapped by the MCP plugin in `cadview/plugin/`.

## Validation

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Tests use temporary data dirs and synthetic box scenes — no real geometry,
no live scenes touched.

## Ops

Run it under your service manager of choice; it's a single process:

```bash
python -m cadview.server [--host H] [--port P]     # default 127.0.0.1:3941
```

Deployment knobs are environment variables, all optional: `CADVIEW_PEERS`
(extra allowed client IPs beyond loopback), `CADVIEW_CAD_PYTHON` (a separate
interpreter with the CAD stack, if the server runs CAD-free),
`CADVIEW_RUN_ROOTS`, `CADVIEW_DATA`, `CADVIEW_DEVICE_LABELS`,
`CADVIEW_HOME_ALIAS`, `CADVIEW_AUTOREG_PEERS`; `CADVIEW_TLS_CERT` /
`CADVIEW_TLS_KEY` / `CADVIEW_TLS_PORT` add an HTTPS listener alongside
HTTP (some embedded browsers only run scripts on secure origins — bring
any cert: mkcert, LetsEncrypt, your mesh's tool).
