#!/usr/bin/env node
// openworkshop MCP server (zero-dep, stdio): lets any Claude Code session —
// terminal OR desktop app — read what's currently selected in a openworkshop
// viewer page. Plain MCP, no channels preview, no flags: the viewer
// streams its selection to the openworkshop server, this tool pulls it.
//
// Config via env (plugin user_config maps onto these):
//   OPENWORKSHOP_URL      default http://127.0.0.1:3941
//   OPENWORKSHOP_PROJECT  default project for the tools (else cwd dir name,
//                    which matches the default scene name of scripts run
//                    from that directory)

import { basename } from "node:path";

const URL_BASE = (process.env.OPENWORKSHOP_URL || "http://127.0.0.1:3941").replace(/\/+$/, "");
const DEFAULT_PROJECT = process.env.OPENWORKSHOP_PROJECT || basename(process.cwd());

const out = (msg) => process.stdout.write(JSON.stringify(msg) + "\n");
const reply = (id, result) => out({ jsonrpc: "2.0", id, result });

const TOOLS = [
    {
        name: "openworkshop_selection",
        description: "What the user currently has selected in the openworkshop viewer for a project: " +
            "parts/faces with world-space measurements (mm), plus his camera. Call this when he " +
            "say things like 'these should be longer' or 'the selected face' — the selection IS " +
            "the referent. Empty selection + old updated_at means nothing is selected right now.",
        inputSchema: {
            type: "object",
            properties: {
                project: {
                    type: "string",
                    description: `openworkshop project/scene name (default: ${DEFAULT_PROJECT})`,
                },
            },
        },
    },
    {
        name: "openworkshop_scenes",
        description: "List the scenes on the openworkshop server (project slug, display title, last push time).",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "openworkshop_parts",
        description: "Every part/group in a scene with its world-space bbox, center and size (mm) — " +
            "the anchors for writing animation tracks or resolving a part by name without reading model source.",
        inputSchema: {
            type: "object",
            properties: { project: { type: "string", description: `scene name (default: ${DEFAULT_PROJECT})` } },
        },
    },
    {
        name: "openworkshop_snapshot",
        description: "A rendered PNG of a scene straight from the viewer, WITHOUT touching the page the user " +
            "is looking at (it renders in a hidden frame of an open openworkshop page). Use it to look at a design " +
            "or check your own change — never navigate the user's browser pane for that. view: iso (default) | " +
            "top | bottom | front | back | left | right; focus: part id/label/path suffix to frame (comma list); " +
            "hide / only: parts to hide / keep (same selectors); zoom: >1 closer; for animated scenes clip + t " +
            "(seconds) pose the clip at a time. w/h pixels (default 1200x800).",
        inputSchema: {
            type: "object",
            properties: {
                project: { type: "string", description: `scene name (default: ${DEFAULT_PROJECT})` },
                view: { type: "string" }, focus: { type: "string" }, hide: { type: "string" },
                only: { type: "string" }, zoom: { type: "number" },
                yaw: { type: "number", description: "degrees to spin the camera about its up axis around the target (turntable)" },
                t: { type: "number" },
                clearance: { type: "number", description: "0 to leave the collision tint out of the shot" },
                clip: { description: "clip name or index" },
                chapter: { type: "string", description: "a clip chapter's name — the shot is taken at its time (instead of t)" },
                w: { type: "number" }, h: { type: "number" },
            },
        },
    },
    {
        name: "openworkshop_clearance",
        description: "Replay animation tracks against the scene's coarse AABBs and report NEW collisions " +
            "(pairs already touching at rest are baseline; parts moving rigidly together are skipped). " +
            "Verify choreography you just authored: pass tracks [[selector, action, times, values], ...], " +
            "or clip (name/index) to check an animation already pushed with the scene.",
        inputSchema: {
            type: "object",
            properties: {
                project: { type: "string", description: `scene name (default: ${DEFAULT_PROJECT})` },
                tracks: { type: "array", description: "tracks to test; omit to use a pushed clip" },
                clip: { description: "pushed clip name or index (default 0)" },
                step: { type: "number", description: "sample interval seconds (default 0.25)" },
            },
        },
    },
];

async function callTool(name, args) {
    if (name === "openworkshop_selection") {
        const project = args.project || DEFAULT_PROJECT;
        const resp = await fetch(`${URL_BASE}/api/selection?name=${encodeURIComponent(project)}`,
                                 { signal: AbortSignal.timeout(10000) });
        if (!resp.ok) throw new Error("openworkshop server said HTTP " + resp.status);
        return JSON.stringify(await resp.json(), null, 1);
    }
    if (name === "openworkshop_scenes") {
        const resp = await fetch(`${URL_BASE}/api/runnable`, { signal: AbortSignal.timeout(10000) });
        if (!resp.ok) throw new Error("openworkshop server said HTTP " + resp.status);
        const rows = (await resp.json()).projects || [];
        return rows.map((r) => `${r.project}  ${r.title || r.name || ""}  (${r.received_at || "?"})`).join("\n");
    }
    if (name === "openworkshop_parts") {
        const project = args.project || DEFAULT_PROJECT;
        const resp = await fetch(`${URL_BASE}/api/parts?name=${encodeURIComponent(project)}`,
                                 { signal: AbortSignal.timeout(20000) });
        if (!resp.ok) throw new Error("openworkshop server said HTTP " + resp.status);
        return JSON.stringify(await resp.json(), null, 1);
    }
    if (name === "openworkshop_snapshot") {
        const project = args.project || DEFAULT_PROJECT;
        const q = new URLSearchParams({ name: project });
        for (const k of ["view", "focus", "hide", "only", "zoom", "yaw", "t", "clip", "chapter", "clearance", "w", "h"])
            if (args[k] != null && args[k] !== "") q.set(k, String(args[k]));
        const resp = await fetch(`${URL_BASE}/api/snapshot?${q}`, { signal: AbortSignal.timeout(70000) });
        if (!resp.ok) throw new Error("openworkshop server said HTTP " + resp.status + ": " + await resp.text());
        const data = Buffer.from(await resp.arrayBuffer()).toString("base64");
        return [{ type: "image", data, mimeType: "image/png" },
                { type: "text", text: `${project} — ${args.view || "iso"}${args.focus ? " focus " + args.focus : ""}` }];
    }
    if (name === "openworkshop_clearance") {
        const body = { ...args, project: args.project || DEFAULT_PROJECT };
        const resp = await fetch(`${URL_BASE}/api/clearance`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body), signal: AbortSignal.timeout(60000),
        });
        if (!resp.ok) throw new Error("openworkshop server said HTTP " + resp.status + ": " + await resp.text());
        return JSON.stringify(await resp.json(), null, 1);
    }
    throw new Error("unknown tool " + name);
}

let buf = "";
process.stdin.on("data", (chunk) => {
    buf += chunk;
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
        const lineText = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!lineText) continue;
        let msg;
        try { msg = JSON.parse(lineText); } catch { continue; }
        handle(msg).catch(() => { });
    }
});

async function handle(msg) {
    const { id, method, params } = msg;
    if (method === "initialize") {
        reply(id, {
            protocolVersion: params?.protocolVersion || "2024-11-05",
            capabilities: { tools: {} },
            serverInfo: { name: "openworkshop", version: "0.3.0" },
            instructions:
                "openworkshop viewer bridge. When the user refers to geometry deictically " +
                "('this face', 'these parts', 'the selected one'), call openworkshop_selection — " +
                "they picked the referent in the 3D viewer. openworkshop_parts gives every part's " +
                "world bbox (anchors for animation tracks); after authoring tracks, verify " +
                "them with openworkshop_clearance. To LOOK at a design or your change, call " +
                "openworkshop_snapshot — it renders off-screen; never navigate the user's browser " +
                "pane to check your own work. Measurements are world-space mm.",
        });
    } else if (method === "tools/list") {
        reply(id, { tools: TOOLS });
    } else if (method === "tools/call") {
        try {
            const r = await callTool(params.name, params.arguments || {});
            reply(id, { content: Array.isArray(r) ? r : [{ type: "text", text: r }] });
        } catch (e) {
            reply(id, { content: [{ type: "text", text: "failed: " + e.message }], isError: true });
        }
    } else if (method === "ping") {
        reply(id, {});
    } else if (id !== undefined) {
        out({ jsonrpc: "2.0", id, error: { code: -32601, message: "method not found" } });
    }
}
