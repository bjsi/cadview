"""5. Inner copper layers and bezier outlines.

A 4-layer board (`Board(layers=4)`) whose outline has one cubic bezier edge, a GND pour on In1.Cu, a hand trace on In2.Cu
between two through vias -> .kicad_pcb -> `kicad-cli pcb drc --save-board` -> `kicad_parse` sees the four copper layers
(table and stackup) and the gr_curve with the same four control points; `kicad-cli pcb export gerbers` writes an In1 / In2
Gerber with the pour / the trace on it; the Edge.Cuts Gerber's polyline of the bezier lies on the build123d edge.  A spline
outline (BSPLINE, several spans) is written as one gr_curve per cubic span.  The 2-layer output keeps F.Cu / B.Cu only.
"""
from __future__ import annotations

import json
import os

import pytest
from build123d import Edge, Face, Vector, Wire

import conftest
import helpers as H
import kicad_parse as kp

TOL = 0.01
POLES = [(-30.0, -10.0), (-40.0, 0.0), (-20.0, 10.0), (-30.0, 20.0)]      # y-up, the DSL's frame
CORNERS = [(-30.0, 20.0), (30.0, 20.0), (30.0, -20.0), (-30.0, -20.0), (-30.0, -10.0)]


def bezier_face() -> Face:
    """a 60 x 40 rectangle whose left side is a cubic bezier"""
    edges = [Edge.make_bezier(*[Vector(x, y, 0) for x, y in POLES])]
    edges += [Edge.make_line(Vector(*a, 0), Vector(*b, 0)) for a, b in zip(CORNERS, CORNERS[1:])]
    return Face(Wire.combine(edges, tol=0.01)[0])


def build_four_layer_board(m):
    b = m.Board(bezier_face(), thickness=1.6, name="four", layers=4)
    soic = m.kicad_footprint("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm")
    r = m.kicad_footprint("Resistor_SMD", "R_0603_1608Metric")
    u1 = b.place(soic, "U1", (0.0, 0.0), value="IC", symbol=("Timer", "NE555D"))
    r1 = b.place(r, "R1", (10.0, 10.0), rot=90, value="10k", symbol=("Device", "R"))
    b.net("GND", ("U1", 4), ("R1", 2))
    b.net("SIG", ("U1", 1), ("R1", 1))
    b.stitch("GND", "U1", 4, (-1, 0))                         # GND pads down to the pours through vias
    b.stitch("GND", "R1", 2, (1, 0))
    b.pour("GND", "In1.Cu")
    b.pour("GND", "bottom")
    p1, p2 = u1.pad_xy(soic.pad(1)), r1.pad_xy(r.pad(1))
    b.via("SIG", (p1[0] - 1.5, p1[1])); b.via("SIG", (p2[0] - 1.5, p2[1]))
    b.trace("SIG", [p1, (p1[0] - 1.5, p1[1])], "top"); b.trace("SIG", [p2, (p2[0] - 1.5, p2[1])], "top")
    b.trace("SIG", [(p1[0] - 1.5, p1[1]), (p2[0] - 1.5, p2[1])], "In2.Cu")     # the SIG link runs on an inner layer
    return b


@pytest.fixture(scope="module")
def four(cadpcb, kicad, outdir):
    d = outdir / "four-layer"; d.mkdir(exist_ok=True)
    b = build_four_layer_board(cadpcb)
    pcb = b.write_kicad(str(d), "four")[0]
    written = open(pcb).read()
    r = kicad.run("pcb", "drc", "--refill-zones", "--save-board", "--format", "json", "--severity-all", "-o", str(d / "drc.json"), pcb)
    with open(d / "drc.json") as f:
        drc = json.load(f)
    g = d / "gerbers"; g.mkdir(exist_ok=True)
    gerbers = kicad.run("pcb", "export", "gerbers", "-o", str(g) + "/", pcb)      # every layer, as tools/pcb/kicad_export.sh does
    step = kicad.run("pcb", "export", "step", "--board-only", "-f", "-o", str(d / "board_only.step"), pcb)
    pick = lambda suffix: next((str(g / n) for n in os.listdir(g) if n.endswith(suffix)), None)
    return dict(board=b, dir=d, pcb=pcb, written=written, drc_rc=r.returncode, drc=drc, gerbers=gerbers, step=step,
                layers={n: pick(s) for n, s in (("F.Cu", "F_Cu.gtl"), ("In1.Cu", "In1_Cu.g1"), ("In2.Cu", "In2_Cu.g2"), ("B.Cu", "B_Cu.gbl"), ("Edge.Cuts", "Edge_Cuts.gm1"))})


def test_four_copper_layers_survive_kicad(four):
    """the layer table and the stackup list F.Cu / In1.Cu / In2.Cu / B.Cu, before and after KiCad re-saves the board"""
    assert kp.read_board(four["pcb"]).copper_layers == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    for text, which in ((four["written"], "written"), (open(four["pcb"]).read(), "re-saved")):
        tree = kp.parse(text)
        assert [str(l[1]) for l in kp.child(tree, "layers")[1:] if str(l[1]).endswith(".Cu")] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], which
        stack = kp.child(kp.child(tree, "setup"), "stackup")
        assert stack, f"{which}: no (stackup ...) in (setup ...)"
        copper = [str(l[1]) for l in kp.children(stack, "layer") if kp.child(l, "type") and kp.child(l, "type")[1] == "copper"]
        assert copper == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], which
        diel = [kp.child(l, "thickness")[1] for l in kp.children(stack, "layer") if str(l[1]).startswith("dielectric")]
        assert len(diel) == 3 and sum(diel) == pytest.approx(1.6 - 4 * 0.035 - 2 * 0.01, abs=1e-6), which
    errors = [v for v in four["drc"]["violations"] if v["severity"] == "error"]
    assert errors == [], [(e["type"], e["description"]) for e in errors]
    assert four["drc"]["unconnected_items"] == []
    conftest.REPORT.append(f"four-layer DRC: {len(four['drc']['violations'])} warnings, 0 errors; board re-saved by kicad-cli with 4 copper layers")


def test_inner_layer_gerbers(four):
    """In1.Cu carries the pour (a region), In2.Cu the trace (a line); F.Cu has the pads only"""
    assert four["gerbers"].returncode == 0, four["gerbers"].stderr
    for name, path in four["layers"].items():
        assert path, f"no Gerber for {name}: {os.listdir(four['dir'] / 'gerbers')}"
    in1, in2, top = (kp.read_copper(four["layers"][l]) for l in ("In1.Cu", "In2.Cu", "F.Cu"))
    assert in1["regions"] >= 1, in1                          # the GND pour, filled by --refill-zones
    assert in2["lines"] == 1 and in2["regions"] == 0, in2    # the SIG link
    assert top["regions"] == 0 and len([f for f in top["flashes"] if f.ref]) == 10, top
    # the four through vias flash on every copper layer
    assert all(len([f for f in L["flashes"] if f.ref == ""]) == 4 for L in (top, in1, in2)), "via flashes on F.Cu / In1.Cu / In2.Cu"


def test_four_layer_step_thickness(four):
    """the stackup sums to the board thickness: kicad-cli's body is the dielectric + inner copper, same as a 2-layer board"""
    from build123d import import_step
    assert four["step"].returncode == 0, four["step"].stderr
    s = import_step(str(four["dir"] / "board_only.step"))
    bb = s.bounding_box(optimal=True)
    assert 1.4 < bb.max.Z - bb.min.Z <= 1.6 + 0.05


def _curves(pcb_path: str) -> list:
    return [e for e in kp.read_board(pcb_path).edge if e.kind == "curve"]


def test_bezier_outline_roundtrip(four):
    """one gr_curve, its four control points the bezier's poles (y flipped); unchanged by KiCad's re-save; rebuilt as the same edge"""
    want = [(x, -y) for x, y in POLES]
    for text, which in ((four["written"], "written"), (open(four["pcb"]).read(), "re-saved")):
        path = str(four["dir"] / f"{which}.kicad_pcb")
        open(path, "w").write(text)
        curves = _curves(path)
        assert len(curves) == 1, which
        assert [tuple(p) for p in curves[0].pts] == pytest.approx(want, abs=1e-6), which
        rec = kp.read_board(path)
        assert [e.kind for e in rec.edge].count("line") == 4, which
        face = H.face_from_edge_cuts(rec.edge)
        bez = [e for e in face.outer_wire().edges() if e.geom_type.name == "BEZIER"]
        assert len(bez) == 1
        assert (bez[0] @ 0).to_tuple()[:2] in (pytest.approx(POLES[0]), pytest.approx(POLES[-1]))
        assert face.area == pytest.approx(bezier_face().area, abs=1e-6)


def test_bezier_gerber_lies_on_the_edge(four):
    """KiCad plots a gr_curve as a polyline: every vertex of it is on the build123d bezier within the Gerber tolerance"""
    bez = next(e for e in bezier_face().outer_wire().edges() if e.geom_type.name == "BEZIER")
    items = [e for e in kp.read_outline(four["layers"]["Edge.Cuts"]) if e[0] == "line"]
    on_curve = [e for e in items if min(abs(e[1] - x) for x in (-30.0, 30.0)) > 1e-6 or min(abs(e[3] - x) for x in (-30.0, 30.0)) > 1e-6]
    assert len(on_curve) > 20, "the bezier should be plotted as many short lines"
    far = [max(bez.distance_to(Vector(x, y, 0)) for x, y in ((e[1], e[2]), (e[3], e[4]))) for e in on_curve]
    assert max(far) < TOL, max(far)
    assert min(v for e in items for v in (e[1], e[3])) < -31.0, "the curve bulges past the rectangle's left side"
    conftest.REPORT.append(f"bezier outline: {len(on_curve)} Gerber segments on the curve, max {max(far):.4f} mm off it")


def test_bezier_keeps_drawn_direction(cadpcb):
    """the gr_curve's control points come out in the order the curve was drawn, whichever way the wire runs through it -
    KiCad's polyline of a bezier depends on the direction, so a board read back and written again plots the same"""
    for poles in (POLES, POLES[::-1]):
        edges = [Edge.make_bezier(*[Vector(x, y, 0) for x, y in poles])]
        edges += [Edge.make_line(Vector(*a, 0), Vector(*b, 0)) for a, b in zip(CORNERS, CORNERS[1:])]
        for face in (Face(Wire.combine(edges, tol=0.01)[0]), Face(Wire.combine(edges[::-1], tol=0.01)[0])):
            tree = kp.parse(cadpcb.Board(face, name="dir").kicad_pcb())
            curves = [c for c in tree if isinstance(c, list) and c and c[0] == "gr_curve"]
            assert len(curves) == 1
            assert [(p[1], -p[2]) for p in kp.child(curves[0], "pts")[1:]] == pytest.approx(poles, abs=1e-6)


def test_spline_outline_is_cubic_spans(cadpcb):
    """a BSPLINE edge (interpolated through 4 points: 3 cubic spans) -> 3 gr_curve items chained end to end, each on the spline"""
    pts = [Vector(0, 0, 0), Vector(5, 8, 0), Vector(12, 3, 0), Vector(20, 10, 0)]
    s = Edge.make_spline(pts)
    corners = [(20, 10), (20, 30), (0, 30), (0, 0)]
    edges = [s] + [Edge.make_line(Vector(*a, 0), Vector(*b, 0)) for a, b in zip(corners, corners[1:])]
    face = Face(Wire.combine(edges, tol=0.01)[0])
    b = cadpcb.Board(face, name="spline")
    tree = kp.parse(b.kicad_pcb())
    curves = [c for c in tree if isinstance(c, list) and c and c[0] == "gr_curve"]
    assert len(curves) == 3, [c[0] for c in tree if isinstance(c, list) and str(c[0]).startswith("gr_")]
    runs = [[(p[1], -p[2]) for p in kp.child(c, "pts")[1:]] for c in curves]       # back to y-up
    assert all(len(r) == 4 for r in runs)
    ends = {tuple(round(v, 6) for v in r[0]) for r in runs} | {tuple(round(v, 6) for v in r[-1]) for r in runs}
    assert (0.0, 0.0) in ends and (20.0, 10.0) in ends
    for r in runs:
        for x, y in r[:1] + r[-1:]:
            assert s.distance_to(Vector(x, y, 0)) < 1e-6
        for t in (0.25, 0.5, 0.75):                                            # the cubic itself follows the spline between its ends
            q = [((1 - t) ** 3 * r[0][i] + 3 * (1 - t) ** 2 * t * r[1][i] + 3 * (1 - t) * t ** 2 * r[2][i] + t ** 3 * r[3][i]) for i in (0, 1)]
            assert s.distance_to(Vector(q[0], q[1], 0)) < 1e-6
    assert not any(isinstance(c, list) and c and c[0] == "gr_arc" for c in tree), "no edge of this face is an arc"


def test_two_layer_output_unchanged(cadpcb):
    b = cadpcb.Board(H.face_rect(20, 10), name="two")
    assert b.layers == 2 and b.copper == ["F.Cu", "B.Cu"]
    tree = kp.parse(b.kicad_pcb())
    assert [str(l[1]) for l in kp.child(tree, "layers")[1:] if str(l[1]).endswith(".Cu")] == ["F.Cu", "B.Cu"]
    stack = kp.child(kp.child(tree, "setup"), "stackup")
    assert [str(l[1]) for l in kp.children(stack, "layer") if str(l[1]).startswith("dielectric")] == ["dielectric 1"]
    assert b.circuit_json()[0]["num_layers"] == 2
    with pytest.raises(ValueError):
        cadpcb.Board(H.face_rect(20, 10), layers=3)
    with pytest.raises(ValueError):
        b.pour("GND", "In1.Cu")
    with pytest.raises(ValueError):
        b.trace("GND", [(0, 0), (1, 1)], "in1")


def test_four_layer_circuit_json_and_jlc(cadpcb, tmp_path):
    b = build_four_layer_board(cadpcb)
    cj = b.circuit_json()
    assert cj[0]["num_layers"] == 4
    layers = {r["layer"] for e in cj if e["type"] == "pcb_trace" for r in e["route"]}
    assert layers == {"top", "inner2"}
    assert b.copper == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    for p in b.parts: p.lcsc = "C1"
    out = b.write_jlc(str(tmp_path))
    assert open(out["cpl.csv"]).read().count("Top") == 2                       # the JLC files do not know about layers
