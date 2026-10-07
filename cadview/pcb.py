"""cadview.pcb — a PCB laid out from build123d, written out for KiCad, tscircuit and JLCPCB.

The board outline, holes and cutouts are read off a build123d Face (a plate's underside, a box floor, ...); footprints
come from KiCad's own libraries on disk (parsed here, no KiCad binary needed); parts are placed in the CAD's frame; nets
are named by (ref, pad).  Out: `write_kicad()` (.kicad_pcb / .kicad_pro / netlist — text an agent can edit and kicad-cli
can check and export: tools/pcb/kicad_export.sh), `circuit_json()` for tscircuit's router and exporters
(tools/pcb/export.mjs), `write_jlc()` (JLCPCB BOM + CPL), and `solid()` — the same board as build123d geometry with the
footprints' STEP models on it, so it sits in the assembly without a round trip.

    from cadview.pcb import Board, kicad_footprint
    b = Board(face, thickness=1.6, z=3.0)
    b.place(kicad_footprint("Connector_JST", "JST_XH_B5B-XH-A_1x05_P2.50mm_Vertical"), "J1", (40, 20), rot=90)
    b.net("GND", ("J1", 2), ("U1", 3))
    b.write_kicad("out", "board");  b.write("out/board.circuit.json");  b.write_jlc("out")
    show(assembly + b.solid())

Units mm, Z up; Circuit JSON is y-up too, KiCad footprints are y-down and are flipped on read.  Implemented: smd and
through-hole pads (rect / roundrect / oval / circle), any rotation for the KiCad outputs (the library tree is re-embedded
and KiCad draws it; the DSL's own `Pad.w / h` - Circuit JSON, `solid()` - only swap at 90 / 270), circle holes, polygon cutouts,
outline edges as KiCad's own items (lines, arcs, circles, cubic beziers - `gr_curve`; cubic splines split into their spans
exactly, every other curve - ellipses, rational / higher-degree splines - approximated by cubic beziers within CURVE_TOL =
1 um), rect keepouts, copper pours, hand traces + vias, silkscreen text, 2 / 4 / 6 copper
layers (`Board(layers=4)`: In1.Cu .. in the layer table and stackup, pours and traces on `layer="In1.Cu"`, through vias), parts
on either side; `kicad_sch()` writes a schematic (global labels per net) and `check_netlist()` proves it against the board.
Needs build123d; shapely for outlines (`pip install cadview[pcb]`); KiCad's footprint + 3D libraries on disk
(KICAD_FOOTPRINTS / KICAD_3DMODELS).

Outline, holes, cutouts.  The Face's outer wire is the board edge (Edge.Cuts: `gr_line` / `gr_arc` per CAD edge).  An inner
wire is a cutout on Edge.Cuts too (`gr_circle` for a full circle, lines / arcs otherwise) - except that a full circle is,
by default, a non-plated drill instead (`Board(..., inner_circles="npth")`: a `cadview:NPTH_<d>mm` footprint H1.. in the
drill file, as a CAD mounting hole should be made; `inner_circles="cutout"` keeps it on Edge.Cuts as a routed opening).
`Board.hole(at, d)` adds an NPTH explicitly.

Sides.  `place(..., layer="bottom")` puts a part on the back the way KiCad flips one (top/bottom flip, FOOTPRINT::Flip):
`(layer "B.Cu")`, pad y mirrored in the footprint frame, pad and text angles negated, every F.* layer its B.* twin, the
footprint at `(at x -y rot)` - so `rot` is the angle KiCad shows and `kicad-cli pcb export pos` reports for the part; the JLC
CPL gets 180 - rot, the angle as seen from the bottom, which is what JLC reads for a bottom part (`write_jlc`).
`Placed.pad_xy()` mirrors the same way, so Circuit JSON, the CPL and `solid()` (the STEP model turned under the board) agree
with the Gerbers.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field

try:
    from build123d import *  # noqa: F401,F403
except ImportError:          # the parser / writers still work without CAD
    pass

KICAD_FP = os.environ.get("KICAD_FOOTPRINTS", "/usr/share/kicad/footprints")   # KiCad 10 (Arch package kicad-library 10.0.x)
KICAD_3D = os.environ.get("KICAD_3DMODELS", "/usr/share/kicad/3dmodels")
KICAD_SYM = os.environ.get("KICAD_SYMBOLS", "/usr/share/kicad/symbols")
_MODEL_VAR = re.compile(r"\$\{KICAD\d*_3DMODEL_DIR\}")


# ------------------------------------------------------------------ KiCad footprint reader ----
class Q(str):
    """a quoted string token (vs a bare symbol), so a parsed tree serialises back the way KiCad wrote it"""


_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")   # the only number KiCad writes: plain decimals, no exponent - so a hex
                                                     # timestamp like KiCad 5/6's `(tedit 527E5841)` stays a symbol (float() would make it inf)


def _sexp(text: str):
    """Minimal s-expression parser: nested lists of Q (quoted) / str (symbol) / float."""
    toks = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()]+', text)
    stack, cur = [], []
    for t in toks:
        if t == "(":
            stack.append(cur); cur = []
        elif t == ")":
            done = cur; cur = stack.pop(); cur.append(done)
        elif t.startswith('"'):
            cur.append(Q(t[1:-1].replace('\\"', '"')))
        elif _NUMBER.fullmatch(t):
            cur.append(float(t))
        else:
            cur.append(t)
    return cur[0]


def _num(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.6f}".rstrip("0").rstrip(".")


def _ser(n, depth=0) -> str:
    """serialise a parsed tree; one node per line like KiCad does (agents diff / edit it by line)"""
    if isinstance(n, list):
        head, rest = n[0], n[1:]
        inline = all(not isinstance(x, list) for x in rest)
        if inline: return "(" + " ".join(_ser(x) for x in n) + ")"
        pad = "  " * (depth + 1)
        return "(" + _ser(head) + "".join(("\n" + pad + _ser(x, depth + 1)) if isinstance(x, list) else " " + _ser(x) for x in rest) + ")"
    if isinstance(n, Q): return '"' + n.replace('"', '\\"') + '"'
    if isinstance(n, float): return _num(n)
    return str(n)


def _kv(node, key, default=None):
    for n in node:
        if isinstance(n, list) and n and n[0] == key: return n
    return default


_FLIP_LAYER = {f"{a}.{s}": f"{b}.{s}" for a, b in (("F", "B"), ("B", "F")) for s in ("Cu", "Paste", "Mask", "SilkS", "Fab", "CrtYd", "Adhes")}
_FLIP_CORNER = {"top_left": "bottom_left", "bottom_left": "top_left", "top_right": "bottom_right", "bottom_right": "top_right"}


def _flip_tree(n):
    """Mirror a footprint tree in place the way KiCad stores a footprint flipped to the back (FOOTPRINT::Flip, top/bottom):
    every y negated (pad and text positions, drill offsets, fp_* graphics, custom-pad primitives, zone polygons), every
    angle negated, F.* <-> B.* layers, chamfered corners top <-> bottom, text mirrored.  Angles are still footprint-relative
    here; the caller adds the part's rotation afterwards.  KiCad renders a pad at fp_pos + R(fp_angle) * local with no
    mirroring of its own, so this stored mirror is what puts a back-side pad where a part turned over sits."""
    if not isinstance(n, list) or not n: return
    for c in n[1:]: _flip_tree(c)
    head = n[0]
    if head in ("at", "start", "end", "mid", "center", "xy", "offset", "rect_delta") and len(n) > 2 and isinstance(n[2], float):
        n[2] = -n[2] + 0.0
        if head == "at" and len(n) > 3 and isinstance(n[3], float): n[3] = (-n[3]) % 360
    elif head == "layer" and len(n) > 1: n[1] = Q(_FLIP_LAYER.get(n[1], n[1]))
    elif head == "layers": n[1:] = [Q(_FLIP_LAYER.get(l, l)) for l in n[1:]]
    elif head == "chamfer": n[1:] = [_FLIP_CORNER.get(c, c) for c in n[1:]]
    elif head == "effects":
        j = _kv(n, "justify")
        if j is None: n.append(["justify", "mirror"])
        elif "mirror" in j[1:]:
            j.remove("mirror")
            if len(j) == 1: n.remove(j)
        else: j.append("mirror")


@dataclass
class Pad:
    number: str
    kind: str                      # "smd" | "thru_hole" | "np_thru_hole"
    shape: str                     # KiCad shape name
    x: float; y: float             # footprint frame, y UP
    w: float; h: float
    drill: float = 0.0             # 0 for smd
    layers: tuple = ("top",)


@dataclass
class Footprint:
    name: str
    pads: list
    model: str | None              # absolute STEP path or None
    lib: str = ""
    tree: list = field(default_factory=list)   # the parsed .kicad_mod, re-embedded verbatim into a .kicad_pcb

    def pad(self, number) -> Pad:
        for p in self.pads:
            if p.number == str(number): return p
        raise KeyError(f"{self.name}: no pad {number!r}")


def kicad_footprint(lib: str, name: str) -> Footprint:
    """Read `<KICAD_FP>/<lib>.pretty/<name>.kicad_mod`: pads (y flipped to y-up) and the STEP model path."""
    path = os.path.join(KICAD_FP, f"{lib}.pretty", f"{name}.kicad_mod")
    with open(path) as f: tree = _sexp(f.read())
    pads = []
    for n in tree:
        if not (isinstance(n, list) and n and n[0] == "pad"): continue
        number, kind, shape = str(n[1]).rstrip("0").rstrip(".") if isinstance(n[1], float) else n[1], n[2], n[3]
        at = _kv(n, "at"); rot = at[3] if len(at) > 3 else 0.0
        size = _kv(n, "size"); w, h = size[1], size[2]
        # the copper's centre can sit off the pad position: `(drill (offset dx dy))` and custom-pad primitives
        # both shift it in the PAD's own frame, which turns with the pad's angle (as KiCad draws it)
        sx = sy = 0.0
        d = _kv(n, "drill")
        off = _kv(d, "offset") if d else None
        if off: sx, sy = off[1], off[2]
        prim = _kv(n, "primitives")                                                 # custom pads (castellations, solder jumpers): cover the primitives too
        if prim:
            xs, ys = [-w / 2, w / 2], [-h / 2, h / 2]
            for g in prim[1:]:
                if not isinstance(g, list): continue
                if g[0] == "gr_poly":
                    for pt in _kv(g, "pts")[1:]: xs.append(pt[1]); ys.append(pt[2])
                elif g[0] == "gr_circle":
                    c, e = _kv(g, "center"), _kv(g, "end"); r = math.hypot(e[1] - c[1], e[2] - c[2])
                    xs += [c[1] - r, c[1] + r]; ys += [c[2] - r, c[2] + r]
                elif g[0] in ("gr_rect", "gr_line"):
                    s, e = _kv(g, "start"), _kv(g, "end"); xs += [s[1], e[1]]; ys += [s[2], e[2]]
            w, h = max(xs) - min(xs), max(ys) - min(ys); sx += (max(xs) + min(xs)) / 2; sy += (max(ys) + min(ys)) / 2
        a = math.radians(rot)                                                       # KiCad frame (y down), then flipped to y up
        x = at[1] + sx * math.cos(a) + sy * math.sin(a)
        y = -(at[2] - sx * math.sin(a) + sy * math.cos(a))
        if rot % 180 == 90: w, h = h, w
        drill = 0.0
        if d: drill = max([v for v in d[1:] if isinstance(v, float)] or [0.0])     # (drill 0.95), (drill oval 1.0 1.8), (drill (offset ..))
        lay = _kv(n, "layers") or []
        layers = tuple(sorted({"top" if l.startswith("F.") else "bottom" for l in lay[1:] if l.endswith(".Cu") or l.startswith("*")}))
        if kind != "smd": layers = ("top", "bottom")
        # no copper layer at all (paste-only pads): keep it for the library tree, but it is not a copper pad
        pads.append(Pad(number, kind, shape, x, y, w, h, drill, layers))
    m = _kv(tree, "model")
    model = _MODEL_VAR.sub(KICAD_3D, m[1]) if m else None
    if m: m[1] = Q(model)                                                          # absolute path: kicad-cli has no ${KICAD10_3DMODEL_DIR} headless
    return Footprint(name, pads, model, lib, tree)


# ------------------------------------------------------------------ KiCad symbol reader ----
_SYM_LIBS: dict = {}


@dataclass
class Symbol:
    lib: str
    name: str
    tree: list                    # the (symbol "lib:name" ...) tree, flattened (no `extends`), ready for lib_symbols
    pins: list                    # (number, x, y, angle, type) in symbol frame (y up), all units


def _sym_lib(lib):
    if lib not in _SYM_LIBS:
        with open(os.path.join(KICAD_SYM, f"{lib}.kicad_sym")) as f: tree = _sexp(f.read())
        _SYM_LIBS[lib] = {n[1]: n for n in tree if isinstance(n, list) and n and n[0] == "symbol"}
    return _SYM_LIBS[lib]


def kicad_symbol(lib: str, name: str) -> Symbol:
    """Read `<KICAD_SYMBOLS>/<lib>.kicad_sym` symbol `name`; a derived symbol (`extends`) is flattened onto its parent."""
    import copy
    lib_syms = _sym_lib(lib)
    node = lib_syms[name]
    ext = _kv(node, "extends")
    if ext:
        parent = copy.deepcopy(lib_syms[ext[1]])
        props = {n[1]: n for n in node if isinstance(n, list) and n[0] == "property"}
        out = [parent[0], Q(name)]
        for n in parent[2:]:
            if isinstance(n, list) and n[0] == "property" and n[1] in props: n = props.pop(n[1])
            if isinstance(n, list) and n[0] == "symbol": n[1] = Q(n[1].replace(ext[1] + "_", name + "_", 1))
            out.append(n)
        out += list(props.values())
        node = out
    else:
        node = copy.deepcopy(node)
    pins = []
    for unit in (n for n in node if isinstance(n, list) and n[0] == "symbol"):
        for p in (n for n in unit if isinstance(n, list) and n[0] == "pin"):
            at = _kv(p, "at"); num = _kv(p, "number")
            pins.append((str(num[1]), at[1], at[2], at[3] if len(at) > 3 else 0.0, p[1]))
    node[1] = Q(f"{lib}:{name}")
    return Symbol(lib, name, node, pins)


# ---------------------------------------------------------------------- geometry from CAD ----
def _poly_from_wire(wire: Wire, step=0.25, tol=0.01):
    """Sample a closed wire every `step` mm and simplify (Douglas-Peucker, `tol`): arcs become chords, corners stay exact."""
    from shapely.geometry import LineString
    n = max(16, int(wire.length / step))
    step = wire.length / n
    pts = [(p.X, p.Y) for p in wire.positions([i * step for i in range(n)], position_mode=PositionMode.LENGTH)]   # LENGTH = absolute mm (build123d 0.10)
    s = LineString(pts + [pts[0]]).simplify(tol, preserve_topology=False)
    out = list(s.coords)[:-1]
    return [(round(x, 4), round(y, 4)) for x, y in out]


def _circle_of(wire: Wire):
    """(cx, cy, d) if the wire is one full circle, else None."""
    es = wire.edges()
    if len(es) == 1 and es[0].geom_type == GeomType.CIRCLE and es[0].is_closed:
        c = es[0].arc_center; return (round(c.X, 4), round(c.Y, 4), round(2 * es[0].radius, 4))
    return None


CURVE_TOL = 0.001   # mm: how far a cubic-bezier approximation of an outline curve KiCad cannot hold exactly may stray from the CAD edge


def _cubic_beziers(e: Edge):
    """A curve edge as cubic beziers: a list of 4-pole [(x, y) ...] runs in the curve's own direction (the way it was drawn -
    KiCad's polyline of a bezier depends on it, so a round trip keeps it), each one a KiCad `gr_curve`.  The edge's parameter
    range goes through OCC's curve -> BSpline -> per-span bezier conversion, exact for a non-rational curve of degree <= 3 (a
    cubic bezier comes back as itself, a quadratic / line is degree-elevated).  Anything else - an ellipse, a rational or
    higher-degree spline - is first approximated by a non-rational cubic BSpline within CURVE_TOL (GeomConvert_ApproxCurve),
    then split the same way; None only when that approximation fails, which the caller samples into lines instead."""
    from OCP.Geom import Geom_TrimmedCurve
    from OCP.GeomAbs import GeomAbs_C1
    from OCP.GeomConvert import GeomConvert, GeomConvert_ApproxCurve, GeomConvert_BSplineCurveToBezierCurve
    ad = e.geom_adaptor()
    crv = Geom_TrimmedCurve(ad.Curve().Curve(), ad.FirstParameter(), ad.LastParameter())
    bs = GeomConvert.CurveToBSplineCurve_s(crv)
    if bs.IsRational() or bs.Degree() > 3:
        ap = GeomConvert_ApproxCurve(crv, CURVE_TOL, GeomAbs_C1, 500, 3)
        if not (ap.IsDone() and ap.HasResult()): return None
        bs = ap.Curve()
        if bs.IsRational() or bs.Degree() > 3: return None
    cv = GeomConvert_BSplineCurveToBezierCurve(bs)
    out = []
    for k in range(1, cv.NbArcs() + 1):
        c = cv.Arc(k)
        P = [(c.Pole(i).X(), c.Pole(i).Y()) for i in range(1, c.NbPoles() + 1)]
        while len(P) < 4:                                                          # degree elevation: Q_i = (i P_{i-1} + (n+1-i) P_i) / (n+1)
            n = len(P) - 1
            P = [P[0]] + [((i * P[i - 1][0] + (n + 1 - i) * P[i][0]) / (n + 1), (i * P[i - 1][1] + (n + 1 - i) * P[i][1]) / (n + 1)) for i in range(1, n + 1)] + [P[-1]]
        out.append(P)
    return out


def _cu(layer: str) -> str:
    """a copper layer as KiCad names it: 'top' / 'bottom' -> F.Cu / B.Cu, 'in1' -> In1.Cu, a KiCad name ('In2.Cu') as given"""
    if layer in ("top", "bottom"): return {"top": "F.Cu", "bottom": "B.Cu"}[layer]
    return layer if layer.endswith(".Cu") else layer.capitalize() + ".Cu"


def _cj_layer(layer: str) -> str:
    """the same layer as Circuit JSON names it: top / bottom / inner1 / inner2 ..."""
    k = _cu(layer)
    return {"F.Cu": "top", "B.Cu": "bottom"}.get(k, "inner" + k[2:-3])


# ------------------------------------------------------------------------------- the board ----
@dataclass
class Placed:
    ref: str
    fp: Footprint
    x: float; y: float; rot: float
    value: str = ""
    mpn: str = ""
    layer: str = "top"
    lcsc: str = ""                 # LCSC C-number (JLCPCB assembly); "" = not assembled (sourced separately)
    note: str = ""                 # BOM note: stock / basic-extended / "assumed"
    ref_at: tuple | None = None    # where the Reference silkscreen goes (footprint frame, y up); None = the library's place
    symbol: tuple | None = None    # ("Lib", "Name") in KiCad's symbol libraries, for the schematic

    def pad_xy(self, pad: Pad):
        """panel position of a pad: the part's origin + the pad's footprint-frame position turned by `rot`; a bottom-side part is
        turned over about its x axis first (pad y mirrored), the same flip KiCad stores"""
        a = math.radians(self.rot); c, s = math.cos(a), math.sin(a)
        py = -pad.y if self.layer == "bottom" else pad.y
        return (round(self.x + pad.x * c - py * s, 4), round(self.y + pad.x * s + py * c, 4))

    def pad_layers(self, pad: Pad) -> tuple:
        """the copper sides of a pad on this part: a bottom-side part's F.* pads are on the bottom"""
        if self.layer != "bottom": return pad.layers
        return tuple(sorted({"top": "bottom", "bottom": "top"}[l] for l in pad.layers))


class Board:
    """A PCB whose outline / holes / cutouts come from a build123d Face lying in a Z plane.  `layers`: copper layers, 2 / 4 / 6
    (F.Cu, In1.Cu .., B.Cu - `self.copper` in stack order); pours and hand traces take any of them by name."""

    def __init__(self, face: Face, thickness=1.6, name="board", z=0.0, inner_circles="npth", layers=2):
        """`inner_circles`: what a full-circle inner wire of the Face is - "npth" (default): a non-plated drill (`Board.holes`,
        a `cadview:NPTH_<d>mm` footprint in the drill file - a CAD mounting hole); "cutout": a `gr_circle` on Edge.Cuts like
        any other inner wire (a routed opening).  Every other inner wire is an Edge.Cuts cutout.  `layers`: 2 / 4 / 6 copper."""
        if inner_circles not in ("npth", "cutout"): raise ValueError(f"inner_circles: 'npth' or 'cutout', not {inner_circles!r}")
        self.name, self.thickness, self.z = name, thickness, z
        if int(layers) not in (2, 4, 6): raise ValueError(f"layers={layers!r}: 2, 4 or 6 copper layers")
        self.layers = int(layers)
        self.copper = ["F.Cu"] + [f"In{i}.Cu" for i in range(1, self.layers - 1)] + ["B.Cu"]
        self.outline = _poly_from_wire(face.outer_wire())
        self.holes, self.cutouts, self.circle_cutouts = [], [], []           # (x, y, d) NPTH; polygons; (x, y, d) of the circular cutouts
        self.edge_wires = [face.outer_wire()]                                   # exact edges for KiCad's Edge.Cuts
        for w in face.inner_wires():
            c = _circle_of(w)
            if c and inner_circles == "npth": self.holes.append(c)
            else:
                self.cutouts.append(_poly_from_wire(w)); self.edge_wires.append(w)
                if c: self.circle_cutouts.append(c)
        xs, ys = [p[0] for p in self.outline], [p[1] for p in self.outline]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))
        self.parts: list[Placed] = []
        self.nets: dict[str, list] = {}
        self.keepouts = []
        self.labels, self.pours, self.manual, self.vias, self.extra = [], [], [], [], []
        self.rules = dict(min_clearance=0.2, min_track_width=0.2, min_via_diameter=0.5, min_through_hole_diameter=0.3,
                          min_copper_edge_clearance=0.3, min_hole_to_hole=0.25, min_hole_clearance=0.25)   # JLCPCB 2-layer, with margin
        self.track_width, self.via_dims = 0.3, (0.6, 0.3)

    # --- authoring
    def place(self, fp: Footprint, ref: str, at, rot=0.0, value="", mpn="", center_pads=True, lcsc="", note="", ref_at=None, symbol=None, layer="top") -> Placed:
        """`at` is where the part's pad-bbox centre goes (KiCad footprints often have their origin on pin 1, e.g. the Pico THT one);
        center_pads=False puts the footprint origin there instead.  layer="bottom": the part on the back, turned over about its
        x axis (KiCad's flip); `rot` is then the angle KiCad shows for it, CCW as seen from the top."""
        if layer not in ("top", "bottom"): raise ValueError(f"layer: 'top' or 'bottom', not {layer!r}")
        ox = oy = 0.0
        if center_pads and fp.pads:
            xs, ys = [q.x for q in fp.pads], [q.y for q in fp.pads]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            if layer == "bottom": cy = -cy
            a = math.radians(rot); ox, oy = -(cx * math.cos(a) - cy * math.sin(a)), -(cx * math.sin(a) + cy * math.cos(a))
        p = Placed(ref, fp, round(at[0] + ox, 4), round(at[1] + oy, 4), rot % 360, value, mpn, layer, lcsc=lcsc, note=note, ref_at=ref_at, symbol=symbol); self.parts.append(p); return p

    def hole(self, at, d):
        """an explicit non-plated hole (NPTH drill, `cadview:NPTH_<d>mm` footprint) at a panel position - the same thing a
        circular inner wire of the Face gives with inner_circles="npth\""""
        self.holes.append((round(at[0], 4), round(at[1], 4), round(d, 4))); return self.holes[-1]

    def label(self, text, at, rot=0.0, size=1.0, layer="F.SilkS"):
        """silkscreen text (KiCad only; Circuit JSON gets a pcb_silkscreen_text)"""
        self.labels.append((text, (round(at[0], 4), round(at[1], 4)), rot % 360, size, layer))

    def pour(self, net="GND", layer="B.Cu"):
        """a copper pour over the whole outline on one layer ('top' / 'bottom' / 'F.Cu' / 'In1.Cu' ...; KiCad zone, filled by
        `kicad-cli pcb drc --refill-zones --save-board`)"""
        self.pours.append((net, self._layer(layer)))

    def trace(self, net, pts, layer="top", width=None):
        """hand-placed copper: a polyline on one layer (Circuit JSON pcb_trace, so the router sees it as an obstacle; KiCad segments)"""
        self.manual.append(dict(net=net, layer=self._layer(layer), width=width or self.track_width, pts=[(round(x, 4), round(y, 4)) for x, y in pts]))

    def _layer(self, layer: str) -> str:
        """a copper layer name the board has, as given (top / bottom / F.Cu / B.Cu / In1.Cu / in1)"""
        if _cu(layer) not in self.copper: raise ValueError(f"layer {layer!r}: this board's copper layers are {', '.join(self.copper)}")
        return layer

    def via(self, net, at):
        self.vias.append((net, (round(at[0], 4), round(at[1], 4))))

    def stitch(self, net, ref, pad_number, toward, length=1.3):
        """a short trace from an SMD pad out to a via (e.g. a top-layer GND pad down to the bottom pour); `toward` = (dx, dy) unit-ish"""
        p = next(p for p in self.parts if p.ref == ref); q = p.fp.pad(pad_number)
        x, y = p.pad_xy(q); n = math.hypot(*toward); dx, dy = toward[0] / n * length, toward[1] / n * length
        self.trace(net, [(x, y), (x + dx, y + dy)], p.pad_layers(q)[0]); self.via(net, (x + dx, y + dy))

    def hole_keepout(self, d_head):
        """keep copper off a d_head square around every mounting hole (the screw head / standoff face), both layers"""
        for x, y, d in self.holes: self.keepout((x, y), d_head, d_head, why=f"screw head at hole ({x}, {y})")

    def bom_only(self, ref, value, footprint, mpn, lcsc, at, rot=0.0, note="", assemble=True):
        """a part with no footprint of its own: on another footprint's pads (assemble=True: JLC BOM + CPL rows) or off-board
        (assemble=False: harness leads etc., bom_full.csv only)"""
        self.extra.append(dict(ref=ref, value=value, fp=footprint, mpn=mpn, lcsc=lcsc, at=(round(at[0], 3), round(at[1], 3)), rot=rot % 360, note=note, assemble=assemble))

    # --- JLCPCB assembly set: bom.csv + cpl.csv in their column layout
    def write_jlc(self, outdir):
        rows = [dict(ref=p.ref, value=p.value, fp=p.fp.name, lcsc=p.lcsc, mpn=p.mpn, note=p.note, rot=p.rot, layer=p.layer,
                     at=((min(x) + max(x)) / 2, (min(y) + max(y)) / 2)) for p in self.parts if p.lcsc
                for x, y in [([p.pad_xy(q)[0] for q in p.fp.pads], [p.pad_xy(q)[1] for q in p.fp.pads])]]
        rows += [dict(e, layer="top") for e in self.extra if e["lcsc"] and e["assemble"]]
        bom = ["Comment,Designator,Footprint,LCSC Part #"]
        groups = {}
        for r in rows: groups.setdefault((r["value"], r["fp"], r["lcsc"]), []).append(r["ref"])
        for (val, fp, lcsc), refs in groups.items(): bom.append(f'"{val}","{",".join(refs)}","{fp}","{lcsc}"')
        # Rotation: JLC reads a bottom part's angle as seen from the bottom (the board turned over left-right), which is 180 - the
        # angle KiCad stores / `kicad-cli pcb export pos` writes; the two KiCad->JLC tools (Fabrication Toolkit, the one JLC's own
        # KiCad guide recommends, and kicad-jlcpcb-tools) both write (180 - rot) % 360 for B.Cu parts.  Top parts: as KiCad has them.
        cpl = ["Designator,Mid X,Mid Y,Layer,Rotation"]
        for r in rows:
            rot = r["rot"] if r["layer"] == "top" else (180.0 - r["rot"]) % 360
            cpl.append(f'"{r["ref"]}",{r["at"][0]:.3f}mm,{r["at"][1]:.3f}mm,{"Top" if r["layer"] == "top" else "Bottom"},{rot:g}')
        full = ["ref,value,footprint,mpn,lcsc,note"] + [f'"{p.ref}","{p.value}","{p.fp.lib}:{p.fp.name}","{p.mpn}","{p.lcsc}","{p.note}"' for p in self.parts] + \
               [f'"{e["ref"]}","{e["value"]}","{e["fp"]}","{e["mpn"]}","{e["lcsc"]}","{e["note"]}"' for e in self.extra]
        out = {}
        for name, lines in (("bom.csv", bom), ("cpl.csv", cpl), ("bom_full.csv", full)):
            out[name] = os.path.join(outdir, name)
            with open(out[name], "w") as f: f.write("\n".join(lines) + "\n")
        return out

    def net(self, name: str, *pins):
        """pins: (ref, pad_number) tuples"""
        self.nets.setdefault(name, []).extend((r, str(n)) for r, n in pins)

    def keepout(self, center, w, h, layers=("top", "bottom"), why="", pour=False):
        """no tracks / vias here; pour=True lets a copper pour through (e.g. keep routed tracks off a THT row so its thermal spokes survive)"""
        self.keepouts.append((center, w, h, tuple(layers), why, pour))

    # --- Circuit JSON
    def circuit_json(self) -> list:
        cx, cy = (self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2
        els = [dict(type="pcb_board", pcb_board_id="pcb_board_0", center=dict(x=cx, y=cy), thickness=self.thickness,
                    num_layers=self.layers, material="fr4", shape="polygon", outline=[dict(x=x, y=y) for x, y in self.outline],
                    width=self.bbox[2] - self.bbox[0], height=self.bbox[3] - self.bbox[1])]
        for i, (x, y, d) in enumerate(self.holes):
            els.append(dict(type="pcb_hole", pcb_hole_id=f"pcb_hole_{i}", hole_shape="circle", hole_diameter=d, x=x, y=y))
        for i, poly in enumerate(self.cutouts):
            els.append(dict(type="pcb_cutout", pcb_cutout_id=f"pcb_cutout_{i}", shape="polygon", points=[dict(x=x, y=y) for x, y in poly]))
        for i, (c, w, h, layers, why, pour) in enumerate(self.keepouts):
            els.append(dict(type="pcb_keepout", pcb_keepout_id=f"pcb_keepout_{i}", shape="rect", center=dict(x=c[0], y=c[1]),
                            width=w, height=h, layers=list(layers), description=why))
        port_id = {}                                                     # (ref, pad) -> source_port_id
        for pi, p in enumerate(self.parts):
            sc, pc = f"source_component_{pi}", f"pcb_component_{pi}"
            xs = [p.pad_xy(q)[0] for q in p.fp.pads]; ys = [p.pad_xy(q)[1] for q in p.fp.pads]
            comp = dict(type="source_component", source_component_id=sc, name=p.ref, ftype="simple_chip", display_value=p.value)
            if p.mpn: comp["manufacturer_part_number"] = p.mpn
            els.append(comp)
            els.append(dict(type="pcb_component", pcb_component_id=pc, source_component_id=sc, center=dict(x=p.x, y=p.y), layer=p.layer,
                            rotation=p.rot, width=round(max(xs) - min(xs) + 2, 3), height=round(max(ys) - min(ys) + 2, 3)))
            els.append(dict(type="cad_component", cad_component_id=f"cad_component_{pi}", pcb_component_id=pc, source_component_id=sc,
                            position=dict(x=p.x, y=p.y, z=(-1 if p.layer == "bottom" else 1) * self.thickness / 2), rotation=dict(x=0, y=0, z=p.rot), layer=p.layer,
                            **({"model_step_url": "file://" + p.fp.model} if p.fp.model else {})))
            for qi, q in enumerate(p.fp.pads):
                layers = p.pad_layers(q)
                if not layers: continue                                         # paste-only pad: no copper, no port
                x, y = p.pad_xy(q)
                if q.number:
                    sp, pp = f"source_port_{pi}_{qi}", f"pcb_port_{pi}_{qi}"
                    port_id[(p.ref, q.number)] = sp
                    els.append(dict(type="source_port", source_port_id=sp, source_component_id=sc, name=q.number, port_hints=[q.number],
                                    **({"pin_number": int(q.number)} if q.number.isdigit() else {})))
                    els.append(dict(type="pcb_port", pcb_port_id=pp, source_port_id=sp, pcb_component_id=pc, x=x, y=y, layers=list(layers)))
                else:
                    pp = None
                base = dict(pcb_component_id=pc, x=x, y=y, **({"pcb_port_id": pp, "port_hints": [q.number]} if pp else {}))
                if q.kind == "smd":
                    shape = "circle" if q.shape == "circle" else "rect"
                    el = dict(type="pcb_smtpad", pcb_smtpad_id=f"pcb_smtpad_{pi}_{qi}", shape=shape, layer=layers[0], **base)
                    w, h = (q.h, q.w) if p.rot % 180 == 90 else (q.w, q.h)            # the part's rotation turns the pad too
                    el.update(dict(radius=q.w / 2) if shape == "circle" else dict(width=w, height=h))
                elif q.kind == "np_thru_hole":
                    el = dict(type="pcb_hole", pcb_hole_id=f"pcb_hole_{p.ref}_{qi}", hole_shape="circle", hole_diameter=q.drill, x=x, y=y)
                else:
                    el = dict(type="pcb_plated_hole", pcb_plated_hole_id=f"pcb_plated_hole_{pi}_{qi}", shape="circle", layers=["top", "bottom"],
                              hole_diameter=q.drill, outer_diameter=max(q.w, q.h), **base)
                els.append(el)
        for ni, (name, pins) in enumerate(self.nets.items()):
            ids = [port_id[k] for k in pins]
            els.append(dict(type="source_net", source_net_id=f"source_net_{ni}", name=name, member_source_group_ids=[],
                            is_ground=name == "GND", is_power=name.startswith("3V3") or name.startswith("+5V")))
            els.append(dict(type="source_trace", source_trace_id=f"source_trace_{ni}", connected_source_port_ids=ids,
                            connected_source_net_ids=[f"source_net_{ni}"], display_name=name))
        for i, (text, (x, y), rot, size, layer) in enumerate(self.labels):
            els.append(dict(type="pcb_silkscreen_text", pcb_silkscreen_text_id=f"pcb_silkscreen_text_{i}", pcb_component_id="pcb_board_0", text=text,
                            layer="top" if layer.startswith("F") else "bottom", anchor_position=dict(x=x, y=y), anchor_alignment="center",
                            font="tscircuit2024", font_size=size, ccw_rotation=rot))
        net_trace = {name: f"source_trace_{ni}" for ni, name in enumerate(self.nets)}
        for i, t in enumerate(self.manual):                                    # hand copper: a pcb_trace the router must avoid
            els.append(dict(type="pcb_trace", pcb_trace_id=f"pcb_trace_manual_{i}", source_trace_id=net_trace.get(t["net"]),
                            route=[dict(route_type="wire", x=x, y=y, width=t["width"], layer=_cj_layer(t["layer"])) for x, y in t["pts"]]))
        for i, (net, (x, y)) in enumerate(self.vias):
            els.append(dict(type="pcb_via", pcb_via_id=f"pcb_via_manual_{i}", x=x, y=y, outer_diameter=self.via_dims[0], hole_diameter=self.via_dims[1], layers=["top", "bottom"]))
        return els

    def write(self, path):
        with open(path, "w") as f: json.dump(self.circuit_json(), f, indent=0)
        return path

    # --- KiCad project (text an agent can edit, kicad-cli can check and export)
    def _stackup(self) -> list:
        """`(stackup ...)` for the setup block, the way KiCad 9 / 10 write the board stackup editor's result: silk / paste / mask,
        the copper layers at 35 um with a dielectric between each pair (one core on a 2-layer board; prepreg - core - prepreg ..
        inside, the outer prepregs 0.2 mm and the cores sharing the rest), summing to `thickness` with the two 10 um masks.
        kicad-cli's STEP body is the dielectric sum, so a 4-layer board comes out the same thickness as a 2-layer one."""
        cu_t, mask_t = 0.035, 0.01
        n = self.layers - 1                                                     # dielectrics
        rest = round(self.thickness - self.layers * cu_t - 2 * mask_t, 4)
        if n == 1: diel = [("core", rest)]
        else:
            cores = n // 2
            diel = [("prepreg", 0.2) if i % 2 == 0 else ("core", round((rest - (n - cores) * 0.2) / cores, 4)) for i in range(n)]
        L = lambda name, kind, *rest: ["layer", Q(name), ["type", Q(kind)], *rest]
        out = ["stackup", L("F.SilkS", "Top Silk Screen"), L("F.Paste", "Top Solder Paste"), L("F.Mask", "Top Solder Mask", ["thickness", mask_t])]
        for i, name in enumerate(self.copper):
            out.append(L(name, "copper", ["thickness", cu_t]))
            if i < n:
                kind, t = diel[i]
                out.append(L(f"dielectric {i + 1}", kind, ["thickness", t], ["material", Q("FR4")], ["epsilon_r", 4.5], ["loss_tangent", 0.02]))
        out += [L("B.Mask", "Bottom Solder Mask", ["thickness", mask_t]), L("B.Paste", "Bottom Solder Paste"), L("B.SilkS", "Bottom Silk Screen"),
                ["copper_finish", Q("None")], ["dielectric_constraints", "no"]]
        return out

    def kicad_pcb(self, traces=None) -> str:
        """A .kicad_pcb (format 20241229, loads in KiCad 9/10).  KiCad is y-DOWN: panel (x, y) -> (x, -y); angles are written
        as given (KiCad's CCW on its y-down screen is the y-up CCW angle after the flip, see below), so `kicad-cli pcb export
        step` lands back in the panel frame.  `traces`: Circuit JSON pcb_trace / pcb_via elements (e.g. from
        export.mjs's routed.circuit.json) written as segments / vias; the nets are embedded, so the GUI shows the ratsnest."""
        import uuid as _uuid
        U = lambda: ["uuid", Q(str(_uuid.uuid4()))]
        Y = lambda y: -y
        stroke = lambda w=0.1: ["stroke", ["width", w], ["type", "default"]]
        net_id = {name: i + 1 for i, name in enumerate(self.nets)}
        pad_net = {}                                                           # (ref, pad) -> net name
        for name, pins in self.nets.items():
            for k in pins: pad_net[k] = name
        # the layer table as KiCad 9 / 10 number it (format 20241229): copper on the even ids - F.Cu 0, B.Cu 2, In1.Cu 4, In2.Cu 6 ... -
        # listed in stack order, the technical layers on the odd ones
        cu = [(0, "F.Cu")] + [(2 + 2 * i, f"In{i}.Cu") for i in range(1, self.layers - 1)] + [(2, "B.Cu")]
        tech = ((13, "F.Paste"), (15, "B.Paste"), (5, "F.SilkS"), (7, "B.SilkS"), (1, "F.Mask"), (3, "B.Mask"), (17, "Dwgs.User"), (19, "Cmts.User"),
                (25, "Edge.Cuts"), (27, "Margin"), (31, "F.CrtYd"), (29, "B.CrtYd"), (35, "F.Fab"), (33, "B.Fab"))
        root = ["kicad_pcb", ["version", 20241229.0], ["generator", Q("cadview.pcb")], ["generator_version", Q("0.1")],
                ["general", ["thickness", self.thickness], ["legacy_teardrops", "no"]], ["paper", Q("A4")],
                ["layers"] + [[float(i), Q(n), "signal"] for i, n in cu] + [[float(i), Q(n), "user"] for i, n in tech],
                ["setup", self._stackup(), ["pad_to_mask_clearance", 0.0], ["allow_soldermask_bridges_in_footprints", "no"]],
                ["net", 0.0, Q("")]] + [["net", float(i), Q(n)] for n, i in net_id.items()]
        # footprints: the library tree, re-rooted at the part's position with nets on the pads
        import copy
        for p in self.parts:
            fp = copy.deepcopy(p.fp.tree)
            fp[1] = Q(f"{p.fp.lib}:{p.fp.name}")
            body = [n for n in fp[2:] if not (isinstance(n, list) and n[0] in ("version", "generator", "generator_version"))]
            # KiCad angles are CCW as seen on its y-down screen, which is exactly a CCW angle in the y-up frame after the y flip:
            # KiCad abs = Rk(A)(px, -py) + (cx, -cy); negating y gives R(A)(px, py) + c, so A = rot (verified by DRC: -rot leaves every track dangling)
            # A bottom-side part is the library tree mirrored as KiCad's flip stores it (_flip_tree) at the same (at x -y rot):
            # KiCad abs = Rk(A)(px, py) + (cx, -cy) -> R(A)(px, -py) + c = Placed.pad_xy()
            a = p.rot % 360
            bottom = p.layer == "bottom"
            if bottom:
                for n in body: _flip_tree(n)
            out = [fp[0], fp[1], ["layer", Q("B.Cu" if bottom else "F.Cu")], U(), ["at", p.x, Y(p.y), a]]
            for n in body:
                if not isinstance(n, list): out.append(n); continue
                if n[0] == "layer": continue
                if n[0] == "property" and n[1] in ("Reference", "Value"): n[2] = Q(p.ref if n[1] == "Reference" else p.value)
                if n[0] == "fp_text" and n[1] in ("reference", "value"): n[2] = Q(p.ref if n[1] == "reference" else p.value)   # KiCad <= 7 library format
                if n[0] in ("property", "fp_text"):                                   # text angles are absolute in the file: add the part's
                    at = _kv(n, "at")
                    if at: at[3:] = [((at[3] if len(at) > 3 else 0.0) + a) % 360]
                    if n[0] == "property" and n[1] == "Reference" and p.ref_at and at: at[1:3] = [p.ref_at[0], p.ref_at[1] if bottom else -p.ref_at[1]]
                if n[0] == "pad":
                    at = _kv(n, "at"); at[3:] = [((at[3] if len(at) > 3 else 0.0) + a) % 360]
                    net = pad_net.get((p.ref, str(n[1]).rstrip("0").rstrip(".") if isinstance(n[1], float) else n[1]))
                    if net: n.append(["net", float(net_id[net]), Q(net)])
                    if net == "GND" and n[2] == "thru_hole": n.append(["zone_connect", 2.0])   # solid into the pour: no starved thermals on a connector row
                n = [U() if isinstance(x, list) and x[0] == "uuid" else x for x in n]
                out.append(n)
            root.append(out)
        # mounting holes: NPTH pad footprints, so they reach the drill file and DRC
        for i, (x, y, d) in enumerate(self.holes):
            root.append(["footprint", Q(f"cadview:NPTH_{_num(d)}mm"), ["layer", Q("F.Cu")], U(), ["at", x, Y(y)], ["attr", "exclude_from_pos_files", "exclude_from_bom"],
                         ["property", Q("Reference"), Q(f"H{i + 1}"), ["at", 0.0, 0.0, 0.0], ["layer", Q("F.SilkS")], ["hide", "yes"], U(), ["effects", ["font", ["size", 1.0, 1.0], ["thickness", 0.15]]]],
                         ["property", Q("Value"), Q(f"hole {_num(d)} mm from the CAD"), ["at", 0.0, 0.0, 0.0], ["layer", Q("F.Fab")], ["hide", "yes"], U(), ["effects", ["font", ["size", 1.0, 1.0], ["thickness", 0.15]]]],
                         ["pad", Q(""), "np_thru_hole", "circle", ["at", 0.0, 0.0], ["size", d, d], ["drill", d], ["layers", Q("*.Cu"), Q("*.Mask")], U()]])
        # board edge + cutouts from the exact CAD edges, each as KiCad's own item: gr_line, gr_arc (3-point), gr_circle, gr_curve
        # (a cubic bezier's 4 control points; a spline is split into cubic spans, any other curve approximated by them within
        # CURVE_TOL); only a curve OCC cannot approximate is sampled into lines.  Every point at 6 decimals - KiCad's own nm
        # precision: a flat arc (58 mm radius over a 3 mm chord, sagitta 0.02 mm) rounded to 4 decimals moves its centre 0.1 mm
        XY = lambda p, nd=6: [round(p.X, nd), Y(round(p.Y, nd))] if hasattr(p, "X") else [round(p[0], nd), Y(round(p[1], nd))]
        edge = lambda kind, *geo: root.append([kind, *geo, stroke(), ["layer", Q("Edge.Cuts")], U()])
        for w in self.edge_wires:
            for e in w.edges():                                                 # not order_edges(): that rebuilds a wire-reversed edge's curve backwards
                p0, p1 = e @ 0, e @ 1
                if e.geom_type == GeomType.LINE:
                    edge("gr_line", ["start", *XY(p0)], ["end", *XY(p1)])
                elif e.geom_type == GeomType.CIRCLE and e.is_closed:
                    c = e.arc_center
                    root.append(["gr_circle", ["center", *XY(c)], ["end", round(c.X + e.radius, 6), Y(round(c.Y, 6))], stroke(), ["fill", "none"], ["layer", Q("Edge.Cuts")], U()])
                elif e.geom_type == GeomType.CIRCLE:
                    edge("gr_arc", ["start", *XY(p0)], ["mid", *XY(e @ 0.5)], ["end", *XY(p1)])
                else:
                    runs = _cubic_beziers(e)                                   # BEZIER / BSPLINE exact, ELLIPSE etc. within CURVE_TOL
                    if runs:
                        for P in runs: edge("gr_curve", ["pts"] + [["xy", *XY(q)] for q in P])
                    else:
                        n = max(2, int(e.length / 0.25))
                        pts = [e @ (i / n) for i in range(n + 1)]
                        for q0, q1 in zip(pts, pts[1:]): edge("gr_line", ["start", *XY(q0)], ["end", *XY(q1)])
        # keepouts: rule-area zones on both copper layers
        for i, (c, w, h, layers, why, pour) in enumerate(self.keepouts):
            x0, x1, y0, y1 = c[0] - w / 2, c[0] + w / 2, c[1] - h / 2, c[1] + h / 2
            lay = ["layers", Q("F&B.Cu")] if set(layers) == {"top", "bottom"} else ["layer", Q("F.Cu" if "top" in layers else "B.Cu")]
            root.append(["zone", ["net", 0.0], ["net_name", Q("")], lay, U(), ["name", Q(why or f"keepout {i}")], ["hatch", "edge", 0.5],
                         ["connect_pads", ["clearance", 0.0]], ["min_thickness", 0.25],
                         ["keepout", ["tracks", "not_allowed"], ["vias", "not_allowed"], ["pads", "allowed"], ["copperpour", "allowed" if pour else "not_allowed"], ["footprints", "allowed"]],
                         ["fill", ["thermal_gap", 0.5], ["thermal_bridge_width", 0.5]],
                         ["polygon", ["pts"] + [["xy", round(x, 4), Y(round(y, 4))] for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]]])
        # silkscreen labels
        for text, (x, y), rot, size, layer in self.labels:
            root.append(["gr_text", Q(text), ["at", x, Y(y), rot], ["layer", Q(layer)], U(), ["effects", ["font", ["size", size, size], ["thickness", round(size * 0.15, 3)]]]])
        # copper pours: one zone per (net, layer) over the whole outline, thermal reliefs; filled by kicad-cli drc --refill-zones --save-board
        for i, (net, layer) in enumerate(self.pours):
            layer = _cu(layer)
            root.append(["zone", ["net", float(net_id[net])], ["net_name", Q(net)], ["layer", Q(layer)], U(), ["name", Q(f"{net} pour {layer}")], ["hatch", "edge", 0.5],
                         ["priority", 0.0], ["connect_pads", ["clearance", 0.3]], ["min_thickness", 0.25], ["filled_areas_thickness", "no"],
                         ["fill", "yes", ["thermal_gap", 0.4], ["thermal_bridge_width", 0.4], ["island_removal_mode", 0.0]],
                         ["polygon", ["pts"] + [["xy", x, Y(y)] for x, y in self.outline]]])
        # hand copper
        for t in self.manual:
            nid = float(net_id.get(t["net"], 0))
            for (x0, y0), (x1, y1) in zip(t["pts"], t["pts"][1:]):
                root.append(["segment", ["start", x0, Y(y0)], ["end", x1, Y(y1)], ["width", t["width"]], ["layer", Q(_cu(t["layer"]))], ["net", nid], U()])
        for net, (x, y) in self.vias:                                          # through vias: F.Cu to B.Cu spans every inner layer too
            root.append(["via", ["at", x, Y(y)], ["size", self.via_dims[0]], ["drill", self.via_dims[1]], ["layers", Q("F.Cu"), Q("B.Cu")], ["net", float(net_id.get(net, 0))], U()])
        # routed copper
        trace_net = {}
        if traces:
            st = {e["source_trace_id"]: e.get("display_name") for e in traces if e.get("type") == "source_trace"}
            for t in traces:
                if t.get("type") != "pcb_trace" or str(t.get("pcb_trace_id", "")).startswith("pcb_trace_manual"): continue
                net = st.get(t.get("source_trace_id")); nid = float(net_id.get(net, 0))
                pts = [r for r in t["route"]]
                for r0, r1 in zip(pts, pts[1:]):
                    if r0.get("route_type") == "wire" and r1.get("route_type") == "wire" and r0["layer"] == r1["layer"]:
                        root.append(["segment", ["start", round(r0["x"], 4), Y(round(r0["y"], 4))], ["end", round(r1["x"], 4), Y(round(r1["y"], 4))], ["width", r0["width"]],
                                     ["layer", Q(_cu(r0["layer"]))], ["net", nid], U()])
                for r in pts:
                    if r.get("route_type") == "via" and "x" in r:
                        root.append(["via", ["at", round(r["x"], 4), Y(round(r["y"], 4))], ["size", self.via_dims[0]], ["drill", self.via_dims[1]], ["layers", Q("F.Cu"), Q("B.Cu")], ["net", nid], U()])
        root.append(["embedded_fonts", "no"])
        return _ser(root) + "\n"

    # --- schematic: one symbol per part, every net a global label on its pins, no wires
    def kicad_sch(self, name, layout=None, power_flags=True, pin_types=None) -> str:
        """A KiCad 10 .kicad_sch for the same parts and nets.  `layout`: list of columns, each a list of refs, left to right
        (parts not listed go in a last column).  Pins with no net get a no-connect; a power net ('+...', '3V3', 'GND') with no
        power-output pin on it gets a PWR_FLAG so ERC sees a driver.  `pin_types`: {(ref, pin): "passive" | ...} overrides the
        library's electrical type in the embedded symbol (e.g. a second power-output GND pin on a net that already has one)."""
        import copy, uuid as _uuid
        U = lambda: Q(str(_uuid.uuid4()))
        root_uuid = str(_uuid.uuid4())
        font = lambda hide=False: ["effects", ["font", ["size", 1.27, 1.27]]] + ([["hide", "yes"]] if hide else [])
        pad_net = {(r, n): net for net, pins in self.nets.items() for r, n in pins}
        syms = {}
        for p in self.parts:
            if not p.symbol: raise ValueError(f"{p.ref}: no symbol given (place(..., symbol=('Lib', 'Name')))")
            syms[p.ref] = kicad_symbol(*p.symbol)
            for (ref, num), kind in (pin_types or {}).items():
                if ref != p.ref: continue
                s = syms[p.ref]
                for unit in (n for n in s.tree if isinstance(n, list) and n[0] == "symbol"):
                    for pin in (n for n in unit if isinstance(n, list) and n[0] == "pin"):
                        if str(_kv(pin, "number")[1]) == str(num): pin[1] = kind
                s.pins = [(n, x, y, a, kind if n == str(num) else k) for n, x, y, a, k in s.pins]
        net_power_out = {net for p in self.parts for num, _, _, _, kind in syms[p.ref].pins if kind == "power_out" for net in [pad_net.get((p.ref, num))] if net}
        lib_symbols = {f"{s.lib}:{s.name}": s.tree for s in syms.values()}
        flag = kicad_symbol("power", "PWR_FLAG") if power_flags else None
        if flag: lib_symbols["power:PWR_FLAG"] = flag.tree
        # columns: stack each part by its pin extent, 10 mm apart; columns 70 mm apart
        cols = [list(c) for c in (layout or [])]
        rest = [p.ref for p in self.parts if not any(p.ref in c for c in cols)]
        if rest: cols.append(rest)
        els, x = [], 40.0
        G = lambda v: round(round(v / 1.27) * 1.27, 2)                                     # KiCad's 50 mil grid
        for col in cols:
            y = 40.0
            for ref in col:
                p = next(q for q in self.parts if q.ref == ref); s = syms[ref]
                ys = [py for _, _, py, _, _ in s.pins] or [0.0]; xs = [px for px, *_ in [(pp[1],) for pp in s.pins]] or [0.0]
                top = max(ys); bottom = min(ys)
                Y = G(y + top + 2.54)                                                  # symbol origin so its highest pin sits 2.54 below y
                X = G(x)
                inst = ["symbol", ["lib_id", Q(f"{s.lib}:{s.name}")], ["at", X, Y, 0.0], ["unit", 1.0], ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"], ["uuid", U()]]
                inst.append(["property", Q("Reference"), Q(p.ref), ["at", G(X + max(xs) + 2.54), G(Y - top - 1.27), 0.0], font()])
                inst.append(["property", Q("Value"), Q(p.value), ["at", G(X + max(xs) + 2.54), G(Y - top + 1.27), 0.0], font()])
                inst.append(["property", Q("Footprint"), Q(f"{p.fp.lib}:{p.fp.name}"), ["at", X, Y, 0.0], font(True)])
                inst.append(["property", Q("Datasheet"), Q(""), ["at", X, Y, 0.0], font(True)])
                inst.append(["property", Q("LCSC"), Q(p.lcsc), ["at", X, Y, 0.0], font(True)])
                seen = set()
                for num, px, py, ang, kind in s.pins:
                    inst.append(["pin", Q(num), ["uuid", U()]])
                    sx, sy = G(X + px), G(Y - py)
                    if (sx, sy) in seen: continue                                      # stacked pins share one label
                    seen.add((sx, sy))
                    net = pad_net.get((p.ref, num))
                    rot = (ang + 180) % 360                                            # label points away from the body
                    if net:
                        els.append(["global_label", Q(net), ["shape", "input"], ["at", sx, sy, rot], ["fields_autoplaced", "yes"],
                                    ["effects", ["font", ["size", 1.27, 1.27]], ["justify", "left" if rot in (0, 90) else "right"]], ["uuid", U()],
                                    ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", sx, sy, 0.0], font(True)]])
                    elif kind != "no_connect":
                        els.append(["no_connect", ["at", sx, sy], ["uuid", U()]])
                inst.append(["instances", ["project", Q(name), ["path", Q("/" + root_uuid), ["reference", Q(p.ref)], ["unit", 1.0]]]])
                els.append(inst)
                y = y + (top - bottom) + 2.54 + 12.7
            x += 76.2
        if flag:
            fx, fy = G(x), 40.0
            fnum, fpx, fpy, fang, _ = flag.pins[0]
            for i, net in enumerate(n for n in self.nets if n.startswith(("+", "3V3", "GND")) and n not in net_power_out):
                X, Y = G(fx), G(fy + i * 12.7)
                els.append(["symbol", ["lib_id", Q("power:PWR_FLAG")], ["at", X, Y, 0.0], ["unit", 1.0], ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"], ["uuid", U()],
                            ["property", Q("Reference"), Q(f"#FLG{i + 1}"), ["at", X, Y, 0.0], font(True)], ["property", Q("Value"), Q("PWR_FLAG"), ["at", G(X + 2.54), Y, 0.0], font()],
                            ["property", Q("Footprint"), Q(""), ["at", X, Y, 0.0], font(True)], ["property", Q("Datasheet"), Q("~"), ["at", X, Y, 0.0], font(True)],
                            ["pin", Q(fnum), ["uuid", U()]], ["instances", ["project", Q(name), ["path", Q("/" + root_uuid), ["reference", Q(f"#FLG{i + 1}")], ["unit", 1.0]]]]])
                sx, sy = G(X + fpx), G(Y - fpy); rot = (fang + 180) % 360
                els.append(["global_label", Q(net), ["shape", "input"], ["at", sx, sy, rot], ["fields_autoplaced", "yes"],
                            ["effects", ["font", ["size", 1.27, 1.27]], ["justify", "left" if rot in (0, 90) else "right"]], ["uuid", U()],
                            ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", sx, sy, 0.0], font(True)]])
        root = ["kicad_sch", ["version", 20250114.0], ["generator", Q("cadview.pcb")], ["generator_version", Q("0.1")], ["uuid", Q(root_uuid)], ["paper", Q("A3")],
                ["title_block", ["title", Q(self.name)], ["date", Q(__import__("datetime").date.today().isoformat())], ["comment", 1.0, Q("generated by cadview.pcb from the build123d board - nets are global labels, no wires")]],
                ["lib_symbols"] + list(lib_symbols.values())] + els + [["sheet_instances", ["path", Q("/"), ["page", Q("1")]]], ["embedded_fonts", "no"]]
        self._root_uuid = root_uuid
        return _ser(root) + "\n"

    def check_netlist(self, path) -> list:
        """compare a `kicad-cli sch export netlist` (kicadsexpr) with the board's nets: returns the mismatches (empty = agree)"""
        with open(path) as f: tree = _sexp(f.read())
        nets = _kv(tree, "nets") or []
        sch = {}
        for n in nets[1:]:
            name = _kv(n, "name")[1]
            if name.startswith("unconnected-"): continue                              # KiCad's one-pin nets for no-connects
            sch[name] = {(_kv(nd, "ref")[1], str(_kv(nd, "pin")[1])) for nd in n if isinstance(nd, list) and nd[0] == "node"}
        pcb = {name: {(r, str(p)) for r, p in pins} for name, pins in self.nets.items()}
        out = []
        for name in sorted(set(sch) | set(pcb)):
            a, b = sch.get(name, set()), pcb.get(name, set())
            if a != b: out.append((name, sorted(a - b), sorted(b - a)))
        return out

    def kicad_pro(self, name) -> str:
        rules = dict(self.rules, min_via_drill=self.via_dims[1] if False else self.rules.get("min_through_hole_diameter", 0.3))
        sev = {"lib_footprint_issues": "warning", "lib_footprint_mismatch": "warning", "silk_over_copper": "error", "courtyards_overlap": "error",
               "npth_inside_courtyard": "ignore", "holes_co_located": "warning", "track_dangling": "error", "unconnected_items": "error",
               "isolated_copper": "warning", "footprint_type_mismatch": "ignore", "missing_courtyard": "ignore", "solder_mask_bridge": "error"}
        return json.dumps({"meta": {"filename": f"{name}.kicad_pro", "version": 1},
                           "board": {"design_settings": {"rules": rules, "rule_severities": sev,
                                                         "track_widths": [0.0, self.track_width, 0.5], "via_dimensions": [{"diameter": 0.0, "drill": 0.0}, {"diameter": self.via_dims[0], "drill": self.via_dims[1]}]}},
                           "boards": [], "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []}, "text_variables": {},
                           "sheets": [[getattr(self, "_root_uuid", ""), "Root"]], "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []}}, indent=2)

    def netlist(self, name) -> str:
        """KiCad netlist (`File > Import Netlist` in pcbnew): components + nets, so the GUI path works without a schematic."""
        comps = [["comp", ["ref", Q(p.ref)], ["value", Q(p.value)], ["footprint", Q(f"{p.fp.lib}:{p.fp.name}")]] for p in self.parts]
        nets = [["net", ["code", Q(str(i + 1))], ["name", Q(n)]] + [["node", ["ref", Q(r)], ["pin", Q(pad)]] for r, pad in pins] for i, (n, pins) in enumerate(self.nets.items())]
        return _ser(["export", ["version", Q("E")], ["design", ["source", Q(f"{name}.py")], ["tool", Q("cadview.pcb")]], ["components"] + comps, ["nets"] + nets]) + "\n"

    def write_kicad(self, outdir, name, traces=None, layout=None, pin_types=None):
        """the KiCad project: .kicad_pcb, .kicad_sch (layout = schematic columns of refs), .kicad_pro, .net"""
        paths = []
        for ext, txt in ((".kicad_pcb", self.kicad_pcb(traces)), (".kicad_sch", self.kicad_sch(name, layout, pin_types=pin_types)), (".kicad_pro", self.kicad_pro(name)), (".net", self.netlist(name))):
            p = os.path.join(outdir, name + ext)
            with open(p, "w") as f: f.write(txt)
            paths.append(p)
        return paths

    # --- build123d
    def solid(self, color=None, models=True, routed=None) -> list:
        """The board as build123d parts in the panel frame: FR4 slab (outline, holes, cutouts) at self.z, plus each part's KiCad
        STEP model on the top face (a bottom-side part turned over under the board) and its pads.  `routed`: a circuit.json path
        with pcb_trace elements -> top-layer copper drawn as thin strips.  Not compared with KiCad's own STEP export by any test."""
        if color is None:
            color = Color(0.1, 0.4, 0.2)
        sk = Polygon(*self.outline, align=None)
        for x, y, d in self.holes + self.circle_cutouts: sk -= Pos(x, y) * Circle(d / 2)
        for poly in self.cutouts: sk -= Polygon(*poly, align=None)
        slab = Pos(0, 0, self.z) * extrude(sk, self.thickness)
        slab.label, slab.color = f"{self.name} FR4", color
        out = [slab]
        cache = {}
        for p in self.parts:
            # a bottom-side part is turned over about its x axis (Rot X 180: y and z mirrored, the same flip as pad_xy) under the board
            bottom = p.layer == "bottom"
            side = Pos(p.x, p.y, self.z if bottom else self.z + self.thickness) * Rot(0, 0, p.rot) * (Rot(180, 0, 0) if bottom else Rot(0, 0, 0))
            if models and p.fp.model and os.path.exists(p.fp.model):
                if p.fp.model not in cache: cache[p.fp.model] = import_step(p.fp.model)
                m = side * cache[p.fp.model]
                m.label = f"{p.ref} {p.fp.name}"; out.append(m)
            for q in p.fp.pads:
                if not q.layers: continue
                x, y = p.pad_xy(q)
                zp = self.z - 0.05 if bottom else self.z + self.thickness
                pad = Pos(x, y, zp) * (Cylinder(q.w / 2, 0.05, align=(Align.CENTER, Align.CENTER, Align.MIN)) if q.shape == "circle"
                                      else Rot(0, 0, p.rot) * Box(q.w, q.h, 0.05, align=(Align.CENTER, Align.CENTER, Align.MIN)))
                pad.label, pad.color = f"{p.ref} pad {q.number}", Color(0.85, 0.65, 0.2); out.append(pad)
        if routed and os.path.exists(routed):
            with open(routed) as f: els = json.load(f)
            for t in (e for e in els if e["type"] == "pcb_trace"):
                pts = [(r["x"], r["y"]) for r in t["route"] if r.get("route_type") == "wire"]
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    L = math.hypot(x1 - x0, y1 - y0)
                    if L < 1e-6: continue
                    strip = Pos((x0 + x1) / 2, (y0 + y1) / 2, self.z + self.thickness + 0.03) * Rot(0, 0, math.degrees(math.atan2(y1 - y0, x1 - x0))) * Box(L + 0.3, 0.3, 0.05)
                    strip.label, strip.color = f"trace {t.get('source_trace_id', '')}", Color(0.85, 0.65, 0.2); out.append(strip)
        return out
