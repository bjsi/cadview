"""2. Round trip through KiCad.

A small board laid out with the DSL (rounded rectangle = 4 lines + 4 arcs, 2 NPTH mounting holes, a rectangular
cutout, 3 parts, 2 nets, one hand trace, a GND pour) -> .kicad_pcb / .kicad_pro -> kicad-cli:
  - `pcb drc` parses it with zero error-severity violations and zero unconnected items,
  - `pcb export gerbers` / `drill` / `step` succeed,
  - the board-only STEP's XY bounding box equals the build123d Face's within 0.05 mm,
  - the netlist KiCad exports from the board (IPC-D-356) equals Board.nets exactly,
  - the Edge.Cuts Gerber carries the outline / cutout / arcs, the NPTH drill file the two holes at the CAD positions.
"""
from __future__ import annotations

import json
import os

import pytest

import conftest
import helpers as H
import kicad_parse as kp

TOL_STEP = 0.05
TOL_GERB = 0.01


@pytest.fixture(scope="module")
def rt(cadpcb, kicad, outdir):
    d = outdir / "roundtrip"; d.mkdir(exist_ok=True)
    b = H.build_roundtrip_board(cadpcb)
    paths = b.write_kicad(str(d), "roundtrip")                 # .kicad_pcb / .kicad_sch / .kicad_pro / .net
    pcb = paths[0]
    out = dict(board=b, dir=d, pcb=pcb)
    r = kicad.run("pcb", "drc", "--refill-zones", "--save-board", "--format", "json", "--severity-all",
                  "-o", str(d / "drc.json"), pcb)
    out["drc_rc"] = r.returncode
    with open(d / "drc.json") as f:
        out["drc"] = json.load(f)
    g = d / "gerbers"; g.mkdir(exist_ok=True)
    out["gerbers"] = kicad.run("pcb", "export", "gerbers", "-o", str(g) + "/", pcb)
    out["drill"] = kicad.run("pcb", "export", "drill", "--excellon-separate-th", "-o", str(g) + "/", pcb)
    out["d356"] = kicad.run("pcb", "export", "ipcd356", "-o", str(d / "roundtrip.d356"), pcb)
    out["step_board"] = kicad.run("pcb", "export", "step", "--board-only", "-f", "-o", str(d / "board_only.step"), pcb)
    out["step_full"] = kicad.run("pcb", "export", "step", "--subst-models", "--include-pads", "--include-tracks", "-f",
                                 "-o", str(d / "board.step"), pcb)
    out["gdir"] = g
    return out


def test_drc_zero_errors_zero_unconnected(rt):
    v = rt["drc"]["violations"]
    errors = [x for x in v if x["severity"] == "error"]
    warnings = [x for x in v if x["severity"] != "error"]
    unconnected = rt["drc"]["unconnected_items"]
    conftest.REPORT.append(f"roundtrip DRC: {len(errors)} errors, {len(warnings)} warnings "
                           f"({sorted({w['type'] for w in warnings})}), {len(unconnected)} unconnected")
    assert errors == [], [(e["type"], e["description"]) for e in errors]
    assert unconnected == [], [(u["type"], u["description"]) for u in unconnected]
    # the only warnings are the headless lib-table ones (no fp-lib-table in a bare kicad-cli run)
    assert {w["type"] for w in warnings} <= {"lib_footprint_issues"}, sorted({(w["type"], w["description"]) for w in warnings})


def test_exports_succeed(rt):
    for k in ("gerbers", "drill", "d356", "step_board", "step_full"):
        r = rt[k]
        assert r.returncode == 0, f"{k}: {r.stdout}\n{r.stderr}"
    g = rt["gdir"]
    names = os.listdir(g)
    for suffix in ("F_Cu.gtl", "B_Cu.gbl", "Edge_Cuts.gm1", "PTH.drl", "NPTH.drl", "F_Mask.gts", "F_SilkS.gto" if False else "F_Silkscreen.gto"):
        assert any(n.endswith(suffix) for n in names), (suffix, names)
    assert os.path.getsize(rt["dir"] / "board_only.step") > 1000
    assert os.path.getsize(rt["dir"] / "board.step") > os.path.getsize(rt["dir"] / "board_only.step"), "models missing from the full STEP"


def test_step_bbox_equals_face(rt):
    from build123d import import_step
    b = rt["board"]
    face = H.roundtrip_face()
    fb = face.bounding_box()
    s = import_step(str(rt["dir"] / "board_only.step"))
    sb = s.bounding_box(optimal=True)
    conftest.REPORT.append(f"roundtrip STEP bbox x[{sb.min.X:.3f},{sb.max.X:.3f}] y[{sb.min.Y:.3f},{sb.max.Y:.3f}] "
                           f"z[{sb.min.Z:.3f},{sb.max.Z:.3f}] vs face x[{fb.min.X:.3f},{fb.max.X:.3f}] y[{fb.min.Y:.3f},{fb.max.Y:.3f}]")
    assert (sb.min.X, sb.min.Y, sb.max.X, sb.max.Y) == pytest.approx((fb.min.X, fb.min.Y, fb.max.X, fb.max.Y), abs=TOL_STEP)
    assert (b.bbox[0], b.bbox[1], b.bbox[2], b.bbox[3]) == pytest.approx((fb.min.X, fb.min.Y, fb.max.X, fb.max.Y), abs=TOL_STEP)
    # KiCad's board body is the dielectric only: thickness minus 2 x 0.035 copper and 2 x 0.01 mask of the default stackup
    assert sb.min.Z == pytest.approx(0.0, abs=TOL_STEP)
    assert 1.4 < sb.max.Z - sb.min.Z <= b.thickness + TOL_STEP
    # the holes and the cutout are in the solid: its volume is less than the full plate's
    assert s.volume < face.area * (sb.max.Z - sb.min.Z) + 1e-3
    assert s.volume == pytest.approx(face.area * (sb.max.Z - sb.min.Z), rel=0.01)


def test_pcb_netlist_equals_board_nets(rt):
    b = rt["board"]
    d356 = kp.read_ipcd356(str(rt["dir"] / "roundtrip.d356"))
    want = {name: {(r, p) for r, p in pins} for name, pins in b.nets.items()}
    assert d356 == want, (d356, want)
    # and KiCad's re-saved board carries the same net on every pad
    rec = kp.read_board(rt["pcb"])
    pad_nets = {k: v for k, v in rec.pad_nets().items() if any(v)}
    assert {k: v[0] for k, v in pad_nets.items()} == {(r, p): n for n, pins in b.nets.items() for r, p in pins}
    conftest.REPORT.append(f"roundtrip IPC-D-356 netlist == Board.nets: {sum(len(v) for v in want.values())} pins in {len(want)} nets")


def test_edge_cuts_and_drills(rt):
    gd = rt["gdir"]
    edge = kp.read_outline(next(str(gd / n) for n in os.listdir(gd) if n.endswith("Edge_Cuts.gm1")))
    lines = [e for e in edge if e[0] == "line"]
    arcs = [e for e in edge if e[0] == "arc"]
    assert len(lines) == 8 and len(arcs) == 4, (len(lines), len(arcs))
    s = H.ROUNDTRIP
    xs = [v for e in lines + arcs for v in (e[1], e[3])]
    ys = [v for e in lines + arcs for v in (e[2], e[4])]
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((-s["w"] / 2, s["w"] / 2, -s["h"] / 2, s["h"] / 2), abs=TOL_GERB)
    for a in arcs:   # each corner arc is centred r inside the corner
        cx, cy = a[5], a[6]
        assert abs(abs(cx) - (s["w"] / 2 - s["r"])) < TOL_GERB and abs(abs(cy) - (s["h"] / 2 - s["r"])) < TOL_GERB, a
    c = s["cutout"]
    cut = [l for l in lines if abs(l[1] - (c["at"][0] - c["w"] / 2)) < 1 or abs(l[3] - (c["at"][0] + c["w"] / 2)) < 1]
    assert len(cut) == 4, cut
    npth = kp.read_drills(next(str(gd / n) for n in os.listdir(gd) if n.endswith("NPTH.drl")))
    want = [("hole", x, y, d) for (x, y), d in s["holes"]]
    matched, left, right = kp.match_multisets(want, npth, TOL_GERB)
    assert not left and not right, (left, right)
    pth = kp.read_drills(next(str(gd / n) for n in os.listdir(gd) if n.endswith("PTH.drl")))
    assert len(pth) == 2, pth                       # J1's two pins are the only plated holes
    conftest.REPORT.append(f"roundtrip Edge.Cuts: {len(lines)} lines + {len(arcs)} arcs, NPTH {len(npth)}, PTH {len(pth)}")
