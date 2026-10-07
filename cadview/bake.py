"""Bake viewer pages from a running cadview server — review pages for a PR,
a demo site, an offline hand-off. No CAD stack needed, just the server.

    python -m cadview.bake --single-file [--changed-vs BUNDLE] [outdir] [scene ...]
    python -m cadview.bake [outdir] [scene ...]

--single-file   one self-contained <scene>.html per scene: the viewer,
                three.js and the gzipped scene inlined. Opens from file://
                or an email attachment, full orbit / part tree / hide /
                measure / animation, nothing fetched. ~1 MB + the scene.
--changed-vs    keep only scenes whose parts or animation differ from the
                scenes in BUNDLE (a cadview-scenes.tar.gz as published by a
                repo's scenes workflow) — "what this PR changed", part by
                part: outdir/changed.json has changed/unchanged scenes and,
                per scene, the changed / added / removed part paths. Parts
                are compared by a rebuild-stable signature (counts, face
                types, bbox, area, placement, colour), not by mesh bytes.
default         a static site: index.html (gallery), scenes.json,
                scenes/<p>.json, thumbs/<p>.png, <p>/index.html (base
                href ../); serve it from any static host.

Server: CADVIEW_URL or --url (default http://127.0.0.1:3941). Push-side
meta (source paths, owners) is stripped: bake only what a viewer needs.
"""
import argparse
import base64
import gzip
import hashlib
import html
import json
import os
import shutil
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LITE = Path(__file__).resolve().parent / "static" / "lite"
KEEP_META = ("name", "title", "project", "units", "revision", "pushed_at", "received_at")


def get(url, path):
    with urllib.request.urlopen(url + path, timeout=300) as r:
        return r.read()


def scene_message(url, project):
    msg = json.loads(get(url, "/api/scene?name=" + urllib.parse.quote(project)))
    msg["meta"] = {k: v for k, v in msg.get("meta", {}).items() if k in KEEP_META}
    return msg


_TYPECODES = {"float32": "f", "float64": "d", "int32": "i", "uint32": "I", "int64": "q", "uint64": "Q",
              "int16": "h", "uint16": "H", "int8": "b", "uint8": "B"}


def _numbers(field):
    """A buffer-json field ({shape, dtype, buffer}) as a flat list of numbers."""
    import array
    import base64
    a = array.array(_TYPECODES[field["dtype"]])
    a.frombytes(base64.b64decode(field["buffer"]))
    return a.tolist()


def part_signatures(msg):
    """{part path: signature} — what a reviewer means by 'this part changed'.

    Tessellation is not bit-stable from one build to the next (vertex order,
    last-digit noise), so hashing the mesh flags phantom diffs. The signature
    uses what survives a rebuild of identical inputs: vertex / triangle counts,
    the face-type histogram, the bounding box and mesh area rounded to a
    thousandth, the placement chain, colour and alpha."""
    data = msg.get("data") or {}
    instances = data.get("instances") or []
    out = {}

    def mesh_sig(inst):
        v = _numbers(inst["vertices"]) if "vertices" in inst else []
        t = _numbers(inst["triangles"]) if "triangles" in inst else []
        pts = [v[i:i + 3] for i in range(0, len(v) - 2, 3)]
        bbox = [round(f(c[k] for c in pts), 3) for k in range(3) for f in (min, max)] if pts else []
        area = 0.0
        for i in range(0, len(t) - 2, 3):
            a, b, c = pts[t[i]], pts[t[i + 1]], pts[t[i + 2]]
            ab = [b[k] - a[k] for k in range(3)]
            ac = [c[k] - a[k] for k in range(3)]
            cx, cy, cz = ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]
            area += (cx * cx + cy * cy + cz * cz) ** 0.5 / 2
        faces = sorted(_numbers(inst["face_types"])) if "face_types" in inst else []
        hist = {}
        for ft in faces:
            hist[str(ft)] = hist.get(str(ft), 0) + 1
        return {"vertices": len(pts), "triangles": len(t) // 3, "bbox": bbox, "area": round(area, 2), "faces": hist}

    def walk(node, chain):
        chain = chain + [[[round(x, 4) for x in part] for part in node["loc"]] if node.get("loc") else None]
        if "parts" in node:
            for child in node["parts"]:
                walk(child, chain)
            return
        shape = node.get("shape")
        inst = instances[shape["ref"]] if isinstance(shape, dict) and isinstance(shape.get("ref"), int) else shape
        body = {"mesh": mesh_sig(inst) if isinstance(inst, dict) else None, "loc": chain,
                "color": node.get("color"), "alpha": node.get("alpha")}
        path = node.get("id") or node.get("name", "part")
        out[path] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]

    if data.get("shapes"):
        walk(data["shapes"], [])
    return out


def scene_diff(before, after):
    """{changed, added, removed: [part paths], animation: bool} between two scene messages."""
    a, b = part_signatures(before), part_signatures(after)
    anim = lambda m: json.dumps({"animations": m.get("animations"), "config": m.get("config")}, sort_keys=True)
    return {"changed": sorted(p for p in a if p in b and a[p] != b[p]),
            "added": sorted(p for p in b if p not in a),
            "removed": sorted(p for p in a if p not in b),
            "animation": anim(before) != anim(after)}


def bundle_scenes(path):
    """project -> scene message for every scene in a cadview-scenes.tar.gz."""
    out = {}
    with tarfile.open(path, "r:gz") as tar:
        for m in tar.getmembers():
            name = Path(m.name).name
            if m.isfile() and name.startswith("scene-") and name.endswith(".json.gz"):
                out[name[len("scene-"):-len(".json.gz")]] = json.loads(gzip.decompress(tar.extractfile(m).read()))
    return out


def _data_url(text):
    return "data:text/javascript;base64," + base64.b64encode(text.encode()).decode()


def single_file_html(msg, title=None):
    """The lite viewer page with three.js and the scene inlined."""
    page = (LITE / "index.html").read_text()
    core = (LITE / "vendor" / "three.core.min.js").read_text()
    module = (LITE / "vendor" / "three.module.min.js").read_text()
    orbit = (LITE / "vendor" / "OrbitControls.js").read_text()
    lite = (LITE / "lite.js").read_text()
    # module specifiers can't be relative inside data: URLs — name them
    assert '"./three.core.min.js"' in module and '"./vendor/OrbitControls.js"' in lite
    module = module.replace('"./three.core.min.js"', '"three-core"')
    lite = lite.replace('"./vendor/OrbitControls.js"', '"orbit"')
    importmap = json.dumps({"imports": {"three": _data_url(module), "three-core": _data_url(core),
                                        "orbit": _data_url(orbit)}})
    old_map = '<script type="importmap">{ "imports": { "three": "./vendor/three.module.min.js" } }</script>'
    old_module = '<script type="module" src="./lite.js"></script>'
    assert old_map in page and old_module in page and "</script>" not in lite
    scene = base64.b64encode(gzip.compress(json.dumps(msg).encode(), compresslevel=6)).decode()
    page = page.replace(old_map, f'<script type="importmap">{importmap}</script>')
    page = page.replace(old_module, f'<script>window.CADVIEW_INLINE_SCENE = "{scene}";</script>\n'
                                    f'<script type="module">\n{lite}\n</script>')
    page = page.replace("<!--__CADVIEW_BASE__-->", "")
    if title:
        page = page.replace("<title>cadview lite</title>", f"<title>{html.escape(str(title))}</title>", 1)
    return page


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir", nargs="?", default="site")
    ap.add_argument("scenes", nargs="*", help="scene names (default: every scene on the server)")
    ap.add_argument("--single-file", action="store_true")
    ap.add_argument("--changed-vs", metavar="BUNDLE", help="cadview-scenes.tar.gz to diff against")
    ap.add_argument("--url", default=os.environ.get("CADVIEW_URL", "http://127.0.0.1:3941"))
    args = ap.parse_args(argv)
    url = args.url.rstrip("/")
    out = Path(args.outdir)

    rows = [r for r in json.loads(get(url, "/api/runnable"))["projects"] if r.get("built", True)]
    if args.scenes:
        rows = [r for r in rows if r["project"] in set(args.scenes)]
    if not rows:
        sys.exit("no scenes to bake")
    msgs = {r["project"]: scene_message(url, r["project"]) for r in rows}
    titles = {r["project"]: r.get("title") or r.get("name") or r["project"] for r in rows}

    changed = sorted(msgs)
    unchanged = []
    scenes = {}
    if args.changed_vs:
        before = bundle_scenes(args.changed_vs)
        for p in sorted(msgs):
            if p not in before:
                scenes[p] = {"changed": [], "added": sorted(part_signatures(msgs[p])), "removed": [], "animation": False, "new_scene": True}
                continue
            scenes[p] = scene_diff(before[p], msgs[p])
        changed = sorted(p for p, d in scenes.items()
                         if d["changed"] or d["added"] or d["removed"] or d["animation"])
        unchanged = sorted(p for p in msgs if p not in changed)
        for p in changed:
            d = scenes[p]
            bits = [f"{len(d[k])} {k}" for k in ("changed", "added", "removed") if d[k]]
            names = ", ".join(q.rsplit("/", 1)[-1] for q in (d["changed"] + d["added"] + d["removed"])[:6])
            print(f"{p}: {', '.join(bits) or 'animation'}{' — ' + names if names else ''}"
                  + (" (animation changed)" if d["animation"] and bits else "") + (" (new scene)" if d.get("new_scene") else ""))
        print(f"changed: {', '.join(changed) or '-'}")
        print(f"unchanged: {', '.join(unchanged) or '-'}")

    if args.single_file:
        out.mkdir(parents=True, exist_ok=True)
        for p in changed:
            page = single_file_html(msgs[p], titles[p])
            (out / f"{p}.html").write_text(page)
            print(f"{out / f'{p}.html'}  {len(page) / 1e6:.1f} MB")
    else:
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        shutil.copy(LITE / "lite.js", out / "lite.js")
        shutil.copytree(LITE / "vendor", out / "vendor")
        shutil.copy(LITE / "gallery.html", out / "index.html")
        (out / "scenes").mkdir()
        (out / "thumbs").mkdir()
        viewer = (LITE / "index.html").read_text().replace("<!--__CADVIEW_BASE__-->", '<base href="../">')
        baked = []
        for r in rows:
            p = r["project"]
            if p not in changed:
                continue
            (out / "scenes" / f"{p}.json").write_text(json.dumps(msgs[p]))
            (out / p).mkdir()
            (out / p / "index.html").write_text(viewer)
            try:
                (out / "thumbs" / f"{p}.png").write_bytes(get(url, f"/thumbs/{p}.png"))
            except urllib.error.HTTPError:
                pass
            baked.append({k: r.get(k) for k in ("project", "title", "name", "received_at", "group")})
        (out / "scenes.json").write_text(json.dumps({"projects": baked}))
        size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
        print(f"static site in {out}/ — {len(baked)} scene(s), {size:.1f} MB")
    (out / "changed.json").write_text(json.dumps({"changed": changed, "unchanged": unchanged, "scenes": scenes}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
