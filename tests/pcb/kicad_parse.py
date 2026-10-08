"""An independent, tiny reader for KiCad's text formats, used as the *oracle* side of the conformance tests.

Nothing here imports the module under test: the s-expression parser, the footprint / board readers, the IPC-D-356
reader and the Gerber / Excellon summaries are all written separately so a bug in cadpcb's own parser cannot hide
behind itself.  Coordinates are returned exactly as KiCad stores them (y DOWN, mm); the tests do the y flip when
they compare against the DSL's y-up frame.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ------------------------------------------------------------------------------------------ s-expressions ----
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()]+')
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")   # plain decimals only: KiCad 5/6's hex `(tedit 527E5841)` is a symbol, not 5.27e5843


def parse(text: str):
    """KiCad s-expression -> nested Python lists.  Quoted strings -> str, numbers -> float, bare symbols -> str.
    (Quoted and bare strings are not distinguished: the tests never re-serialise.)"""
    root = []
    stack = [root]
    for m in _TOKEN.finditer(text):
        t = m.group(0)
        if t == "(":
            node = []
            stack[-1].append(node)
            stack.append(node)
        elif t == ")":
            stack.pop()
        elif t[0] == '"':
            stack[-1].append(t[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        elif _NUMBER.fullmatch(t):
            stack[-1].append(float(t))
        else:
            stack[-1].append(t)
    if len(stack) != 1:
        raise ValueError("unbalanced parentheses")
    return root[0]


def children(node, key):
    """all direct children of `node` whose head is `key`"""
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def child(node, key, default=None):
    cs = children(node, key)
    return cs[0] if cs else default


def numstr(v) -> str:
    """pad numbers come back as float when they look numeric: '1', '1.0' -> '1'"""
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    return str(v)


# ------------------------------------------------------------------------------------------- footprints ----
@dataclass
class PadRec:
    number: str
    kind: str           # smd | thru_hole | np_thru_hole | connect
    shape: str          # circle | rect | oval | roundrect | custom | trapezoid
    x: float            # footprint frame, KiCad y-down (or absolute when read from a board with `absolute=True`)
    y: float
    rot: float          # pad orientation as stored (absolute in a board file, relative in a .kicad_mod)
    w: float
    h: float
    drill: tuple        # () for none; (d,) round; ('oval', a, b) slot
    layers: tuple       # as written, e.g. ('F.Cu', 'F.Paste', 'F.Mask') or ('*.Cu', '*.Mask')
    net: str = ""       # net name on a board pad ("" = none)
    prim_bbox: tuple | None = None   # custom pads: (xmin, ymin, xmax, ymax) of the primitives in the pad frame
    offset: tuple = (0.0, 0.0)       # `(drill (offset dx dy))`: the copper shape sits this far from the pad position (pad frame)
    rratio: float | None = None      # `(roundrect_rratio r)` as written (roundrect / chamfered pads)
    chamfer: tuple = ()              # `(chamfer top_left ...)`: the chamfered corners of a roundrect pad

    @property
    def copper(self) -> bool:
        return any(l.endswith(".Cu") or l.startswith("*") for l in self.layers)


def read_pad(node) -> PadRec:
    at = child(node, "at")
    size = child(node, "size")
    d = child(node, "drill")
    drill: tuple = ()
    offset = (0.0, 0.0)
    if d:
        nums = [v for v in d[1:] if isinstance(v, float)]
        if "oval" in d[1:]:
            drill = ("oval", nums[0], nums[1]) if len(nums) >= 2 else ("oval", nums[0], nums[0])
        elif nums:
            drill = (nums[0],)
        off = child(d, "offset")
        if off:
            offset = (off[1], off[2])
    lay = child(node, "layers")
    net = child(node, "net")
    prim = child(node, "primitives")
    bbox = None
    if prim:
        xs, ys = [], []
        for g in prim[1:]:
            if not isinstance(g, list):
                continue
            if g[0] == "gr_poly":
                for pt in child(g, "pts")[1:]:
                    xs.append(pt[1]); ys.append(pt[2])
            elif g[0] == "gr_circle":
                c, e = child(g, "center"), child(g, "end")
                r = math.hypot(e[1] - c[1], e[2] - c[2])
                xs += [c[1] - r, c[1] + r]; ys += [c[2] - r, c[2] + r]
            elif g[0] in ("gr_rect", "gr_line"):
                s, e = child(g, "start"), child(g, "end")
                xs += [s[1], e[1]]; ys += [s[2], e[2]]
            elif g[0] == "gr_arc":
                for k in ("start", "mid", "end"):
                    p = child(g, k); xs.append(p[1]); ys.append(p[2])
        if xs:
            bbox = (min(xs), min(ys), max(xs), max(ys))
    # `(net 3 "GND")` up to format 20241229; KiCad 10 (20260206) re-saves pads with `(net "GND")`: the name is the last string
    net_name = next((str(v) for v in reversed(net[1:]) if isinstance(v, str)), "") if net else ""
    rr, ch = child(node, "roundrect_rratio"), child(node, "chamfer")
    return PadRec(numstr(node[1]), str(node[2]), str(node[3]), at[1], at[2], at[3] if len(at) > 3 else 0.0,
                  size[1], size[2], drill, tuple(str(l) for l in lay[1:]) if lay else (), net_name, bbox, offset,
                  rr[1] if rr else None, tuple(str(c) for c in ch[1:]) if ch else ())


@dataclass
class FootprintRec:
    name: str                       # "Lib:Name" on a board, "Name" in a .kicad_mod
    pads: list
    x: float = 0.0                  # board placement (KiCad frame); 0 for a library footprint
    y: float = 0.0
    rot: float = 0.0
    layer: str = "F.Cu"
    ref: str = ""
    value: str = ""
    model: str = ""


def read_footprint(node) -> FootprintRec:
    at = child(node, "at", ["at", 0.0, 0.0])
    layer = child(node, "layer")
    props = {p[1]: p[2] for p in children(node, "property") if len(p) > 2 and isinstance(p[2], str)}
    # KiCad 5 / 6 / 7 files carry the reference and value as `(fp_text reference "R1" ...)` instead of properties
    # (a KiCad 5 `(module ...)` writes them bare: `(fp_text value 1u ...)`, so a numeric value comes back as a float)
    for t in children(node, "fp_text"):
        if len(t) > 2 and t[1] in ("reference", "value"):
            props.setdefault(str(t[1]).capitalize(), numstr(t[2]))
    model = child(node, "model")
    return FootprintRec(str(node[1]), [read_pad(p) for p in children(node, "pad")], at[1], at[2],
                        at[3] if len(at) > 3 else 0.0, layer[1] if layer else "F.Cu",
                        props.get("Reference", ""), props.get("Value", ""), model[1] if model else "")


def read_kicad_mod(path) -> FootprintRec:
    with open(path) as f:
        return read_footprint(parse(f.read()))


# ------------------------------------------------------------------------------------------------ boards ----
@dataclass
class EdgeItem:
    kind: str                       # line | arc | circle | rect | poly | curve
    pts: tuple                      # line: (start, end); arc: (start, mid, end); circle: (center, end); rect: (start, end);
    width: float = 0.0              # poly: (p0, p1, ...); curve (cubic bezier): (start, ctrl1, ctrl2, end)


@dataclass
class BoardRec:
    footprints: list
    nets: list                      # net names in the board's net table
    edge: list                      # EdgeItem on Edge.Cuts (board-level graphics only)
    segments: int = 0
    vias: list = field(default_factory=list)   # (x, y, drill) of every via (KiCad frame)
    zones: int = 0
    version: float = 0.0
    copper_layers: list = field(default_factory=list)   # copper layer names from the `(layers ...)` table, in stack order
    fp_edge_items: int = 0          # fp_line / fp_arc / ... drawn on Edge.Cuts inside footprints (castellations, module cutouts)
    castellated: bool = False       # `(castellated_pads yes)` in the setup / stackup: pads on the board edge are meant to be cut through
    fp_copper_items: int = 0        # fp_line / fp_arc / fp_poly ... drawn on a copper layer inside footprints (they plot as lines / regions)
    via_spans: list = field(default_factory=list)   # per via, in `vias` order: (kind, from_layer, to_layer) - kind 'through' | 'blind' | 'micro' as
                                                    # written (`(via blind ...)` / `(via micro ...)`); the layers are what decides whether it spans the stack
    track_arcs: int = 0             # `(arc ...)` track items on copper (rounded routing)
    teardrop_zones: int = 0         # zones KiCad generated as teardrops (`(attr (teardrop ...))`, KiCad 7+)
    keepout_zones: int = 0          # zones with a `(keepout ...)` rule block (rule areas)
    net_ties: int = 0               # footprints with `(net_tie_pad_groups ...)` (KiCad 7+ net ties)
    vcut_texts: int = 0             # `gr_text` items reading V-CUT / V_CUT / VCUT: a panel scored for breaking apart
    flex: bool = False              # a stackup dielectric of Polyimide (a flex circuit)
    groups: int = 0                 # `(group ...)` blocks
    mirrored_texts: int = 0         # texts with `(justify ... mirror)`: the silkscreen of parts on the back

    def pad_nets(self) -> dict:
        """{(ref, pad_number): sorted list of net names} over every pad on the board (duplicate pad numbers keep one entry each)"""
        out: dict = {}
        for fp in self.footprints:
            for p in fp.pads:
                out.setdefault((fp.ref, p.number), []).append(p.net)
        return {k: sorted(v) for k, v in out.items()}

    def blind_buried_vias(self) -> list:
        """the vias that do not span the whole stack (outer copper to outer copper), whatever flag they were written with:
        [(x, y, drill, from_layer, to_layer)].  A `(via blind ...)` on a 2-layer board whose layers are F.Cu / B.Cu is a through via."""
        if len(self.copper_layers) < 2:
            return []
        outer = {self.copper_layers[0], self.copper_layers[-1]}
        return [(x, y, d, a, b) for (x, y, d), (_, a, b) in zip(self.vias, self.via_spans) if {a, b} != outer]


def _legacy_arc(center, start, angle) -> tuple:
    """a KiCad 5 arc - `(start)` is the CENTRE, `(end)` the start point, `(angle)` the sweep in degrees, positive clockwise on
    KiCad's y-down screen (RotatePoint's sense) - as the (start, mid, end) triple KiCad 6+ stores"""
    dx, dy = start[0] - center[0], start[1] - center[1]
    def at(t):
        c, s = math.cos(math.radians(t)), math.sin(math.radians(t))
        return (center[0] + dx * c - dy * s, center[1] + dx * s + dy * c)
    return (start, at(angle / 2), at(angle))


def footprint_nodes(tree) -> list:
    """the board's footprint nodes in file order: `(footprint ...)` from KiCad 6 on, `(module ...)` in a KiCad 5 file"""
    return [n for n in tree if isinstance(n, list) and n and n[0] in ("footprint", "module")]


def _count_mirrored(node) -> int:
    n = 0
    for c in node:
        if isinstance(c, list) and c:
            n += (c[0] == "justify" and "mirror" in c[1:]) + _count_mirrored(c)
    return n


def read_board(path) -> BoardRec:
    """A .kicad_pcb from KiCad 5 (format 20171130: `(module ...)`, bare symbols, `(width w)` strokes, arcs as centre / start /
    angle, a via's drill defaulting to the setup's `via_drill` / `uvia_drill`) up to KiCad 10."""
    with open(path) as f:
        tree = parse(f.read())
    assert tree[0] == "kicad_pcb", path
    nets = [next((str(v) for v in reversed(n[1:]) if isinstance(v, str)), "") for n in children(tree, "net")]
    setup = child(tree, "setup") or []
    default_drill = {k: (child(setup, key) or [None, 0.0])[1] for k, key in (("through", "via_drill"), ("blind", "via_drill"), ("micro", "uvia_drill"))}
    vias, spans = [], []
    for v in children(tree, "via"):
        kind = v[1] if len(v) > 1 and isinstance(v[1], str) and v[1] in ("blind", "micro") else "through"
        at, d, lay = child(v, "at"), child(v, "drill"), child(v, "layers") or [None, "", ""]
        vias.append((at[1], at[2], d[1] if d else default_drill[kind]))
        spans.append((kind, str(lay[1]), str(lay[2])))
    edge = []
    for n in tree:
        if not (isinstance(n, list) and n and isinstance(n[0], str) and n[0].startswith("gr_")):
            continue
        lay = child(n, "layer")
        if not lay or lay[1] != "Edge.Cuts":
            continue
        stroke, width = child(n, "stroke"), child(n, "width")                  # `(stroke (width w))` from KiCad 6 on; `(width w)` in KiCad 5
        w = child(stroke, "width")[1] if stroke else (width[1] if width else 0.0)
        P = lambda k: tuple(child(n, k)[1:3])
        if n[0] == "gr_line":
            edge.append(EdgeItem("line", (P("start"), P("end")), w))
        elif n[0] == "gr_arc":
            if child(n, "mid"):
                edge.append(EdgeItem("arc", (P("start"), P("mid"), P("end")), w))
            else:                                                            # KiCad 5: (start = centre) (end = start point) (angle)
                edge.append(EdgeItem("arc", _legacy_arc(P("start"), P("end"), child(n, "angle")[1]), w))
        elif n[0] == "gr_circle":
            edge.append(EdgeItem("circle", (P("center"), P("end")), w))
        elif n[0] == "gr_rect":
            edge.append(EdgeItem("rect", (P("start"), P("end")), w))
        elif n[0] == "gr_poly":
            edge.append(EdgeItem("poly", tuple(tuple(pt[1:3]) for pt in child(n, "pts")[1:]), w))
        elif n[0] == "gr_curve":
            edge.append(EdgeItem("curve", tuple(tuple(pt[1:3]) for pt in child(n, "pts")[1:]), w))
    fp_edge = fp_cu = ties = 0
    fps = footprint_nodes(tree)
    for f in fps:
        ties += bool(child(f, "net_tie_pad_groups"))
        for g in f:
            if isinstance(g, list) and g and isinstance(g[0], str) and g[0].startswith("fp_") and g[0] != "fp_text":
                lay = child(g, "layer")
                fp_edge += bool(lay) and lay[1] == "Edge.Cuts"
                fp_cu += bool(lay) and str(lay[1]).endswith(".Cu")
    layers = child(tree, "layers") or []
    copper = [str(l[1]) for l in layers[1:] if isinstance(l, list) and str(l[1]).endswith(".Cu")]
    ver = child(tree, "version")
    stackup = child(setup, "stackup") or []
    cast = child(setup, "castellated_pads") or child(stackup, "castellated_pads")   # KiCad 9 puts it in the stackup
    flex = any(isinstance(l, list) and l and l[0] == "layer" and (child(l, "material") or [None, ""])[1] == "Polyimide" for l in stackup[1:])
    zones = children(tree, "zone")
    teardrops = sum(1 for z in zones if child(child(z, "attr") or [], "teardrop"))
    keepouts = sum(1 for z in zones if child(z, "keepout"))
    vcut = sum(1 for t in children(tree, "gr_text") if len(t) > 1 and isinstance(t[1], str) and re.search(r"v[-_ ]?cut", t[1], re.I))
    return BoardRec([read_footprint(n) for n in fps], nets, edge, len(children(tree, "segment")), vias, len(zones),
                    ver[1] if ver else 0.0, copper, fp_edge, bool(cast) and cast[1] == "yes", fp_cu,
                    via_spans=spans, track_arcs=len(children(tree, "arc")), teardrop_zones=teardrops, keepout_zones=keepouts, net_ties=ties,
                    vcut_texts=vcut, flex=flex, groups=len(children(tree, "group")), mirrored_texts=_count_mirrored(tree))


def pad_abs(fp: FootprintRec, p: PadRec) -> tuple:
    """absolute KiCad (y-down) position of a board pad: footprint origin + pad offset rotated by the footprint angle
    (KiCad rotates CCW on its y-down screen: x' = x cos a + y sin a, y' = -x sin a + y cos a)"""
    a = math.radians(fp.rot)
    c, s = math.cos(a), math.sin(a)
    return (fp.x + p.x * c + p.y * s, fp.y - p.x * s + p.y * c)


# --------------------------------------------------------------------------------------------- IPC-D-356 ----
_D356 = re.compile(r"^(3[12]7|367)(.{14})\s{3}(.{6})(?:-(.{4})|\s{5})")


def read_ipcd356(path) -> dict:
    """{net name: {(ref, pin), ...}} from `kicad-cli pcb export ipcd356`; 'N/C' (no net) records are dropped.
    Fixed columns per IPC-D-356: 1-3 record (317 TH / 327 SMD / 367 NPTH), 4-17 net, 21-26 ref des, 27 '-', 28-31 pin."""
    out: dict = {}
    with open(path) as f:
        for line in f:
            m = _D356.match(line)
            if not m:
                continue
            net = m.group(2).strip()
            if net in ("N/C", ""):
                continue
            ref = m.group(3).strip()
            pin = (m.group(4) or "").strip()
            out.setdefault(net, set()).add((ref, pin))
    return out


# ---------------------------------------------------------------------------------- Gerber / Excellon summaries ----
def _ap_sig(a) -> tuple:
    """a comparable signature for a Gerber aperture: (name, numbers...).  Macro apertures carry the macro's base name
    (RoundRect3 -> RoundRect) and their parameters; the flash's own bounding box is appended by the caller so FreePoly
    (custom pad) macros, whose outline lives in the macro body, still compare by size."""
    n = type(a).__name__
    if n == "CircleAperture":
        return ("C", a.diameter)
    if n == "RectangleAperture":
        return ("R", a.w, a.h, (getattr(a, "rotation", 0.0) or 0.0))
    if n == "ObroundAperture":
        return ("O", a.w, a.h, (getattr(a, "rotation", 0.0) or 0.0))
    if n == "PolygonAperture":
        return ("P", a.diameter, float(a.n_vertices), (getattr(a, "rotation", 0.0) or 0.0))
    if n == "ApertureMacroInstance":
        return (re.sub(r"\d+$", "", a.macro.name),) + tuple(float(v) for v in a.parameters)
    return (n,)


@dataclass
class FlashRec:
    ref: str
    pad: str
    net: str
    x: float            # flash position (gerber frame = KiCad x, -KiCad y)
    y: float
    cx: float           # centre of the flashed shape's bounding box (differs from x, y for custom pads with an off-centre anchor)
    cy: float
    bw: float           # bounding box size
    bh: float
    sig: tuple


def read_copper(path) -> dict:
    """one copper Gerber -> {'flashes': [FlashRec], 'lines': n, 'arcs': n, 'regions': n}.  Lines/arcs (tracks) and
    regions (zone fills) are counted only: the comparisons exclude copper routing on purpose."""
    from gerbonara import GerberFile
    from gerbonara import graphic_objects as go
    g = GerberFile.open(path)
    assert str(g.unit) == "mm", f"{path}: unit {g.unit}"
    out = {"flashes": [], "lines": 0, "arcs": 0, "regions": 0}
    for o in g.objects:
        if isinstance(o, go.Flash):
            P = o.attrs.get(".P", ())
            N = o.attrs.get(".N", ())
            (x0, y0), (x1, y1) = o.bounding_box()
            ref = _unescape(P[0]) if len(P) > 0 else ""
            pad = _unescape(P[1]) if len(P) > 1 else ""
            out["flashes"].append(FlashRec(ref, pad, N[0] if N else "", o.x, o.y, (x0 + x1) / 2, (y0 + y1) / 2,
                                           x1 - x0, y1 - y0, _ap_sig(o.aperture)))
        elif isinstance(o, go.Line):
            out["lines"] += 1
        elif isinstance(o, go.Arc):
            out["arcs"] += 1
        elif isinstance(o, go.Region):
            out["regions"] += 1
    return out


def _unescape(s: str) -> str:
    return re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)


def _ends(p, q) -> tuple:
    """the two endpoints in a direction-free order: by x, then by y, coordinates within 1 um counting as equal - so a
    line that is vertical within 1 um in one file and exactly vertical in the other orders the same way in both"""
    for i in (0, 1):
        if abs(p[i] - q[i]) > 1e-3:
            return (p, q) if p[i] < q[i] else (q, p)
    return (p, q)


def read_outline(path) -> list:
    """Edge.Cuts Gerber -> list of ('line', x1, y1, x2, y2) / ('arc', x1, y1, x2, y2, cx, cy) with endpoints sorted so
    direction does not matter; arc centres absolute."""
    from gerbonara import GerberFile
    from gerbonara import graphic_objects as go
    g = GerberFile.open(path)
    out = []
    for o in g.objects:
        if isinstance(o, go.Line):
            a, b = _ends((o.x1, o.y1), (o.x2, o.y2))
            out.append(("line", a[0], a[1], b[0], b[1]))
        elif isinstance(o, go.Arc):
            a, b = _ends((o.x1, o.y1), (o.x2, o.y2))
            out.append(("arc", a[0], a[1], b[0], b[1], o.x1 + o.cx, o.y1 + o.cy))
        elif isinstance(o, go.Region):
            out.append(("region", float(len(o.outline))))
    return out


def read_drills(path) -> list:
    """Excellon -> list of ('hole', x, y, d) / ('slot', x1, y1, x2, y2, d); empty when the file does not exist."""
    import os
    if not os.path.exists(path):
        return []
    from gerbonara.excellon import ExcellonFile
    from gerbonara import graphic_objects as go
    e = ExcellonFile.open(path)
    out = []
    for o in e.objects:
        d = float(o.tool.diameter)
        if isinstance(o, go.Flash):
            out.append(("hole", o.x, o.y, d))
        elif isinstance(o, go.Line):
            a, b = sorted([(o.x1, o.y1), (o.x2, o.y2)])
            out.append(("slot", a[0], a[1], b[0], b[1], d))
        elif isinstance(o, go.Arc):
            out.append(("slot-arc", o.x1, o.y1, o.x2, o.y2, d))
    return out


# ------------------------------------------------------------------------------------ tolerant multiset match ----
def close(a, b, tol) -> bool:
    """two signature tuples agree: same length, strings equal, numbers within tol"""
    if len(a) != len(b):
        return False
    for u, v in zip(a, b):
        if isinstance(u, str) or isinstance(v, str):
            if u != v:
                return False
        elif abs(float(u) - float(v)) > tol:
            return False
    return True


def _exact(r) -> tuple:
    return tuple(round(float(v), 6) if not isinstance(v, str) else v for v in r)


def match_multisets(a: list, b: list, tol: float, key=lambda r: ()):
    """one-to-one matching of two lists of signature tuples (grouped by `key`, e.g. (ref, pad)); returns
    (matched, unmatched_a, unmatched_b).  A record matches another when every number agrees within `tol`.  Records equal
    to 1e-6 are paired first, the rest greedily within `tol`: a polyline of segments shorter than `tol` (KiCad's plot of
    a bezier) would otherwise let a greedy pass pair a segment with its neighbour and leave the chain's ends unmatched."""
    pool: dict = {}
    for r in b:
        pool.setdefault((key(r), _exact(r)), []).append(r)
    matched, rest = 0, []
    for r in a:
        cands = pool.get((key(r), _exact(r)))
        if cands:
            cands.pop(); matched += 1
        else:
            rest.append(r)
    loose: dict = {}
    for cs in pool.values():
        for c in cs:
            loose.setdefault(key(c), []).append(c)
    left = []
    for r in rest:
        cands = loose.get(key(r), [])
        hit = next((i for i, c in enumerate(cands) if close(r, c, tol)), None)
        if hit is None:
            left.append(r)
        else:
            cands.pop(hit); matched += 1
    right = [c for cs in loose.values() for c in cs]
    return matched, left, right
