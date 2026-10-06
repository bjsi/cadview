# cadview MCP — the viewer, for agents

Four stdio tools over plain MCP (no flags, works in the Claude Code
desktop app and terminal alike):

- **`cadview_selection`** — what the user has selected on the viewer page
  right now: parts/faces with world-space measurements and the camera.
  "Make these 5 mm taller" resolves through this.
- **`cadview_parts`** — every part/group in a scene with world bbox,
  center and size: the anchors for writing animation tracks without
  reading model source.
- **`cadview_clearance`** — replay animation tracks (or a pushed clip)
  against the scene's AABBs and get NEW collisions back, baseline contact
  and rigid groups excluded. Author, verify, then show the human.
- **`cadview_scenes`** — what's on the server.

## Wiring

`.mcp.json` in the project you run Claude Code from:

```json
{
    "mcpServers": {
        "cadview": {
            "command": "node",
            "args": ["/path/to/cadview/cadview/plugin/server.mjs"],
            "env": { "CADVIEW_PROJECT": "my-project" }
        }
    }
}
```

`CADVIEW_URL` defaults to `http://127.0.0.1:3941`; `CADVIEW_PROJECT`
defaults to the directory Claude was launched from, which matches the
default scene name of scripts pushed from there. Agents without MCP can
hit the HTTP endpoints directly (`/api/selection`, `/api/parts`,
`/api/clearance` — see docs/DETAILS.md).
