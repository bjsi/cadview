"""A few generic parts, each pushed as its own scene — populates the gallery
(http://127.0.0.1:3941/) so you can see the multi-design overview.

    python -m cadview.server      # in another terminal
    python examples/parts.py      # pushes 4 scenes; open / to browse them
"""

import os

from build123d import Align, Box, Cylinder, Pos, Rot

UP = (Align.CENTER, Align.CENTER, Align.MIN)


def part(shape, label, color):
    shape.label, shape.color = label, color
    return shape


def l_bracket():
    from build123d import Color
    body = (Box(60, 40, 6, align=(Align.MIN, Align.CENTER, Align.MIN))
            + Box(6, 40, 50, align=(Align.MIN, Align.CENTER, Align.MIN)))
    for x, y in ((18, -12), (18, 12), (42, -12), (42, 12)):
        body -= Pos(x, y, 0) * Cylinder(2.6, 20, align=UP)
    return part(body, "L-bracket", Color(0.55, 0.58, 0.62))


def flange():
    from build123d import Color
    disc = Cylinder(34, 8, align=UP)
    pipe = Pos(0, 0, 8) * (Cylinder(16, 40, align=UP) - Cylinder(12, 40, align=UP))
    body = disc - Cylinder(12, 8, align=UP) + pipe
    for i in range(6):
        body -= Rot(0, 0, i * 60) * Pos(26, 0, 0) * Cylinder(3, 10, align=UP)
    return part(body, "pipe flange", Color(0.72, 0.6, 0.4))


def knob():
    from build123d import Color
    body = Cylinder(20, 16, align=UP)
    for i in range(24):
        body -= Rot(0, 0, i * 15) * Pos(20, 0, 8) * Box(1.6, 3, 16)
    body = Pos(0, 0, 16) * Cylinder(14, 6, align=UP) + body
    body -= Pos(0, 0, 0) * Cylinder(3, 12, align=UP)
    return part(body, "knurled knob", Color(0.3, 0.32, 0.36))


def enclosure():
    from build123d import Color
    outer = Box(90, 60, 30, align=UP)
    body = outer - Pos(0, 0, 3) * Box(82, 52, 30, align=UP)
    lid = Pos(0, 0, 30) * Box(90, 60, 3, align=UP)
    for x in range(-2, 3):
        lid -= Pos(x * 14, 0, 30) * Box(4, 36, 6, align=UP)
    body += lid
    return part(body, "vented enclosure", Color(0.4, 0.55, 0.7))


SCENES = {
    "bracket": ("L-bracket", l_bracket),
    "flange": ("Pipe flange", flange),
    "knob": ("Knurled knob", knob),
    "enclosure": ("Vented enclosure", enclosure),
}

if __name__ == "__main__":
    from cadview import show
    for scene, (title, build) in SCENES.items():
        os.environ["CADVIEW_SCENE"] = scene
        show(build(), title=title)
