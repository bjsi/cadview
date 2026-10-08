"""Build guide — the assembly clip's chapters as IKEA-style step pages.

    python -m openworkshop.guide <scene> [-o guide.html] [--clip NAME] [--notes guide.json]
                                 [--url http://127.0.0.1:3941] [--size 900x600]

A clip with chapters is a build order: each chapter is a step, and the parts
whose tracks change inside the step (a `vis` 0 -> 1, a move that starts) are
the parts that step adds. For every step the page gets a picture shot through
the server's snapshot route — the state at the END of the step, the parts
already in place ghosted, the new ones in colour, from the chapter's camera —
the list of what arrives (like parts counted together: "4 × bracket"), and
whatever the notes file says about it. One self-contained HTML file: phone
sized, big prev / next, arrow keys, prints as one page per step.

Notes file (optional JSON; keys are chapter names):

    {"title": "Mega desk", "intro": "Two people, 40 min. Lay the MDF face down first.",
     "steps": {"legs":  {"note": "Long legs go at the back.", "fasteners": ["8 × M8×16 + T-nut"], "tools": ["6 mm hex"]},
               "frame": {"note": "Tighten after the top is on."}}}

Parts that never move in the clip are treated as present from the start.
Needs only a running server with an open page (the snapshot route renders in
a hidden frame of it) — no CAD stack.
"""
import argparse
import base64
import html
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

from openworkshop.bake import get, scene_message

_DUP = re.compile(r"\(\d+\)$")      # "bracket(2)" -> "bracket"


def leaves(shapes):
    """[(id, name)] of every leaf part, and {group id: [leaf ids]}."""
    out, groups = [], {}

    def walk(node, parents):
        nid = node.get("id") or node.get("name")
        if "parts" in node:
            groups[nid] = []
            for child in node["parts"]:
                walk(child, parents + [nid])
            return
        out.append((nid, node.get("name") or nid.rsplit("/", 1)[-1]))
        for p in parents:
            groups[p].append(nid)

    walk(shapes, [])
    return out, groups


def resolve(selector, leaf_ids, groups):
    """The viewer's rule: an exact node id, else every node whose id ends in '/<selector>'.
    A group resolves to the leaves under it."""
    sel = str(selector)
    ids = [sel] if sel in groups or sel in leaf_ids else [i for i in list(groups) + leaf_ids if i.endswith("/" + sel)]
    out = []
    for i in ids:
        out += groups.get(i, [i])
    return out


def steps_of(msg, clip_name=None):
    """[{name, t0, t1, camera, parts: [leaf ids]}] from the clip's chapters."""
    clips = [c for c in msg.get("animations") or [] if c.get("chapters")]
    if not clips:
        sys.exit("the scene has no clip with chapters")
    clip = next((c for c in clips if c["name"] == clip_name), None) if clip_name else clips[0]
    if clip is None:
        sys.exit(f"no clip named {clip_name!r}; chapters in: {[c['name'] for c in clips]}")
    leaf, groups = leaves(msg["data"]["shapes"])
    leaf_ids = [i for i, _ in leaf]
    chapters = sorted(({"t": float(c["t"]), "name": c["name"], "camera": c.get("camera")} for c in clip["chapters"]), key=lambda c: c["t"])
    end = max((t for tr in clip["tracks"] for t in tr[2]), default=0.0)
    # when does a selector arrive? the moment its `vis` turns on if it has one
    # (a part parked out of sight until its step), else the start of its first
    # real move (a zero-length "park it here" segment at t=0 is not a move)
    shown, moved = {}, {}
    for sel, action, times, values in clip["tracks"]:
        for k in range(1, len(times)):
            if values[k] == values[k - 1]:
                continue
            if action == "vis":
                if values[k] > 0.5:
                    shown[sel] = min(shown.get(sel, 1e9), times[k])
            elif times[k] > times[k - 1] + 1e-6:
                moved[sel] = min(moved.get(sel, 1e9), times[k - 1])
    arrival = {sel: shown.get(sel, moved.get(sel)) for sel in set(shown) | set(moved)}
    steps = []
    for i, ch in enumerate(chapters):
        t1 = chapters[i + 1]["t"] if i + 1 < len(chapters) else end + 1e-6
        arriving = []
        for sel, t in sorted(arrival.items(), key=lambda kv: kv[1]):
            if ch["t"] <= t < t1 or (i == 0 and t < ch["t"]):
                arriving += resolve(sel, leaf_ids, groups)
        seen = set()
        parts = [p for p in arriving if not (p in seen or seen.add(p))]
        steps.append({"name": ch["name"], "t0": ch["t"], "t1": t1, "camera": ch["camera"], "parts": parts})
    moving = {p for s in steps for p in s["parts"]}
    static = [i for i in leaf_ids if i not in moving]
    names = dict(leaf)
    return clip["name"], steps, static, names


def counted(ids, names):
    """[(count, display name)] — duplicates of one label counted together, in first-seen order."""
    out, order = {}, []
    for i in ids:
        n = _DUP.sub("", names.get(i, i)).strip()
        if n not in out:
            order.append(n)
        out[n] = out.get(n, 0) + 1
    return [(out[n], n) for n in order]


def _short(ids):
    """The viewer resolves a bare last path segment ('bracket(2)') to the node(s) that end in it —
    short enough that a whole build fits in one URL."""
    out, seen = [], set()
    for i in ids:
        s = i.rsplit("/", 1)[-1]
        if s not in seen:
            seen.add(s); out.append(s)
    return ",".join(out)


def snapshot(url, scene, clip, step, only, ghost, size):
    q = {"name": scene, "clip": clip, "chapter": step["name"], "t": f"{max(step['t0'], step['t1'] - 0.01):.3f}",
         "only": _short(only), "ghost": _short(ghost), "clearance": "0", "bg": "ffffff", "w": size[0], "h": size[1]}
    if not step["camera"]:
        q.update({"view": "iso", "zoom": "1.2"})
    return get(url, "/api/snapshot?" + urllib.parse.urlencode(q))


CSS = """
:root { --ink: #1b1f27; --muted: #6b7280; --line: #e5e7eb; --accent: #d97706; --bg: #fff; }
* { box-sizing: border-box; }
body { margin: 0; font: 17px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }
header { position: sticky; top: 0; background: var(--bg); border-bottom: 1px solid var(--line); padding: 10px 16px; display: flex; gap: 12px; align-items: baseline; z-index: 2; }
header h1 { font-size: 18px; margin: 0; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
header .pos { color: var(--muted); font-variant-numeric: tabular-nums; }
main { max-width: 760px; margin: 0 auto; padding: 0 16px 120px; }
section.step { display: none; padding-top: 12px; }
section.step.on { display: block; }
section.step h2 { font-size: 28px; margin: 8px 0 4px; }
section.step h2 small { color: var(--accent); font-size: 16px; font-weight: 600; letter-spacing: .04em; display: block; }
section.step img { width: 100%; border-radius: 10px; border: 1px solid var(--line); background: #fff; display: block; }
.note { margin: 12px 0 0; font-size: 18px; }
.lists { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; margin-top: 12px; }
.lists h3 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 10px 0 4px; }
.lists ul { margin: 0; padding: 0; list-style: none; }
.lists li { padding: 6px 0; border-top: 1px solid var(--line); display: flex; gap: 10px; }
.lists li b { min-width: 2.4em; color: var(--accent); font-variant-numeric: tabular-nums; }
section.kit table { width: 100%; border-collapse: collapse; margin-top: 8px; }
section.kit td { padding: 6px 4px; border-top: 1px solid var(--line); }
section.kit td:first-child { width: 3em; color: var(--accent); font-weight: 700; text-align: right; padding-right: 12px; }
nav { position: fixed; left: 0; right: 0; bottom: 0; display: flex; gap: 10px; padding: 12px 16px calc(12px + env(safe-area-inset-bottom)); background: var(--bg); border-top: 1px solid var(--line); }
nav button { flex: 1; font: inherit; font-size: 20px; font-weight: 600; padding: 14px; border-radius: 12px; border: 1px solid var(--line); background: #f9fafb; color: var(--ink); }
nav button.next { background: var(--ink); color: #fff; border-color: var(--ink); }
nav button:disabled { opacity: .35; }
footer { color: var(--muted); font-size: 13px; margin-top: 24px; }
@media (max-width: 480px) { .lists { grid-template-columns: 1fr; } }
@media print { header, nav { display: none; } section.step { display: block; page-break-after: always; } main { padding: 0; max-width: none; } }
"""

JS = """
const steps = [...document.querySelectorAll("section.step")];
let i = Math.min(steps.length - 1, Math.max(0, parseInt(location.hash.slice(1)) || 0));
const prev = document.getElementById("prev"), next = document.getElementById("next"), pos = document.getElementById("pos");
function show(k) {
    i = k; steps.forEach((s, j) => s.classList.toggle("on", j === i));
    prev.disabled = i === 0; next.textContent = i === steps.length - 1 ? "Done" : "Next →";
    pos.textContent = (i + 1) + " / " + steps.length; history.replaceState(null, "", "#" + i); window.scrollTo(0, 0);
}
prev.onclick = () => show(Math.max(0, i - 1));
next.onclick = () => show(Math.min(steps.length - 1, i + 1));
addEventListener("keydown", (e) => { if (e.key === "ArrowRight") next.click(); if (e.key === "ArrowLeft") prev.click(); });
show(i);
"""


def build_html(title, intro, clip, steps, static, names, images, notes, scene_url):
    esc = html.escape
    parts = []
    # step 0: the kit — everything in the build, counted
    kit = counted([p for s in steps for p in s["parts"]], names)
    kit_rows = "".join(f"<tr><td>{n}×</td><td>{esc(name)}</td></tr>" for n, name in kit)
    fast = sorted({f for s in steps for f in (notes.get("steps", {}).get(s["name"], {}).get("fasteners") or [])})
    tools = sorted({t for s in steps for t in (notes.get("steps", {}).get(s["name"], {}).get("tools") or [])})
    extra = ""
    if fast:
        extra += "<h3>Fasteners</h3><ul>" + "".join(f"<li>{esc(f)}</li>" for f in fast) + "</ul>"
    if tools:
        extra += "<h3>Tools</h3><ul>" + "".join(f"<li>{esc(t)}</li>" for t in tools) + "</ul>"
    ctx = counted(static, names)
    ctx_html = ("<p class=note>Already in place: " + ", ".join(f"{n}× {esc(m)}" for n, m in ctx) + "</p>") if ctx else ""
    parts.append(f'<section class="step kit on"><h2><small>Before you start</small>{esc(title)}</h2>'
                 f'{("<p class=note>" + esc(intro) + "</p>") if intro else ""}'
                 f'<img src="data:image/png;base64,{images["kit"]}" alt="the finished build">'
                 f'<div class=lists><div><h3>Parts · {sum(n for n, _ in kit)}</h3><table>{kit_rows}</table></div><div>{extra}</div></div>{ctx_html}</section>')
    for k, s in enumerate(steps, 1):
        n = notes.get("steps", {}).get(s["name"], {})
        rows = "".join(f"<li><b>{c}×</b><span>{esc(name)}</span></li>" for c, name in counted(s["parts"], names))
        fl = "".join(f"<li><span>{esc(f)}</span></li>" for f in (n.get("fasteners") or []))
        tl = "".join(f"<li><span>{esc(t)}</span></li>" for t in (n.get("tools") or []))
        side = (f"<div><h3>Fasteners</h3><ul>{fl}</ul></div>" if fl else "") + (f"<div><h3>Tools</h3><ul>{tl}</ul></div>" if tl else "")
        parts.append(f'<section class="step" id="s{k}"><h2><small>Step {k} of {len(steps)}</small>{esc(s["name"])}</h2>'
                     f'<img src="data:image/png;base64,{images[s["name"]]}" alt="step {k}: {esc(s["name"])}">'
                     f'{("<p class=note>" + esc(n["note"]) + "</p>") if n.get("note") else ""}'
                     f'<div class=lists><div><h3>Add</h3><ul>{rows}</ul></div>{side}</div></section>')
    body = "".join(parts)
    link = f'<a href="{esc(scene_url)}">open the 3D model</a> · ' if scene_url else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(title)} — build guide</title><style>{CSS}</style></head><body>'
            f'<header><h1>{esc(title)}</h1><span class=pos id=pos></span></header><main>{body}'
            f'<footer>{link}built from the “{esc(clip)}” clip with openworkshop.guide</footer></main>'
            f'<nav><button id=prev>&larr; Back</button><button id=next class=next>Next &rarr;</button></nav>'
            f'<script>{JS}</script></body></html>')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("-o", "--output", help="guide HTML (default: <scene>-guide.html)")
    ap.add_argument("--clip", help="clip name (default: the first clip that has chapters)")
    ap.add_argument("--notes", help="JSON with title / intro / per-step note, fasteners, tools")
    ap.add_argument("--url", default=os.environ.get("OPENWORKSHOP_URL", "http://127.0.0.1:3941"))
    ap.add_argument("--size", default="900x600", help="picture size WxH (default 900x600)")
    a = ap.parse_args(argv)
    url = a.url.rstrip("/")
    size = tuple(int(x) for x in a.size.lower().split("x"))
    notes = json.loads(Path(a.notes).read_text()) if a.notes else {}
    msg = scene_message(url, a.scene)
    clip, steps, static, names = steps_of(msg, a.clip)
    title = notes.get("title") or msg.get("meta", {}).get("title") or msg.get("meta", {}).get("name") or a.scene
    images, placed = {}, list(static)
    for s in steps:
        images[s["name"]] = base64.b64encode(snapshot(url, a.scene, clip, s, placed + s["parts"], placed, size)).decode()
        placed += s["parts"]
        print(f"step {s['name']}: {len(s['parts'])} part(s)", file=sys.stderr)
    final = dict(steps[-1], camera=None)
    images["kit"] = base64.b64encode(snapshot(url, a.scene, clip, final, placed, [], size)).decode()
    page = build_html(title, notes.get("intro"), clip, steps, static, names, images, notes, f"{url}/{a.scene}")
    out = Path(a.output) if a.output else Path(f"{a.scene}-guide.html")
    out.write_text(page)
    print(f"{out}  {len(steps)} steps, {len(page) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
