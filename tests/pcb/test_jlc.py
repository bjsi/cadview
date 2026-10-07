"""4. JLCPCB assembly outputs: bom.csv / cpl.csv / bom_full.csv.

A fixture board with known answers checks the exact column order, the grouping of identical parts into one BOM
row, which parts are assembled (an LCSC number) versus listed only (bom_full.csv), the `bom_only` extras, the
`Mid X/Mid Y` convention (pad-bbox centre, mm, y up) and the rotation convention: KiCad's CCW degrees, normalised
to 0..360, equal to what `kicad-cli pcb export pos` writes for the same board.
"""
from __future__ import annotations

import csv
import os

import pytest

import conftest
import helpers as H


@pytest.fixture(scope="module")
def jlc(cadpcb, outdir):
    m = cadpcb
    d = outdir / "jlc"; d.mkdir(exist_ok=True)
    b = m.Board(H.face_rect(50, 40, 25, 20), thickness=1.6, name="jlc", z=0.0)
    r = m.kicad_footprint("Resistor_SMD", "R_0603_1608Metric")
    c = m.kicad_footprint("Capacitor_SMD", "C_0603_1608Metric")
    soic = m.kicad_footprint("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm")
    j = m.kicad_footprint("Connector_JST", "JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical")
    b.place(r, "R1", (10, 20), rot=90, value="10k", lcsc="C25804", mpn="0603WAF1002T5E")
    b.place(r, "R2", (10, 25), rot=0, value="10k", lcsc="C25804", mpn="0603WAF1002T5E")
    b.place(c, "C1", (20, 20), rot=-90, value="100n", lcsc="C14663")              # -90 -> 270
    b.place(soic, "U1", (30, 20), rot=180, value="NE555", lcsc="C7593", note="extended")
    b.place(j, "J1", (40, 20), rot=0, value="XH2", mpn="B2B-XH-A")                # no LCSC: not assembled
    b.bom_only("SW1", "SW", "SW_fp", "TS-1187A", "C318884", (5, 5), rot=0, note="on J1's pads")
    b.bom_only("W1", "lead 200mm", "", "", "", (0, 0), assemble=False)
    files = b.write_jlc(str(d))
    read = lambda p: open(p).read().splitlines()
    return dict(board=b, dir=d, bom=read(files["bom.csv"]), cpl=read(files["cpl.csv"]), full=read(files["bom_full.csv"]))


def test_bom_columns_and_grouping(jlc):
    assert jlc["bom"] == [
        "Comment,Designator,Footprint,LCSC Part #",
        '"10k","R1,R2","R_0603_1608Metric","C25804"',
        '"100n","C1","C_0603_1608Metric","C14663"',
        '"NE555","U1","SOIC-8_3.9x4.9mm_P1.27mm","C7593"',
        '"SW","SW1","SW_fp","C318884"',
    ]


def test_cpl_columns_positions_rotations(jlc):
    assert jlc["cpl"] == [
        "Designator,Mid X,Mid Y,Layer,Rotation",
        '"R1",10.000mm,20.000mm,Top,90',
        '"R2",10.000mm,25.000mm,Top,0',
        '"C1",20.000mm,20.000mm,Top,270',
        '"U1",30.000mm,20.000mm,Top,180',
        '"SW1",5.000mm,5.000mm,Top,0',
    ]
    rows = list(csv.DictReader(jlc["cpl"]))
    assert [r["Designator"] for r in rows] == ["R1", "R2", "C1", "U1", "SW1"]
    assert all(r["Layer"] == "Top" for r in rows)
    assert all(r["Mid X"].endswith("mm") and r["Mid Y"].endswith("mm") for r in rows)


def test_bom_full_lists_everything(jlc):
    assert jlc["full"][0] == "ref,value,footprint,mpn,lcsc,note"
    refs = [l.split(",")[0].strip('"') for l in jlc["full"][1:]]
    assert refs == ["R1", "R2", "C1", "U1", "J1", "SW1", "W1"]
    assert '"J1","XH2","Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical","B2B-XH-A","",""' in jlc["full"]
    assert '"U1","NE555","Package_SO:SOIC-8_3.9x4.9mm_P1.27mm","","C7593","extended"' in jlc["full"]
    assert '"W1","lead 200mm","","","",""' in jlc["full"]


def test_mid_is_pad_bbox_centre_not_origin(jlc, cadpcb):
    """the JST XH footprint's origin is pin 1; `place()` puts the pad-bbox centre at `at`, and the CPL would report
    that centre (JLC wants the part centre)."""
    b = jlc["board"]
    j1 = next(p for p in b.parts if p.ref == "J1")
    xs = [j1.pad_xy(q)[0] for q in j1.fp.pads]; ys = [j1.pad_xy(q)[1] for q in j1.fp.pads]
    assert ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2) == pytest.approx((40, 20), abs=1e-6)
    assert (j1.x, j1.y) != (40, 20)                   # the footprint origin sits on pin 1


def test_rotation_matches_kicad_pos_file(jlc, kicad, cadpcb):
    """the CPL rotation is KiCad's own (CCW, 0..360): `kicad-cli pcb export pos` on the same board agrees on every
    part, and on the position for every footprint whose origin is its pad centre"""
    b, d = jlc["board"], jlc["dir"]
    pcb = H.write_pcb(b, str(d / "jlc.kicad_pcb"))
    kicad.ok("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "-o", str(d / "pos.csv"), pcb)
    pos = {r["Ref"]: r for r in csv.DictReader(open(d / "pos.csv"))}
    cpl = {r["Designator"]: r for r in csv.DictReader(jlc["cpl"])}
    assert set(pos) == {"R1", "R2", "C1", "U1", "J1"}
    for ref, r in cpl.items():
        if ref not in pos:
            continue                                    # bom_only extras have no footprint
        assert float(pos[ref]["Rot"]) % 360 == pytest.approx(float(r["Rotation"])), ref
        assert pos[ref]["Side"] == "top"
        if ref != "J1":
            assert (float(pos[ref]["PosX"]), float(pos[ref]["PosY"])) == pytest.approx((float(r["Mid X"][:-2]), float(r["Mid Y"][:-2])), abs=1e-3), ref
    j1 = next(p for p in b.parts if p.ref == "J1")
    assert (float(pos["J1"]["PosX"]), float(pos["J1"]["PosY"])) == pytest.approx((j1.x, j1.y), abs=1e-3)
    conftest.REPORT.append("jlc: cpl rotations == kicad-cli pos rotations for R1/R2/C1/U1/J1 (90, 0, 270, 180, 0); Mid X/Y == pos X/Y for the centred footprints")
