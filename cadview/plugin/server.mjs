#!/usr/bin/env node
// cadview MCP server (zero-dep, stdio): lets any Claude Code session —
// terminal OR desktop app — read what's currently selected in a cadview
// viewer page. Plain MCP, no channels preview, no flags: the viewer
// streams its selection to the cadview server, this tool pulls it.
//
// Config via env (plugin user_config maps onto these):
//   CADVIEW_URL      default http://127.0.0.1:3941
//   CADVIEW_PROJECT  default project for the tools (else cwd dir name,
//                    which matches the default scene name of scripts run
//                    from that directory)

import { basename } from "node:path";

const URL_BASE = (process.env.CADVIEW_URL || "http://127.0.0.1:3941").replace(/\/+$/, "");
const DEFAULT_PROJECT = process.env.CADVIEW_PROJECT || basename(process.cwd());

const out = (msg) => process.stdout.write(JSON.stringify(msg) + "\n");
const reply = (id, result) => out({ jsonrpc: "2.0", id, result });

const TOOLS = [
    {
        name: "cadview_selection",
        description: "What the user currently has selected in the cadview viewer for a project: " +
            "parts/faces with world-space measurements (mm), plus his camera. Call this when he " +
            "say things like 'these should be longer' or 'the selected face' — the selection IS " +
            "the referent. Empty selection + old updated_at means nothing is selected right now.",
        inputSchema: {
            type: "object",
            properties: {
                project: {
                    type: "string",
                    description: `cadview project/scene name (default: ${DEFAULT_PROJECT})`,
                },
            },
        },
    },
    {
        name: "cadview_scenes",
        description: "List the scenes on the cadview server (project slug, display title, last push time).",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "cadview_parts",
        description: "Every part/group in a scene with its world-space bbox, center and size (mm) — " +
            "the anchors for writing animation tracks or resolving a part by name without reading model source.",
        inputSchema: {
            type: "object",
            properties: { project: { type: "string", description: `scene name (default: ${DEFAULT_PROJECT})` } },
        },
    },
    {
        name: "cadview_clearance",
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
    if (name === "cadview_selection") {
        const project = args.project || DEFAULT_PROJECT;
        const resp = await fetch(`${URL_BASE}/api/selection?name=${encodeURIComponent(project)}`,
                                 { signal: AbortSignal.timeout(10000) });
        if (!resp.ok) throw new Error("cadview server said HTTP " + resp.status);
        return JSON.stringify(await resp.json(), null, 1);
    }
    if (name === "cadview_scenes") {
        const resp = await fetch(`${URL_BASE}/api/runnable`, { signal: AbortSignal.timeout(10000) });
        if (!resp.ok) throw new Error("cadview server said HTTP " + resp.status);
        const rows = (await resp.json()).projects || [];
        return rows.map((r) => `${r.project}  ${r.title || r.name || ""}  (${r.received_at || "?"})`).join("\n");
    }
    if (name === "cadview_parts") {
        const project = args.project || DEFAULT_PROJECT;
        const resp = await fetch(`${URL_BASE}/api/parts?name=${encodeURIComponent(project)}`,
                                 { signal: AbortSignal.timeout(20000) });
        if (!resp.ok) throw new Error("cadview server said HTTP " + resp.status);
        return JSON.stringify(await resp.json(), null, 1);
    }
    if (name === "cadview_clearance") {
        const body = { ...args, project: args.project || DEFAULT_PROJECT };
        const resp = await fetch(`${URL_BASE}/api/clearance`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body), signal: AbortSignal.timeout(60000),
        });
        if (!resp.ok) throw new Error("cadview server said HTTP " + resp.status + ": " + await resp.text());
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
            serverInfo: { name: "cadview", version: "0.2.0" },
            instructions:
                "cadview viewer bridge. When the user refers to geometry deictically " +
                "('this face', 'these parts', 'the selected one'), call cadview_selection — " +
                "they picked the referent in the 3D viewer. cadview_parts gives every part's " +
                "world bbox (anchors for animation tracks); after authoring tracks, verify " +
                "them with cadview_clearance. Measurements are world-space mm.",
        });
    } else if (method === "tools/list") {
        reply(id, { tools: TOOLS });
    } else if (method === "tools/call") {
        try {
            const text = await callTool(params.name, params.arguments || {});
            reply(id, { content: [{ type: "text", text }] });
        } catch (e) {
            reply(id, { content: [{ type: "text", text: "failed: " + e.message }], isError: true });
        }
    } else if (method === "ping") {
        reply(id, {});
    } else if (id !== undefined) {
        out({ jsonrpc: "2.0", id, error: { code: -32601, message: "method not found" } });
    }
}
