"""Build a fully static demo site from the lite viewer + one baked scene.

    python tools/build_demo_site.py [scene] [outdir]

Copies static/lite/* next to a scene.json fetched from the running server
(default scene "demo"). The result serves from any static host — GitHub
Pages, a bucket, `python -m http.server`.
"""
import json
import shutil
import sys
import urllib.request
from pathlib import Path

scene = sys.argv[1] if len(sys.argv) > 1 else "demo"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "site")
lite = Path(__file__).resolve().parents[1] / "cadview/static/lite"

if out.exists():
    shutil.rmtree(out)
shutil.copytree(lite, out)
with urllib.request.urlopen(f"http://127.0.0.1:3941/api/scene?name={scene}", timeout=60) as r:
    msg = json.load(r)
# bake only presentation meta — push-side stamps (source paths, owners)
# are deployment details and may leak local paths
msg["meta"] = {k: v for k, v in msg.get("meta", {}).items()
               if k in ("name", "title", "project", "units", "revision", "pushed_at", "received_at")}
(out / "scene.json").write_text(json.dumps(msg))
print(f"static site in {out}/ ({scene}, "
      f"{sum(f.stat().st_size for f in out.rglob('*') if f.is_file()) / 1e6:.1f} MB)")
