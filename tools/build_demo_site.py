"""Build a fully static site from a running cadview server: the gallery at
the root plus one viewer page per scene — serves from any static host
(GitHub Pages, a bucket, `python -m http.server`).

    python tools/build_demo_site.py [outdir] [scene ...]

Default: every scene on the server (CADVIEW_URL, default
http://127.0.0.1:3941). Layout:

    index.html            gallery (reads scenes.json)
    scenes.json           the scene list the gallery shows
    scenes/<p>.json       baked scene data
    thumbs/<p>.png        thumbnails the server has
    <p>/index.html        the viewer for scene <p> (base href ../)
    lite.js, vendor/      the viewer core

Push-side meta (source paths, owners) is stripped: bake only what a
viewer needs. Only put scenes here that may be public.
"""
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = os.environ.get("CADVIEW_URL", "http://127.0.0.1:3941").rstrip("/")
KEEP_META = ("name", "title", "project", "units", "revision", "pushed_at", "received_at")

args = sys.argv[1:]
out = Path(args[0] if args else "site")
only = set(args[1:])
lite = Path(__file__).resolve().parents[1] / "cadview/static/lite"


def get(path):
    with urllib.request.urlopen(URL + path, timeout=120) as r:
        return r.read()


rows = [r for r in json.loads(get("/api/runnable"))["projects"]
        if not only or r["project"] in only]
if not rows:
    sys.exit("no scenes to bake")

if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)
shutil.copy(lite / "lite.js", out / "lite.js")
shutil.copytree(lite / "vendor", out / "vendor")
shutil.copy(lite / "gallery.html", out / "index.html")
(out / "scenes").mkdir()
(out / "thumbs").mkdir()

viewer = (lite / "index.html").read_text().replace(
    "<!--__CADVIEW_BASE__-->", '<base href="../">')
baked = []
for r in rows:
    p = r["project"]
    msg = json.loads(get(f"/api/scene?name={p}"))
    msg["meta"] = {k: v for k, v in msg.get("meta", {}).items() if k in KEEP_META}
    (out / "scenes" / f"{p}.json").write_text(json.dumps(msg))
    (out / p).mkdir()
    (out / p / "index.html").write_text(viewer)
    try:
        (out / "thumbs" / f"{p}.png").write_bytes(get(f"/thumbs/{p}.png"))
    except urllib.error.HTTPError:
        pass
    baked.append({k: r.get(k) for k in ("project", "title", "name", "received_at", "group")})

(out / "scenes.json").write_text(json.dumps({"projects": baked}))
size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
print(f"static site in {out}/ — {len(baked)} scene(s), {size:.1f} MB")
