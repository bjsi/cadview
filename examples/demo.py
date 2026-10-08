"""openworkshop demo: a cabinet with a sliding drawer.

    python -m openworkshop.server          # in another terminal (or your agent's)
    python examples/demo.py           # pushes scene "demo" -> open /demo

Shows the basics: a labelled/coloured part tree, a part grouped at its
joint (the drawer node slides as one piece), animation tracks and named
clips (dropdown in the player). Try the ⚠ toggle (collision check) and
⏺ (record the playing clip to video).
"""

import os

from build123d import Align, Box, Color, Compound, Cylinder, Pos, Rot

os.environ.setdefault("OPENWORKSHOP_SCENE", "demo")

UP = (Align.CENTER, Align.CENTER, Align.MIN)


def part(shape, label, color):
    shape.label, shape.color = label, Color(*color)
    return shape


def build():
    # cabinet: a shell with the +X face open
    body = Box(120, 160, 100, align=UP) - Pos(7, 0, 7) * Box(122, 146, 88, align=UP)
    cabinet = part(body, "cabinet", (0.5, 0.38, 0.28))
    top = part(Pos(0, 0, 100) * Box(132, 172, 8, align=UP), "worktop", (0.62, 0.5, 0.38))

    # drawer: geometry built around the node origin so one track slides it all
    tray = Box(104, 138, 60, align=UP) - Pos(0, 0, 8) * Box(92, 126, 60, align=UP)
    front = Pos(57, 0, -3) * Box(8, 158, 86, align=UP)
    knob = Pos(63, 0, 40) * Rot(0, 90, 0) * Cylinder(9, 10)
    drawer = Compound(children=[part(tray, "tray", (0.72, 0.58, 0.42)),
                                part(front, "front", (0.62, 0.48, 0.34)),
                                part(knob, "knob", (0.2, 0.2, 0.22))],
                      label="drawer (slides)")
    drawer.locate(Pos(3, 0, 12))

    return Compound(children=[cabinet, top, drawer], label="drawer demo")


# tracks: (selector, action, times, values) — the selector matches the part
# label, tx slides in mm along X relative to where the drawer sits
CYCLE = [("drawer (slides)", "tx", [0, 0.6, 2.0, 3.4, 4.6, 5.2], [0, 0, 85, 85, 0, 0])]
PEEK = [("drawer (slides)", "tx", [0, 0.4, 1.1, 1.8, 2.3], [0, 0, 28, 0, 0])]

if __name__ == "__main__":
    from openworkshop import show
    show(build(),
         title="Sliding drawer (demo)",
         animation=[{"name": "open & close", "tracks": CYCLE},
                    {"name": "peek", "tracks": PEEK}])
