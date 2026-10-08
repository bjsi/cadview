"""Marks — parts that say what they are and which way they go.

    from openworkshop.marks import engrave, arrow, top_face

    bracket = engrave(bracket, "P1")                       # its kit ID, cut 0.4 mm into the top face
    bracket = arrow(bracket, (0, 1, 0), text="WALL")       # a triangle (and a word) pointing +Y

A build guide assigns every part type a short ID by route (P1 for the first
printed part, C1 cut on the CNC, X1 cut to length, B1 bought — see
openworkshop.guide); engraving that ID on the part, and an arrow where the
orientation is not obvious, is what lets someone who has never seen the
model pick the right part out of the bag and put it in the right way round.
The marks are geometry, so they print / machine with the part and show in
the viewer. `engrave(..., raised=True)` embosses instead of cutting.
"""
from __future__ import annotations

import math

from build123d import Align, Axis, Plane, Polygon, Pos, Rot, Text, Vector, extrude


def top_face(shape, normal=(0, 0, 1)):
    """The largest face whose normal points along `normal` and that sits furthest that way
    (the top of a part lying flat: where a printed part's label goes)."""
    n = Vector(*normal).normalized()
    faces = [f for f in shape.faces() if (f.normal_at() - n).length < 1e-3]
    if not faces:
        raise ValueError("no flat face facing that way")
    top = max(f.center().dot(n) for f in faces)
    return max((f for f in faces if abs(f.center().dot(n) - top) < 1e-3), key=lambda f: f.area)


def _plane(shape, face, normal):
    """The face's plane: origin at its centre, z along its normal, x the default for that normal
    (so `at` and `rotation` mean the same thing for every mark on the face)."""
    f = face or top_face(shape, normal)
    return Plane(origin=f.center(), z_dir=f.normal_at())


def _angle(plane, direction):
    """Degrees from the plane's x axis to `direction` projected into the plane."""
    d = plane.to_local_coords(Vector(*direction)) - plane.to_local_coords(Vector(0, 0, 0))
    return math.degrees(math.atan2(d.Y, d.X))


def _apply(shape, plane, solid, raised):
    out = shape + plane * solid if raised else shape - plane * solid
    out.label, out.color = shape.label, shape.color
    return out


def font_file():
    """A bold sans TTF for the marks: OPENWORKSHOP_FONT, else what fontconfig gives for 'sans:bold'
    (build123d's default is Arial, which a Linux box rarely has — OCC then draws boxes), else None."""
    import os
    import shutil
    import subprocess
    p = os.environ.get("OPENWORKSHOP_FONT")
    if p:
        return p
    if shutil.which("fc-match"):
        try:
            out = subprocess.run(["fc-match", "-f", "%{file}", "sans:bold"], capture_output=True, text=True, timeout=10).stdout.strip()
            if out.lower().endswith((".ttf", ".otf")):
                return out
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def engrave(shape, text, *, face=None, normal=(0, 0, 1), depth=0.4, size=6.0, at=(0, 0), rotation=0.0, raised=False):
    """Cut (or raise) `text` into a face: the part's top face by default, else `face`.
    `at` offsets the text in the face's plane (mm), `rotation` turns it (degrees)."""
    plane = _plane(shape, face, normal)
    font = font_file()
    glyphs = extrude(Text(str(text), font_size=size, align=(Align.CENTER, Align.CENTER), **({"font_path": font} if font else {})), amount=depth)
    glyphs = Pos(at[0], at[1], 0 if raised else -depth) * Rot(0, 0, rotation) * glyphs
    return _apply(shape, plane, glyphs, raised)


def arrow(shape, direction, *, face=None, normal=(0, 0, 1), depth=0.4, size=6.0, at=(0, 0), text=None, raised=False):
    """A triangle pointing along `direction` (a vector in the face's plane) cut into the face,
    with an optional word under it ("UP", "WALL", "FRONT") reading along the arrow."""
    plane = _plane(shape, face, normal)
    ang = _angle(plane, direction)
    tri = extrude(Polygon((-size / 2, -size / 2), (size / 2, 0), (-size / 2, size / 2), align=None), amount=depth)
    tri = Pos(at[0], at[1], 0 if raised else -depth) * Rot(0, 0, ang) * tri
    out = _apply(shape, plane, tri, raised)
    if text:
        # the word sits "below" the arrow in the arrow's own frame: -y there, rotated back into the face
        off = Vector(0, -size, 0).rotate(Axis.Z, ang)
        out = engrave(out, text, face=face, normal=normal, depth=depth, size=size * 0.7,
                      at=(at[0] + off.X, at[1] + off.Y), rotation=ang, raised=raised)
    return out


__all__ = ["engrave", "arrow", "top_face"]
