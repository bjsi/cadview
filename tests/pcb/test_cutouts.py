"""7. Inner wires: NPTH drills vs Edge.Cuts cutouts.

A Face with a circular inner wire and a slot-shaped one.  By default (`inner_circles="npth"`) the circle is a non-plated
drill - one `openworkshop:NPTH` footprint, no `gr_circle` - exactly what every board written before `inner_circles` existed got
(the ordered nose-poke board's M2.5 clearance holes are circular inner wires of its Face); with `"cutout"` it is a
`gr_circle` on Edge.Cuts and no drill.  The slot is an Edge.Cuts cutout either way: its arcs and lines chain into a closed
loop that the independent reader turns back into one inner wire of the same area.  `Board.hole()` adds an NPTH explicitly.
"""
from __future__ import annotations

import pytest
from build123d import Circle, Pos, Rectangle, SlotCenterToCenter

import helpers as H
import kicad_parse as kp


def _face():
    return (Rectangle(40, 30) - Pos(10, 5) * Circle(1.6) - Pos(-10, 0) * SlotCenterToCenter(6, 2)).faces()[0]


def _write(b, path):
    open(path, "w").write(b.kicad_pcb())
    tree = kp.parse(open(path).read())
    npth = [c for c in tree if isinstance(c, list) and c and c[0] == "footprint" and str(c[1]).startswith("openworkshop:NPTH")]
    return kp.read_board(path), npth


@pytest.mark.parametrize("mode,holes,circles", [("npth", 1, 0), ("cutout", 0, 1)])
def test_circle_inner_wire(cadpcb, tmp_path, mode, holes, circles):
    face = _face()
    b = cadpcb.Board(face, name="cut", inner_circles=mode)
    assert len(b.holes) == holes and len(b.circle_cutouts) == circles
    rec, npth = _write(b, str(tmp_path / f"{mode}.kicad_pcb"))
    assert len(npth) == holes
    assert [e.kind for e in rec.edge].count("circle") == circles
    if holes:
        assert b.holes[0] == pytest.approx((10.0, 5.0, 3.2), abs=1e-4)
        at = kp.child(npth[0], "at")
        assert (at[1], -at[2]) == pytest.approx((10.0, 5.0), abs=1e-4)
    # the slot: 2 arcs + 2 lines, a closed chain the reader rebuilds as one inner wire; with the circle on Edge.Cuts, two
    again = H.face_from_edge_cuts(rec.edge)
    assert len(again.inner_wires()) == 1 + circles
    assert [e.kind for e in rec.edge].count("arc") == 2
    assert again.area == pytest.approx(face.area + (3.14159265 * 1.6 ** 2 if holes else 0.0), abs=1e-3)


def test_explicit_hole(cadpcb, tmp_path):
    b = cadpcb.Board(H.face_rect(20, 10), name="h")
    b.hole((3.0, -2.0), 2.2)
    assert b.holes == [(3.0, -2.0, 2.2)]
    rec, npth = _write(b, str(tmp_path / "h.kicad_pcb"))
    assert len(npth) == 1 and kp.child(npth[0], "at")[1:3] == [3.0, 2.0]
    assert [e.kind for e in rec.edge] == ["line"] * 4


def test_bad_inner_circles_value(cadpcb):
    with pytest.raises(ValueError):
        cadpcb.Board(H.face_rect(20, 10), inner_circles="drill")
