"""DSL-side helpers: build123d faces from KiCad Edge.Cuts, the boards the tests lay out, and a re-expression of a
parsed open-source board through the DSL.  Everything that touches the module under test takes it as `m`."""
from __future__ import annotations

import math
import os

from build123d import (Edge, Face, Plane, Vector, Wire, Circle, Pos, Rectangle, RectangleRounded)

import kicad_parse as kp


# --------------------------------------------------------------------------------------- faces from KiCad ----
def face_from_edge_cuts(items: list) -> Face:
    """KiCad Edge.Cuts items (y DOWN) -> a build123d Face in the y-UP frame the DSL works in.  The biggest closed
    loop is the outline, the others are holes / cutouts."""
    F = lambda p: Vector(p[0], -p[1], 0)
    edges = []
    for it in items:
        if it.kind == "line":
            a, b = it.pts
            edges.append(Edge.make_line(F(a), F(b)))
        elif it.kind == "arc":
            a, mid, b = it.pts
            edges.append(Edge.make_three_point_arc(F(a), F(mid), F(b)))
        elif it.kind == "circle":
            c, e = it.pts
            r = math.hypot(e[0] - c[0], e[1] - c[1])
            edges.append(Edge.make_circle(r, Plane(origin=(c[0], -c[1], 0))))
        elif it.kind == "rect":
            (x0, y0), (x1, y1) = it.pts
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            for p, q in zip(pts, pts[1:] + pts[:1]):
                edges.append(Edge.make_line(F(p), F(q)))
    wires = Wire.combine(edges)
    closed = [w for w in wires if w.is_closed]
    assert closed, "no closed loop on Edge.Cuts"
    area = lambda w: Face(w).area
    outer = max(closed, key=area)
    inner = [w for w in closed if w is not outer]
    return Face(outer, inner) if inner else Face(outer)


def face_rect(w: float, h: float, cx=0.0, cy=0.0) -> Face:
    return (Pos(cx, cy) * Rectangle(w, h)).faces()[0]


# ------------------------------------------------------------------------------------- the round-trip board ----
ROUNDTRIP = dict(w=60.0, h=40.0, r=4.0, thickness=1.6, holes=[((-25.0, -15.0), 3.2), ((25.0, 15.0), 3.2)],
                 cutout=dict(at=(20.0, -12.0), w=8.0, h=3.0))


def roundtrip_face() -> Face:
    s = ROUNDTRIP
    sk = RectangleRounded(s["w"], s["h"], s["r"])
    for (x, y), d in s["holes"]:
        sk -= Pos(x, y) * Circle(d / 2)
    c = s["cutout"]
    sk -= Pos(*c["at"]) * Rectangle(c["w"], c["h"])
    return sk.faces()[0]


def build_roundtrip_board(m):
    """rectangle + 4 corner arcs, 2 NPTH, a rectangular cutout, 3 parts, 2 nets, one hand trace, one pour"""
    b = m.Board(roundtrip_face(), thickness=ROUNDTRIP["thickness"], name="roundtrip", z=0.0)
    soic = m.kicad_footprint("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm")
    r = m.kicad_footprint("Resistor_SMD", "R_0603_1608Metric")
    j = m.kicad_footprint("Connector_JST", "JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical")
    u1 = b.place(soic, "U1", (0.0, 0.0), rot=0, value="IC", symbol=("Timer", "NE555D"))
    b.place(r, "R1", (-10.0, 10.0), rot=90, value="10k", lcsc="C25804", symbol=("Device", "R"))
    j1 = b.place(j, "J1", (-20.0, 0.0), rot=90, value="XH2", lcsc="C158012", symbol=("Connector_Generic", "Conn_01x02"))
    b.net("GND", ("J1", 1), ("U1", 4), ("R1", 2))
    b.net("SIG", ("J1", 2), ("U1", 1))
    b.trace("SIG", [j1.pad_xy(j.pad(2)), u1.pad_xy(soic.pad(1))], "top")
    b.pour("GND", "F.Cu")
    return b


# --------------------------------------------------------------------------------------- re-expression ----
def reexpress(m, rec: kp.BoardRec, name: str, footprint_dir: str | None = None):
    """An open-source board parsed by kicad_parse -> the same board through the DSL: outline from Edge.Cuts, the same
    library footprints (by Lib:Name) at the same origins and rotations, the same net on every pad; no copper
    routing, no zones.  `footprint_dir` overrides the library the footprints are read from."""
    face = face_from_edge_cuts(rec.edge)
    b = m.Board(face, thickness=1.6, name=name, z=0.0)
    saved = m.KICAD_FP
    if footprint_dir:
        m.KICAD_FP = footprint_dir
    try:
        cache = {}
        for fp in rec.footprints:
            assert fp.layer == "F.Cu", f"{fp.ref}: the DSL writes top-side footprints only ({fp.layer})"
            lib, _, fname = fp.name.partition(":")
            if fp.name not in cache:
                cache[fp.name] = m.kicad_footprint(lib, fname)
            b.place(cache[fp.name], fp.ref, (fp.x, -fp.y), rot=fp.rot, value=fp.value, center_pads=False)
    finally:
        m.KICAD_FP = saved
    nets: dict = {}
    for fp in rec.footprints:
        for p in fp.pads:
            if p.net:
                nets.setdefault(p.net, set()).add((fp.ref, p.number))
    for net, pins in nets.items():
        b.net(net, *sorted(pins))
    return b


def write_pcb(b, path: str, traces=None) -> str:
    with open(path, "w") as f:
        f.write(b.kicad_pcb(traces))
    return path


def write_pro(b, path: str, name: str) -> str:
    with open(path, "w") as f:
        f.write(b.kicad_pro(name))
    return path


def expected_pad_geom(p: kp.PadRec) -> tuple:
    """the copper of a library pad as KiCad draws it, computed independently: (centre x, centre y UP, w, h) of its
    bounding box in the footprint frame.  A custom pad covers its anchor plus its primitives; `(drill (offset dx dy))`
    moves the copper off the pad position; both are given in the pad's own frame and turn with the pad's angle
    (KiCad rotates CCW on its y-down screen); the size swaps for pads at 90 / 270."""
    w, h, x, y = p.w, p.h, p.x, p.y
    sx, sy = p.offset
    if p.prim_bbox:
        xs = [-w / 2, w / 2, p.prim_bbox[0], p.prim_bbox[2]]
        ys = [-h / 2, h / 2, p.prim_bbox[1], p.prim_bbox[3]]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        sx += (max(xs) + min(xs)) / 2
        sy += (max(ys) + min(ys)) / 2
    a = math.radians(p.rot)
    x += sx * math.cos(a) + sy * math.sin(a)
    y += -sx * math.sin(a) + sy * math.cos(a)
    if p.rot % 180 == 90:
        w, h = h, w
    return (x, -y, w, h)


def pad_is_plain(p: kp.PadRec) -> bool:
    """pads whose copper is just the anchor shape at the pad position: no `(drill (offset))`, not a custom pad
    rotated inside its footprint, and on a copper layer.  Everything else is covered by the known-deviation test."""
    return p.copper and p.offset == (0.0, 0.0) and not (p.prim_bbox and p.rot % 360 != 0)


def expected_drill(p: kp.PadRec) -> float:
    if not p.drill:
        return 0.0
    return max(v for v in p.drill if isinstance(v, float))


def expected_layers(p: kp.PadRec) -> tuple:
    """copper sides of a pad; a paste- or mask-only pad has none"""
    if p.kind != "smd":
        return ("top", "bottom")
    s = {"top" if l.startswith("F.") else "bottom" for l in p.layers if l.endswith(".Cu") or l.startswith("*")}
    return tuple(sorted(s))


def lib_path(m, lib: str, name: str) -> str:
    return os.path.join(m.KICAD_FP, f"{lib}.pretty", f"{name}.kicad_mod")
