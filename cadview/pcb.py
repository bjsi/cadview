"""cadview.pcb — a 2-layer PCB laid out from build123d, written out for KiCad, tscircuit and JLCPCB.

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
through-hole pads (rect / roundrect / oval / circle), rotations in multiples of 90 deg, circle holes, polygon cutouts,
rect keepouts, copper pours, hand traces + vias, silkscreen text, 2 layers.  Needs build123d; shapely for outlines
(`pip install cadview[pcb]`); KiCad's footprint + 3D libraries on disk (KICAD_FOOTPRINTS / KICAD_3DMODELS).
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
_MODEL_VAR = re.compile(r"\$\{KICAD\d*_3DMODEL_DIR\}")


# ------------------------------------------------------------------ KiCad footprint reader ----
class Q(str):
    """a quoted string token (vs a bare symbol), so a parsed tree serialises back the way KiCad wrote it"""


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
        else:
            try: cur.append(float(t))
            except ValueError: cur.append(t)
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
        at = _kv(n, "at"); x, y = at[1], -at[2]; rot = at[3] if len(at) > 3 else 0.0
        size = _kv(n, "size"); w, h = size[1], size[2]
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
            w, h = max(xs) - min(xs), max(ys) - min(ys); x += (max(xs) + min(xs)) / 2; y -= (max(ys) + min(ys)) / 2
        if rot % 180 == 90: w, h = h, w
        drill = 0.0
        d = _kv(n, "drill")
        if d: drill = max([v for v in d[1:] if isinstance(v, float)] or [0.0])     # (drill 0.95), (drill oval 1.0 1.8), (drill (offset ..))
        lay = _kv(n, "layers") or []
        layers = tuple(sorted({"top" if l.startswith("F.") else "bottom" for l in lay[1:] if l.endswith(".Cu") or l.startswith("*")} or {"top"}))
        if kind != "smd": layers = ("top", "bottom")
        pads.append(Pad(number, kind, shape, x, y, w, h, drill, layers))
    m = _kv(tree, "model")
    model = _MODEL_VAR.sub(KICAD_3D, m[1]) if m else None
    if m: m[1] = Q(model)                                                          # absolute path: kicad-cli has no ${KICAD10_3DMODEL_DIR} headless
    return Footprint(name, pads, model, lib, tree)


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

    def pad_xy(self, pad: Pad):
        a = math.radians(self.rot); c, s = math.cos(a), math.sin(a)
        return (round(self.x + pad.x * c - pad.y * s, 4), round(self.y + pad.x * s + pad.y * c, 4))


class Board:
    """A 2-layer PCB whose outline / holes / cutouts come from a build123d Face lying in a Z plane."""

    def __init__(self, face: Face, thickness=1.6, name="board", z=0.0):
        self.name, self.thickness, self.z = name, thickness, z
        self.outline = _poly_from_wire(face.outer_wire())
        self.holes, self.cutouts = [], []
        self.edge_wires = [face.outer_wire()]                                   # exact edges for KiCad's Edge.Cuts
        for w in face.inner_wires():
            c = _circle_of(w)
            if c: self.holes.append(c)
            else: self.cutouts.append(_poly_from_wire(w)); self.edge_wires.append(w)
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
    def place(self, fp: Footprint, ref: str, at, rot=0.0, value="", mpn="", center_pads=True, lcsc="", note="", ref_at=None) -> Placed:
        """`at` is where the part's pad-bbox centre goes (KiCad footprints often have their origin on pin 1, e.g. the Pico THT one);
        center_pads=False puts the footprint origin there instead."""
        ox = oy = 0.0
        if center_pads and fp.pads:
            xs, ys = [q.x for q in fp.pads], [q.y for q in fp.pads]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            a = math.radians(rot); ox, oy = -(cx * math.cos(a) - cy * math.sin(a)), -(cx * math.sin(a) + cy * math.cos(a))
        p = Placed(ref, fp, round(at[0] + ox, 4), round(at[1] + oy, 4), rot % 360, value, mpn, lcsc=lcsc, note=note, ref_at=ref_at); self.parts.append(p); return p

    def label(self, text, at, rot=0.0, size=1.0, layer="F.SilkS"):
        """silkscreen text (KiCad only; Circuit JSON gets a pcb_silkscreen_text)"""
        self.labels.append((text, (round(at[0], 4), round(at[1], 4)), rot % 360, size, layer))

    def pour(self, net="GND", layer="B.Cu"):
        """a copper pour over the whole outline on one layer (KiCad zone; filled by `kicad-cli pcb drc --refill-zones --save-board`)"""
        self.pours.append((net, layer))

    def trace(self, net, pts, layer="top", width=None):
        """hand-placed copper: a polyline on one layer (Circuit JSON pcb_trace, so the router sees it as an obstacle; KiCad segments)"""
        self.manual.append(dict(net=net, layer=layer, width=width or self.track_width, pts=[(round(x, 4), round(y, 4)) for x, y in pts]))

    def via(self, net, at):
        self.vias.append((net, (round(at[0], 4), round(at[1], 4))))

    def stitch(self, net, ref, pad_number, toward, length=1.3):
        """a short trace from an SMD pad out to a via (e.g. a top-layer GND pad down to the bottom pour); `toward` = (dx, dy) unit-ish"""
        p = next(p for p in self.parts if p.ref == ref); q = p.fp.pad(pad_number)
        x, y = p.pad_xy(q); n = math.hypot(*toward); dx, dy = toward[0] / n * length, toward[1] / n * length
        self.trace(net, [(x, y), (x + dx, y + dy)], q.layers[0]); self.via(net, (x + dx, y + dy))

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
        cpl = ["Designator,Mid X,Mid Y,Layer,Rotation"]
        for r in rows: cpl.append(f'"{r["ref"]}",{r["at"][0]:.3f}mm,{r["at"][1]:.3f}mm,{"Top" if r["layer"] == "top" else "Bottom"},{r["rot"]:g}')
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
                    num_layers=2, material="fr4", shape="polygon", outline=[dict(x=x, y=y) for x, y in self.outline],
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
                            position=dict(x=p.x, y=p.y, z=self.thickness / 2), rotation=dict(x=0, y=0, z=p.rot), layer=p.layer,
                            **({"model_step_url": "file://" + p.fp.model} if p.fp.model else {})))
            for qi, q in enumerate(p.fp.pads):
                x, y = p.pad_xy(q)
                if q.number:
                    sp, pp = f"source_port_{pi}_{qi}", f"pcb_port_{pi}_{qi}"
                    port_id[(p.ref, q.number)] = sp
                    els.append(dict(type="source_port", source_port_id=sp, source_component_id=sc, name=q.number, port_hints=[q.number],
                                    **({"pin_number": int(q.number)} if q.number.isdigit() else {})))
                    els.append(dict(type="pcb_port", pcb_port_id=pp, source_port_id=sp, pcb_component_id=pc, x=x, y=y, layers=list(q.layers)))
                else:
                    pp = None
                base = dict(pcb_component_id=pc, x=x, y=y, **({"pcb_port_id": pp, "port_hints": [q.number]} if pp else {}))
                if q.kind == "smd":
                    shape = "circle" if q.shape == "circle" else "rect"
                    el = dict(type="pcb_smtpad", pcb_smtpad_id=f"pcb_smtpad_{pi}_{qi}", shape=shape, layer=q.layers[0], **base)
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
                            route=[dict(route_type="wire", x=x, y=y, width=t["width"], layer=t["layer"]) for x, y in t["pts"]]))
        for i, (net, (x, y)) in enumerate(self.vias):
            els.append(dict(type="pcb_via", pcb_via_id=f"pcb_via_manual_{i}", x=x, y=y, outer_diameter=self.via_dims[0], hole_diameter=self.via_dims[1], layers=["top", "bottom"]))
        return els

    def write(self, path):
        with open(path, "w") as f: json.dump(self.circuit_json(), f, indent=0)
        return path

    # --- KiCad project (text an agent can edit, kicad-cli can check and export)
    def kicad_pcb(self, traces=None) -> str:
        """A .kicad_pcb (format 20241229, loads in KiCad 9/10).  KiCad is y-DOWN: panel (x, y) -> (x, -y), angles negated, so
        `kicad-cli pcb export step` lands back in the panel frame.  `traces`: Circuit JSON pcb_trace / pcb_via elements (e.g. from
        export.mjs's routed.circuit.json) written as segments / vias; the nets are embedded, so the GUI shows the ratsnest."""
        import uuid as _uuid
        U = lambda: ["uuid", Q(str(_uuid.uuid4()))]
        Y = lambda y: -y
        stroke = lambda w=0.1: ["stroke", ["width", w], ["type", "default"]]
        net_id = {name: i + 1 for i, name in enumerate(self.nets)}
        pad_net = {}                                                           # (ref, pad) -> net name
        for name, pins in self.nets.items():
            for k in pins: pad_net[k] = name
        root = ["kicad_pcb", ["version", 20241229.0], ["generator", Q("cadview.pcb")], ["generator_version", Q("0.1")],
                ["general", ["thickness", self.thickness], ["legacy_teardrops", "no"]], ["paper", Q("A4")],
                ["layers"] + [[float(i), Q(n), k] for i, n, k in ((0, "F.Cu", "signal"), (31, "B.Cu", "signal"), (34, "B.Paste", "user"), (35, "F.Paste", "user"),
                                                                 (36, "B.SilkS", "user"), (37, "F.SilkS", "user"), (38, "B.Mask", "user"), (39, "F.Mask", "user"),
                                                                 (40, "Dwgs.User", "user"), (41, "Cmts.User", "user"), (44, "Edge.Cuts", "user"), (45, "Margin", "user"),
                                                                 (46, "B.CrtYd", "user"), (47, "F.CrtYd", "user"), (48, "B.Fab", "user"), (49, "F.Fab", "user"))],
                ["setup", ["pad_to_mask_clearance", 0.0], ["allow_soldermask_bridges_in_footprints", "no"]],
                ["net", 0.0, Q("")]] + [["net", float(i), Q(n)] for n, i in net_id.items()]
        # footprints: the library tree, re-rooted at the part's position with nets on the pads
        import copy
        for p in self.parts:
            fp = copy.deepcopy(p.fp.tree)
            fp[1] = Q(f"{p.fp.lib}:{p.fp.name}")
            body = [n for n in fp[2:] if not (isinstance(n, list) and n[0] in ("version", "generator", "generator_version"))]
            # KiCad angles are CCW as seen on its y-down screen, which is exactly a CCW angle in the y-up frame after the y flip:
            # KiCad abs = Rk(A)(px, -py) + (cx, -cy); negating y gives R(A)(px, py) + c, so A = rot (verified by DRC: -rot leaves every track dangling)
            a = p.rot % 360
            out = [fp[0], fp[1], ["layer", Q("F.Cu")], U(), ["at", p.x, Y(p.y), a]]
            for n in body:
                if not isinstance(n, list): out.append(n); continue
                if n[0] == "layer": continue
                if n[0] == "property" and n[1] in ("Reference", "Value"): n[2] = Q(p.ref if n[1] == "Reference" else p.value)
                if n[0] in ("property", "fp_text"):                                   # text angles are absolute in the file: add the part's
                    at = _kv(n, "at")
                    if at: at[3:] = [((at[3] if len(at) > 3 else 0.0) + a) % 360]
                    if n[0] == "property" and n[1] == "Reference" and p.ref_at and at: at[1:3] = [p.ref_at[0], -p.ref_at[1]]
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
        # board edge + cutouts from the exact CAD edges
        for w in self.edge_wires:
            for e in w.order_edges():
                p0, p1 = e @ 0, e @ 1
                if e.geom_type == GeomType.LINE:
                    root.append(["gr_line", ["start", round(p0.X, 4), Y(round(p0.Y, 4))], ["end", round(p1.X, 4), Y(round(p1.Y, 4))], stroke(), ["layer", Q("Edge.Cuts")], U()])
                elif e.geom_type == GeomType.CIRCLE and e.is_closed:
                    c = e.arc_center
                    root.append(["gr_circle", ["center", round(c.X, 4), Y(round(c.Y, 4))], ["end", round(c.X + e.radius, 4), Y(round(c.Y, 4))], stroke(), ["fill", "none"], ["layer", Q("Edge.Cuts")], U()])
                else:
                    pm = e @ 0.5
                    root.append(["gr_arc", ["start", round(p0.X, 4), Y(round(p0.Y, 4))], ["mid", round(pm.X, 4), Y(round(pm.Y, 4))], ["end", round(p1.X, 4), Y(round(p1.Y, 4))], stroke(), ["layer", Q("Edge.Cuts")], U()])
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
            root.append(["zone", ["net", float(net_id[net])], ["net_name", Q(net)], ["layer", Q(layer)], U(), ["name", Q(f"{net} pour {layer}")], ["hatch", "edge", 0.5],
                         ["priority", 0.0], ["connect_pads", ["clearance", 0.3]], ["min_thickness", 0.25], ["filled_areas_thickness", "no"],
                         ["fill", "yes", ["thermal_gap", 0.4], ["thermal_bridge_width", 0.4], ["island_removal_mode", 0.0]],
                         ["polygon", ["pts"] + [["xy", x, Y(y)] for x, y in self.outline]]])
        # hand copper
        for t in self.manual:
            nid = float(net_id.get(t["net"], 0))
            for (x0, y0), (x1, y1) in zip(t["pts"], t["pts"][1:]):
                root.append(["segment", ["start", x0, Y(y0)], ["end", x1, Y(y1)], ["width", t["width"]], ["layer", Q("F.Cu" if t["layer"] == "top" else "B.Cu")], ["net", nid], U()])
        for net, (x, y) in self.vias:
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
                                     ["layer", Q("F.Cu" if r0["layer"] == "top" else "B.Cu")], ["net", nid], U()])
                for r in pts:
                    if r.get("route_type") == "via" and "x" in r:
                        root.append(["via", ["at", round(r["x"], 4), Y(round(r["y"], 4))], ["size", self.via_dims[0]], ["drill", self.via_dims[1]], ["layers", Q("F.Cu"), Q("B.Cu")], ["net", nid], U()])
        root.append(["embedded_fonts", "no"])
        return _ser(root) + "\n"

    def kicad_pro(self, name) -> str:
        rules = dict(self.rules, min_via_drill=self.via_dims[1] if False else self.rules.get("min_through_hole_diameter", 0.3))
        sev = {"lib_footprint_issues": "warning", "lib_footprint_mismatch": "warning", "silk_over_copper": "error", "courtyards_overlap": "error",
               "npth_inside_courtyard": "ignore", "holes_co_located": "warning", "track_dangling": "error", "unconnected_items": "error",
               "isolated_copper": "warning", "footprint_type_mismatch": "ignore", "missing_courtyard": "ignore", "solder_mask_bridge": "error"}
        return json.dumps({"meta": {"filename": f"{name}.kicad_pro", "version": 1},
                           "board": {"design_settings": {"rules": rules, "rule_severities": sev,
                                                         "track_widths": [0.0, self.track_width, 0.5], "via_dimensions": [{"diameter": 0.0, "drill": 0.0}, {"diameter": self.via_dims[0], "drill": self.via_dims[1]}]}},
                           "boards": [], "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []}, "text_variables": {}}, indent=2)

    def netlist(self, name) -> str:
        """KiCad netlist (`File > Import Netlist` in pcbnew): components + nets, so the GUI path works without a schematic."""
        comps = [["comp", ["ref", Q(p.ref)], ["value", Q(p.value)], ["footprint", Q(f"{p.fp.lib}:{p.fp.name}")]] for p in self.parts]
        nets = [["net", ["code", Q(str(i + 1))], ["name", Q(n)]] + [["node", ["ref", Q(r)], ["pin", Q(pad)]] for r, pad in pins] for i, (n, pins) in enumerate(self.nets.items())]
        return _ser(["export", ["version", Q("E")], ["design", ["source", Q(f"{name}.py")], ["tool", Q("cadview.pcb")]], ["components"] + comps, ["nets"] + nets]) + "\n"

    def write_kicad(self, outdir, name, traces=None):
        paths = []
        for ext, txt in ((".kicad_pcb", self.kicad_pcb(traces)), (".kicad_pro", self.kicad_pro(name)), (".net", self.netlist(name))):
            p = os.path.join(outdir, name + ext)
            with open(p, "w") as f: f.write(txt)
            paths.append(p)
        return paths

    # --- build123d
    def solid(self, color=None, models=True, routed=None) -> list:
        """The board as build123d parts in the panel frame: FR4 slab (outline, holes, cutouts) at self.z, plus each part's KiCad
        STEP model on the top face.  `routed`: a circuit.json path with pcb_trace elements -> top-layer copper drawn as thin strips."""
        if color is None:
            color = Color(0.1, 0.4, 0.2)
        sk = Polygon(*self.outline, align=None)
        for x, y, d in self.holes: sk -= Pos(x, y) * Circle(d / 2)
        for poly in self.cutouts: sk -= Polygon(*poly, align=None)
        slab = Pos(0, 0, self.z) * extrude(sk, self.thickness)
        slab.label, slab.color = f"{self.name} FR4", color
        out = [slab]
        cache = {}
        for p in self.parts:
            if models and p.fp.model and os.path.exists(p.fp.model):
                if p.fp.model not in cache: cache[p.fp.model] = import_step(p.fp.model)
                m = Pos(p.x, p.y, self.z + self.thickness) * Rot(0, 0, p.rot) * cache[p.fp.model]
                m.label = f"{p.ref} {p.fp.name}"; out.append(m)
            for q in p.fp.pads:
                x, y = p.pad_xy(q)
                pad = Pos(x, y, self.z + self.thickness) * (Cylinder(q.w / 2, 0.05, align=(Align.CENTER, Align.CENTER, Align.MIN)) if q.shape == "circle"
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
