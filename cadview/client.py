"""Push side of cadview: tessellate CAD objects and POST them to the server.

Runs inside the build123d script process (which already has OCP loaded), so the
server itself never needs CAD dependencies. Uses ocp-tessellate — the same
engine ocp_vscode uses — so nested Compound labels, colors and alphas survive
unchanged into the viewer's part tree.
"""

import gzip
import json
import os
import re
import subprocess
import sys
from pathlib import Path
import time
import urllib.error
import urllib.request
from enum import Enum

# the invoked script, before any runpy.run_path rewrites sys.argv[0]
_ARGV0 = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""


class Camera(Enum):
    """Camera reset modes (mirrors ocp_vscode.Camera for drop-in compat)."""

    RESET = "reset"
    CENTER = "center"
    KEEP = "keep"
    ISO = "iso"
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    BACK = "rear"
    FRONT = "front"


class Collapse(Enum):
    """Tree collapse modes (mirrors ocp_vscode.Collapse for drop-in compat)."""

    NONE = 2
    LEAVES = -1
    ALL = 0
    ROOT = 1

_config = {
    "host": None,   # push target; falls back to CADVIEW_HOST, then 127.0.0.1
    "port": None,   # falls back to CADVIEW_PORT, then 3941
    "defaults": {},  # extra show() kwargs applied to every call
}

# show() kwargs forwarded to the frontend (everything else that isn't a
# tessellation param is accepted and dropped for ocp_vscode compatibility)
_VIEWER_CONFIG_KEYS = {
    "reset_camera", "collapse", "explode", "grid", "axes", "axes0", "ortho",
    "transparent", "black_edges", "default_opacity", "default_edgecolor",
    "up", "control", "glass", "tools", "theme", "debug",
    "ambient_intensity", "direct_intensity", "metalness", "roughness",
}

_TESS_KEYS = {"deviation", "angular_tolerance"}


def set_port(port):
    """ocp_vscode-compatible: set the port pushed to by show()."""
    _config["port"] = int(port)


def set_host(host):
    """Set the host pushed to by show() (default 127.0.0.1)."""
    _config["host"] = host


def set_defaults(**kwargs):
    """ocp_vscode-compatible: kwargs merged into every show() call."""
    _config["defaults"].update(kwargs)


def get_url():
    host = _config["host"] or os.environ.get("CADVIEW_HOST", "127.0.0.1")
    port = _config["port"] or int(os.environ.get("CADVIEW_PORT", "3941"))
    return f"http://{host}:{port}"


def show(*cad_objs, names=None, colors=None, alphas=None, **kwargs):
    """Tessellate and push objects to the cadview server.

    Drop-in for ``from ocp_vscode import show``: build123d/CadQuery objects
    (nested Compounds with .label/.color honored), optional names/colors/alphas
    lists. Unknown ocp_vscode kwargs are accepted and ignored.
    """
    from ocp_tessellate.convert import tessellate_group, to_ocpgroup
    from ocp_tessellate.utils import numpy_to_buffer_json

    if not cad_objs:
        raise ValueError("show() called with no objects")

    kwargs = {**_config["defaults"], **kwargs}
    if isinstance(names, str):
        names = [names]

    t0 = time.perf_counter()
    group, instances = to_ocpgroup(
        *cad_objs,
        names=names,
        colors=colors,
        alphas=alphas,
        default_color=kwargs.get("default_color"),
        progress=None,
    )
    quality = kwargs.get("quality", "standard")
    if quality not in ("standard", "preview"):
        raise ValueError("quality must be 'standard' or 'preview'")
    tess_params = {"deviation": 0.4 if quality == "preview" else 0.1,
                   "angular_tolerance": 0.4 if quality == "preview" else 0.2, "render_edges": True}
    for key in _TESS_KEYS:
        if kwargs.get(key) is not None:
            tess_params[key] = kwargs[key]
    instances_out, shapes, mapping = tessellate_group(group, instances, tess_params, None)
    t_tess = time.perf_counter()
    data = numpy_to_buffer_json({"instances": instances_out, "shapes": shapes})

    config = {k: v for k, v in kwargs.items() if k in _VIEWER_CONFIG_KEYS and v is not None}
    config = {k: v.value if isinstance(v, Enum) else v for k, v in config.items()}
    name = shapes.get("name") or "scene"
    message = {
        "type": "data",
        "data": data,
        "config": config,
        "meta": {
            "name": name,
            "units": kwargs.get("units", "mm"),
            "pushed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
    }
    if kwargs.get("title"):
        # org-facing display name (the picker/hud show it instead of the
        # engineering scene name); server-side titles.json can also set it
        message["meta"]["title"] = str(kwargs["title"])[:120]
    # stamp the pushing script so the viewer can offer re-run/watch — the
    # server only ever executes it if it lands in its runnable registry
    # (auto-registered only for pushes originating on the hub itself).
    # _ARGV0 is captured at import time: runpy.run_path swaps sys.argv[0] to
    # the inner script, and re-run must target the OUTER tool that was invoked.
    src = os.environ.get("CADVIEW_SOURCE") or _ARGV0
    if src.endswith(".py") and os.path.exists(src):
        message["meta"]["source_file"] = os.path.abspath(src)

    animation = kwargs.get("animation")
    if animation:
        # tracks: (selector, action, times, values) — actions t/tx/ty/tz (mm,
        # relative to the node's base), rx/ry/rz (degrees), q (quaternion).
        # Selector = a node id from the tree, or a trailing path segment.
        # A design can carry SEVERAL named animations: pass a dict
        # {name: tracks} (or a list of {"name", "tracks", "speed"?}); a plain
        # track list stays one unnamed clip. The viewer shows a clip picker.
        # vis: visibility 0/1 (sampled > 0.5 = shown) — cue LEDs, appearing
        # pellets and other indicator states
        actions = {"t", "tx", "ty", "tz", "rx", "ry", "rz", "q", "vis"}

        def norm_tracks(raw):
            tracks = []
            for track in raw:
                selector, action, times, values = track
                if action not in actions:
                    raise ValueError(f"unknown animation action {action!r}")
                if len(times) != len(values) or len(times) < 2:
                    raise ValueError("animation track needs matching times/values, ≥2 keys")
                tracks.append([str(selector), action, list(times), list(values)])
            return tracks

        speed = float(kwargs.get("animation_speed", 1.0))
        if isinstance(animation, dict):
            clips = [{"name": str(n), "tracks": norm_tracks(t), "speed": speed}
                     for n, t in animation.items()]
        elif animation and isinstance(animation[0], dict):
            clips = [{"name": str(c.get("name") or f"clip {i + 1}"),
                      "tracks": norm_tracks(c["tracks"]),
                      "speed": float(c.get("speed", speed))}
                     for i, c in enumerate(animation)]
        else:
            clips = [{"name": "animation", "tracks": norm_tracks(animation),
                      "speed": speed}]
        message["animations"] = clips

    body = gzip.compress(json.dumps(message).encode(), compresslevel=3)
    t_encoded = time.perf_counter()
    url = get_url()
    # one scene per project: CADVIEW_SCENE, else the pushing script's cwd basename
    project = os.environ.get("CADVIEW_SCENE") or Path.cwd().name or "default"
    req = urllib.request.Request(
        url + "/api/scene?name=" + urllib.parse.quote(project),
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ConnectionError(
            f"cadview server not reachable at {url} ({exc}). "
            "Start it with: python -m cadview.server"
        ) from None

    print(
        f"cadview: pushed '{name}' to {url}/{project} "
        f"({len(body) / 1e6:.1f} MB gzipped, {time.perf_counter() - t0:.1f}s; "
        f"tessellate {t_tess - t0:.2f}s, encode/compress {t_encoded - t_tess:.2f}s, "
        f"send/store {time.perf_counter() - t_encoded:.2f}s)"
    )
