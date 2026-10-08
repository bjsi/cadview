# openworkshop MCP — the viewer, for agents

Four stdio tools over plain MCP (no flags, works in the Claude Code
desktop app and terminal alike):

- **`openworkshop_selection`** — what the user has selected on the viewer page
  right now: parts/faces with world-space measurements and the camera.
  "Make these 5 mm taller" resolves through this.
- **`openworkshop_parts`** — every part/group in a scene with world bbox,
  center and size: the anchors for writing animation tracks without
  reading model source.
- **`openworkshop_clearance`** — replay animation tracks (or a pushed clip)
  against the scene's AABBs and get NEW collisions back, baseline contact
  and rigid groups excluded. Author, verify, then show the human.
- **`openworkshop_scenes`** — what's on the server.

## Wiring

`.mcp.json` in the project you run Claude Code from — with openworkshop
installed as a package (any venv/uv layout):

```json
{
    "mcpServers": {
        "openworkshop": {
            "command": "uv",
            "args": ["run", "python", "-m", "openworkshop.mcp"]
        }
    }
}
```

(Or `"command": "node", "args": ["/path/to/openworkshop/openworkshop/plugin/server.mjs"]`
from a checkout. Needs node on PATH either way.)

`OPENWORKSHOP_URL` defaults to `http://127.0.0.1:3941`; `OPENWORKSHOP_PROJECT`
defaults to the directory Claude was launched from, which matches the
default scene name of scripts pushed from there. Agents without MCP can
hit the HTTP endpoints directly (`/api/selection`, `/api/parts`,
`/api/clearance` — see docs/DETAILS.md).
