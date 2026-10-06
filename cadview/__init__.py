"""cadview — persistent build123d viewer for the Tailscale mesh.

Usage in a build123d script (drop-in for ocp_vscode):

    from cadview import show
    show(scene)
"""

from cadview.client import (
    Camera,
    Collapse,
    get_url,
    set_defaults,
    set_host,
    set_port,
    show,
)

__version__ = "0.1.0"
__all__ = [
    "show", "set_port", "set_host", "set_defaults", "get_url",
    "Camera", "Collapse", "__version__",
]
from .anim import Timeline  # noqa: F401  (phase-style track builder)
