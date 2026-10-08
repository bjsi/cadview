"""Hardware — fasteners and extrusion fittings as real build123d parts.

A build guide counts the parts a step adds by label, so a screw that is a
part with the label "M6×12 socket screw" puts "8 × M6×12 socket screw" on
the step's list by itself — no notes to keep in sync with the model. Every
function returns a labelled, coloured Part (or a Compound of them) sized
from the ISO tables below; the shapes are deliberately simple (a socket
screw is a shank, a head and a hex recess) so a few hundred of them cost
nothing to tessellate.

    from openworkshop.hardware import screw, t_nut, corner_bracket, fasten

    bracket = Pos(x, y, z) * corner_bracket("3030")
    screws  = fasten(screw("M6", 12), t_nut("M6", "3030"), at=(x, y, z + 14), axis=(0, -1, 0))

Orientation: a screw's origin is the underside of its head and it points
down -Z (the way it goes into the material), so `Pos(p) * screw(...)` sits
on a surface at p with the material below; `fasten(..., axis=)` turns it
to point along any axis and puts the nut / T-nut where the shank ends.
Labels carry the spec, never the position; the guide and the BOM group
by label.
"""
from __future__ import annotations

import math

from build123d import Align, Box, Compound, Cone, Cylinder, Plane, Pos, RegularPolygon, Rot, Vector, extrude

# ISO 4762 socket head (d_k, k), ISO 4032 hex nut (s, m), ISO 7089 washer (d2, t), hex key (s_key)
_SCREW = {"M3": (5.5, 3.0, 2.5), "M4": (7.0, 4.0, 3.0), "M5": (8.5, 5.0, 4.0), "M6": (10.0, 6.0, 5.0),
          "M8": (13.0, 8.0, 6.0), "M10": (16.0, 10.0, 8.0)}
_NUT = {"M3": (5.5, 2.4), "M4": (7.0, 3.2), "M5": (8.0, 4.7), "M6": (10.0, 5.2), "M8": (13.0, 6.8), "M10": (16.0, 8.4)}
_WASHER = {"M3": (7.0, 0.5), "M4": (9.0, 0.8), "M5": (10.0, 1.0), "M6": (12.0, 1.6), "M8": (16.0, 1.6), "M10": (20.0, 2.0)}
# T-slot extrusion families: slot width, profile, drop-in T-nut body (length, width, height)
_SLOT = {"2020": (6.0, 20.0, (10.0, 5.8, 4.0)), "3030": (8.0, 30.0, (19.0, 7.8, 5.5)), "4040": (8.0, 40.0, (19.0, 7.8, 5.5))}

STEEL = (0.62, 0.64, 0.66)
ZINC = (0.72, 0.74, 0.76)
BRASS = (0.80, 0.66, 0.30)
ALU = (0.75, 0.77, 0.80)


def _d(size):
    return float(size.upper().lstrip("M"))


def _part(shape, label, color):
    shape.label, shape.color = label, color
    return shape


def screw(size="M6", length=12, head="socket"):
    """M<d>×<length>: 'socket' (cap head with hex recess), 'button' (low dome), 'countersunk' (flat top, cone under).
    Origin at the underside of the head, shank down -Z."""
    size = size.upper()
    d = _d(size)
    dk, k, key = _SCREW[size]
    shank = Cylinder(d / 2, length, align=(Align.CENTER, Align.CENTER, Align.MAX))
    if head == "socket":
        cap = Cylinder(dk / 2, k, align=(Align.CENTER, Align.CENTER, Align.MIN))
        recess = Pos(0, 0, k) * extrude(RegularPolygon(key / math.sqrt(3), 6), amount=-k * 0.6)
        body = shank + cap - recess
    elif head == "button":
        cap = Cylinder(dk / 2, k * 0.55, align=(Align.CENTER, Align.CENTER, Align.MIN))
        dome = Pos(0, 0, k * 0.55) * Cone(dk / 2, dk / 4, k * 0.25, align=(Align.CENTER, Align.CENTER, Align.MIN))
        recess = Pos(0, 0, k * 0.8) * extrude(RegularPolygon(key / math.sqrt(3), 6), amount=-k * 0.5)
        body = shank + cap + dome - recess
    elif head == "countersunk":
        cone = Cone(d / 2, dk / 2, k * 0.6, align=(Align.CENTER, Align.CENTER, Align.MIN))
        recess = Pos(0, 0, k * 0.6) * extrude(RegularPolygon(key / math.sqrt(3), 6), amount=-k * 0.4)
        body = shank + cone - recess
    else:
        raise ValueError(f"head {head!r}: socket, button or countersunk")
    return _part(body, f"{size}×{int(length)} {head} screw", STEEL)


def nut(size="M6"):
    """Hex nut, origin at its underside, standing up +Z."""
    size = size.upper()
    s, m = _NUT[size]
    body = extrude(RegularPolygon(s / math.sqrt(3), 6), amount=m) - Cylinder(_d(size) / 2, m, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return _part(body, f"{size} hex nut", ZINC)


def washer(size="M6"):
    size = size.upper()
    d2, t = _WASHER[size]
    body = Cylinder(d2 / 2, t, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(_d(size) / 2 + 0.2, t, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return _part(body, f"{size} washer", ZINC)


def t_nut(size="M6", slot="3030"):
    """Drop-in T-nut for a T-slot extrusion family ('2020' 6 mm slot, '3030' / '4040' 8 mm slot).
    Origin at the top face centre (flush with the slot opening), body below."""
    size = size.upper()
    L, w, h = _SLOT[slot][2]
    body = Box(L, w, h, align=(Align.CENTER, Align.CENTER, Align.MAX)) - Cylinder(_d(size) / 2, h, align=(Align.CENTER, Align.CENTER, Align.MAX))
    return _part(body, f"{size} T-nut ({slot})", ZINC)


def heat_set_insert(size="M3", length=None):
    """Brass heat-set insert, origin at its top face, body down -Z."""
    size = size.upper()
    d = _d(size)
    length = length or round(d * 1.9, 1)
    body = Cylinder(d * 0.85, length, align=(Align.CENTER, Align.CENTER, Align.MAX)) - Cylinder(d / 2, length, align=(Align.CENTER, Align.CENTER, Align.MAX))
    return _part(body, f"{size} heat-set insert", BRASS)


def corner_bracket(profile="3030", thickness=3.0):
    """Cast L-bracket for the extrusion family: leg length = profile, width = profile - 2, a slot each leg.
    Origin at the inside corner; legs along +X and +Z, width along Y."""
    p = _SLOT[profile][1]
    w = p - 2
    legx = Box(p, w, thickness, align=(Align.MIN, Align.CENTER, Align.MIN))
    legz = Box(thickness, w, p, align=(Align.MIN, Align.CENTER, Align.MIN))
    hole = _SLOT[profile][0] / 2 - 0.5
    body = (legx + legz
            - Pos(p * 0.6, 0, 0) * Cylinder(hole, thickness * 3)
            - Pos(0, 0, p * 0.6) * Rot(0, 90, 0) * Cylinder(hole, thickness * 3))
    return _part(body, f"{profile} corner bracket", ALU)


def fasten(screw_part, mate=None, *, at=(0, 0, 0), axis=(0, 0, -1), grip=0.0):
    """A screw (and its nut / T-nut / insert) placed at `at`, the screw pointing along `axis`.
    `grip` = the material between the head and the mate: the mate's origin goes that far along
    the axis. Returns a Compound labelled by the screw, so both show on the step's list."""
    ax = Vector(*axis).normalized()
    base = Plane(origin=Vector(*at), z_dir=-ax).location      # local -Z (the shank) -> axis
    parts = [base * screw_part]
    if mate is not None:
        parts.append(base * Pos(0, 0, -grip) * mate)
    return Compound(children=parts, label=screw_part.label)


def bom(*parts):
    """{label: count} over every leaf of the given compounds — what to buy."""
    out = {}

    def walk(c):
        kids = getattr(c, "children", None) or []
        if kids:
            for k in kids:
                walk(k)
        else:
            out[c.label or "part"] = out.get(c.label or "part", 0) + 1

    for p in parts:
        walk(p)
    return out


# what this library's parts are by default: bought (a corner bracket can also be
# printed, so it says both). A show(routes=...) entry for the same label wins.
from openworkshop.guide import HARDWARE_ROUTES as DEFAULT_ROUTES  # noqa: E402

__all__ = ["screw", "nut", "washer", "t_nut", "heat_set_insert", "corner_bracket", "fasten", "bom", "DEFAULT_ROUTES"]
