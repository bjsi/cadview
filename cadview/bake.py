"""Bake viewer pages from a running cadview server — review pages for a PR,
a demo site, an offline hand-off. No CAD stack needed, just the server.

    python -m cadview.bake --single-file [--changed-vs BUNDLE] [outdir] [scene ...]
    python -m cadview.bake [outdir] [scene ...]

--single-file   one self-contained <scene>.html per scene: the viewer,
                three.js and the gzipped scene inlined. Opens from file://
                or an email attachment, full orbit / part tree / hide /
                measure / animation, nothing fetched. ~1 MB + the scene.
--changed-vs    keep only scenes whose geometry or animation differs from
                the scenes in BUNDLE (a cadview-scenes.tar.gz as published
                by a repo's scenes workflow) — "what this PR changed".
                outdir/changed.json lists changed + unchanged either way.
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


def geometry_key(msg):
    """What a reviewer cares about: geometry + animation, not push times."""
    body = {"data": msg.get("data"), "animations": msg.get("animations"), "config": msg.get("config")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def bundle_keys(path):
    """project -> geometry_key for every scene in a cadview-scenes.tar.gz."""
    out = {}
    with tarfile.open(path, "r:gz") as tar:
        for m in tar.getmembers():
            name = Path(m.name).name
            if m.isfile() and name.startswith("scene-") and name.endswith(".json.gz"):
                msg = json.loads(gzip.decompress(tar.extractfile(m).read()))
                out[name[len("scene-"):-len(".json.gz")]] = geometry_key(msg)
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
    if args.changed_vs:
        before = bundle_keys(args.changed_vs)
        changed = sorted(p for p in msgs if before.get(p) != geometry_key(msgs[p]))
        unchanged = sorted(p for p in msgs if p not in changed)
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
    (out / "changed.json").write_text(json.dumps({"changed": changed, "unchanged": unchanged}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
