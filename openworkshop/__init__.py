"""openworkshop — a persistent build123d viewer, animation, boards, and an
agent's eyes on all of it (the project was called cadview until 0.3.0;
`import cadview` still works, and CADVIEW_* environment variables are read
as OPENWORKSHOP_*).

Usage in a build123d script (drop-in for ocp_vscode):

    from openworkshop import show
    show(scene)
"""
import os as _os

for _k, _v in list(_os.environ.items()):           # CADVIEW_X -> OPENWORKSHOP_X unless set
    if _k.startswith("CADVIEW_") and "OPENWORKSHOP_" + _k[8:] not in _os.environ:
        _os.environ["OPENWORKSHOP_" + _k[8:]] = _v

from openworkshop.client import (
    Camera,
    Collapse,
    get_url,
    set_defaults,
    set_host,
    set_port,
    show,
)

__version__ = "0.3.0"
__all__ = [
    "show", "set_port", "set_host", "set_defaults", "get_url",
    "Camera", "Collapse", "__version__",
]
from .anim import Timeline  # noqa: F401  (phase-style track builder)
