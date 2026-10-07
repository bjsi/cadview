"""5. Bottom-side parts.

A part placed with `layer="bottom"` must come out the way KiCad stores a footprint flipped to the back, and KiCad itself
must then put the copper where the DSL says.  Four footprints (SOIC-8, 0603, JST XH - origin on pin 1 -, the Pico SMD
with offset / custom / paste-only pads) go on the bottom at 0 / 90 / 37 / 180 / 270 degrees, each next to a TOP twin at
the NEGATED angle: turning a top part over about its x axis is exactly what KiCad's flip does (FOOTPRINT::Flip negates the
orientation, mirrors y), so the bottom part's Gerber flashes must be the twin's flashes mirrored about the part's y, on the
other copper layer - an oracle that uses nothing of the DSL's own mirror rules.

(a) write -> `kicad-cli pcb drc --save-board` -> `kicad_parse`: `(layer "B.Cu")`, `(at x -y rot)`, every pad's stored
    position / angle / offset / layers / primitives are the library's mirrored the documented way, and KiCad's rendering
    rule (`kicad_parse.pad_abs`, no mirroring of its own) lands on `Placed.pad_xy()`.
(b) `kicad-cli pcb export gerbers`: the bottom part's flashes == the top twin's flashes mirrored, same size, on the other
    layer; SMD pads of a bottom part flash on B.Cu only.
(c) `kicad-cli pcb export pos`: Side = bottom, the same rotation and X/Y as the DSL's JLC CPL (`Layer` = Bottom).
(d) Circuit JSON: pads and ports of a bottom part on the bottom layer; `solid()`: the STEP model and pads under the board.
"""
from __future__ import annotations

import csv
import math
import os

import pytest

import conftest
import helpers as H
import kicad_parse as kp

TOL = 1e-6
GERB_TOL = 0.01
FOOTPRINTS = [
    ("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm"),
    ("Resistor_SMD", "R_0603_1608Metric"),
    ("Connector_JST", "JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical"),      # THT, origin on pin 1
    ("Module", "RaspberryPi_Pico_SMD"),                               # drill offsets, rotated custom pads, paste-only pads
]
ROTS = [0, 90, 37, 180, 270]
PITCH = (40.0, 64.0)


@pytest.fixture(scope="module")
def board(cadpcb, kicad, outdir):
    m = cadpcb
    d = outdir / "bottom"; d.mkdir(exist_ok=True)
    w, h = PITCH[0] * (len(FOOTPRINTS) * 2 + 1), PITCH[1] * (len(ROTS) + 1)
    b = m.Board(H.face_rect(w, h, w / 2, h / 2), thickness=1.6, name="bottom", z=0.0)
    pairs = []                                                        # (bottom Placed, top twin Placed, library FootprintRec)
    for i, (lib, name) in enumerate(FOOTPRINTS):
        fp = m.kicad_footprint(lib, name)
        ref = kp.read_kicad_mod(H.lib_path(m, lib, name))
        for j, rot in enumerate(ROTS):
            x, y = PITCH[0] * (2 * i + 1), PITCH[1] * (j + 1)
            bot = b.place(fp, f"B{i + 1}R{j}", (x, y), rot=rot, center_pads=False, layer="bottom", lcsc="C1")
            top = b.place(fp, f"T{i + 1}R{j}", (x + PITCH[0], y), rot=-rot, center_pads=False, lcsc="C1")
            pairs.append((bot, top, ref))
    b.net("N1", ("B1R0", 1), ("T1R0", 1))
    pcb = H.write_pcb(b, str(d / "bottom.kicad_pcb"))
    H.write_pro(b, str(d / "bottom.kicad_pro"), "bottom")
    r = kicad.run("pcb", "drc", "--save-board", "--format", "json", "--severity-all", "-o", str(d / "drc.json"), pcb)
    assert r.returncode in (0, 5), r.stdout + r.stderr           # 5 = DRC violations, still re-saved
    rec = kp.read_board(pcb)
    g = d / "gerbers"; g.mkdir(exist_ok=True)
    kicad.ok("pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu", "-o", str(g) + "/", pcb)
    files = {f: str(g / f) for f in os.listdir(g)}
    fl = {"top": kp.read_copper(next(v for k, v in files.items() if k.endswith("F_Cu.gtl")))["flashes"],
          "bottom": kp.read_copper(next(v for k, v in files.items() if k.endswith("B_Cu.gbl")))["flashes"]}
    kicad.ok("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "-o", str(d / "pos.csv"), pcb)
    pos = {r["Ref"]: r for r in csv.DictReader(open(d / "pos.csv"))}
    return dict(board=b, pairs=pairs, rec=rec, flashes=fl, pos=pos, dir=d)


def _pair_ids():
    return [f"{n}@{r}" for _, n in FOOTPRINTS for r in ROTS]


@pytest.fixture(params=range(len(FOOTPRINTS) * len(ROTS)), ids=_pair_ids())
def pair(request, board):
    return board["pairs"][request.param]


# ---------------------------------------------------------------------------------------------- (a) ----
def test_reread_is_kicads_flipped_footprint(pair, board):
    """after KiCad re-saves it: B.Cu, (at x -y rot), and every pad stored as FOOTPRINT::Flip stores it"""
    bot, top, lib = pair
    fp = next(f for f in board["rec"].footprints if f.ref == bot.ref)
    assert fp.layer == "B.Cu"
    assert (fp.x, fp.y) == pytest.approx((bot.x, -bot.y), abs=TOL)
    assert fp.rot % 360 == pytest.approx(bot.rot % 360, abs=1e-6)
    assert len(fp.pads) == len(lib.pads) > 0
    for k, l in zip(fp.pads, lib.pads):
        where = f"{bot.ref} pad {l.number!r}"
        assert (k.number, k.kind, k.shape) == (l.number, l.kind, l.shape), where
        assert (k.x, k.y) == pytest.approx((l.x, -l.y), abs=TOL), f"{where}: stored position (y mirrored)"
        assert _ang_eq(k.rot, bot.rot - l.rot), f"{where}: stored angle {k.rot} should be -lib {l.rot} + rot {bot.rot}"
        assert (k.w, k.h) == pytest.approx((l.w, l.h), abs=TOL), where
        assert k.offset == pytest.approx((l.offset[0], -l.offset[1]), abs=TOL), f"{where}: drill offset y mirrored"
        assert k.layers == tuple(_flip(x) for x in l.layers), f"{where}: layers {k.layers} vs {l.layers}"
        if l.prim_bbox:
            x0, y0, x1, y1 = l.prim_bbox
            assert k.prim_bbox == pytest.approx((x0, -y1, x1, -y0), abs=TOL), f"{where}: primitives y mirrored"
        else:
            assert k.prim_bbox is None, where
    # KiCad's rendering rule for a board pad (footprint origin + R(angle) * stored local, no mirroring) == Placed.pad_xy()
    # for the plain pads (pad_xy() includes a drill offset / primitive centre, pad_abs() is the pad position: the Gerber test covers those)
    for k, q, l in zip(fp.pads, bot.fp.pads, lib.pads):
        if not H.pad_is_plain(l): continue
        ax, ay = kp.pad_abs(fp, k)
        assert (ax, -ay) == pytest.approx(bot.pad_xy(q), abs=1e-4), f"{bot.ref} pad {q.number!r}: KiCad {(ax, -ay)} vs pad_xy {bot.pad_xy(q)}"


def _ang_eq(a: float, b: float) -> bool:
    return abs(((a - b + 180) % 360) - 180) < 1e-6


def _flip(layer: str) -> str:
    if layer.startswith("F."): return "B." + layer[2:]
    if layer.startswith("B."): return "F." + layer[2:]
    return layer


# ---------------------------------------------------------------------------------------------- (b) ----
def test_gerber_flashes_are_the_top_twin_turned_over(pair, board):
    """the Gerber copper of the bottom part == the top twin's (placed at -rot) mirrored about the part's y, layer swapped"""
    bot, top, lib = pair
    fl = board["flashes"]
    n = 0
    for layer, other in (("bottom", "top"), ("top", "bottom")):
        got = sorted((f.pad, f.cx, f.cy, f.bw, f.bh) for f in fl[layer] if f.ref == bot.ref)
        want = sorted((f.pad, f.cx - (top.x - bot.x), 2 * top.y - f.cy, f.bw, f.bh) for f in fl[other] if f.ref == top.ref)
        matched, left, right = kp.match_multisets(want, got, GERB_TOL, key=lambda r: r[0])
        assert not left and not right, (f"{bot.ref} {layer}: {matched} match; twin-mirrored without a flash: {left[:4]}; "
                                        f"flashes the twin does not explain: {right[:4]}")
        n += matched
    smd = [q for q in bot.fp.pads if q.kind == "smd" and q.layers == ("top",)]
    if smd:
        assert not [f for f in fl["top"] if f.ref == bot.ref and any(f.pad == q.number for q in smd)], f"{bot.ref}: SMD copper on F.Cu"
    assert n == sum(len(p.pad_layers(q)) for q in bot.fp.pads for p in [bot] if q.layers)
    # and every flash sits at pad_xy() with the DSL's size (plain pads: the rest are proven by their twins above).  Off the
    # 90 deg grid KiCad flashes a rotated macro aperture whose bounding box gerbonara only approximates: the flash point then.
    for q, l in zip(bot.fp.pads, lib.pads):
        if not H.pad_is_plain(l) or not q.layers or not q.number: continue
        f = [f for f in fl[bot.pad_layers(q)[0]] if f.ref == bot.ref and f.pad == q.number]
        assert len(f) == 1, (bot.ref, q.number, f)
        if bot.rot % 90 == 0:
            assert (f[0].cx, f[0].cy) == pytest.approx(bot.pad_xy(q), abs=GERB_TOL), f"{bot.ref} pad {q.number!r}"
            w, h = (q.w, q.h) if bot.rot % 180 == 0 else (q.h, q.w)
            assert (f[0].bw, f[0].bh) == pytest.approx((w, h), abs=GERB_TOL), f"{bot.ref} pad {q.number!r} size"
        elif not l.prim_bbox:
            assert (f[0].x, f[0].y) == pytest.approx(bot.pad_xy(q), abs=GERB_TOL), f"{bot.ref} pad {q.number!r}"


def test_flash_count(board):
    n = sum(1 for f in board["flashes"]["top"] + board["flashes"]["bottom"] if f.ref.startswith("B"))
    conftest.REPORT.append(f"bottom-side parts: {n} pad flashes of {len(board['pairs'])} bottom parts (4 footprints x 5 rotations) "
                           f"== their top twins turned over, KiCad re-read == FOOTPRINT::Flip storage, pos == CPL")
    assert n > 100


# ---------------------------------------------------------------------------------------------- (c) ----
def test_pos_file_and_cpl_agree(board):
    """`kicad-cli pcb export pos`: side bottom, and the rotation / X / Y the DSL writes in the JLC CPL for every bottom part"""
    b, pos, d = board["board"], board["pos"], board["dir"]
    files = b.write_jlc(str(d))
    cpl = {r["Designator"]: r for r in csv.DictReader(open(files["cpl.csv"]))}
    mid = lambda ref: (float(cpl[ref]["Mid X"][:-2]), float(cpl[ref]["Mid Y"][:-2]))
    for bot, top, lib in board["pairs"]:
        assert pos[bot.ref]["Side"] == "bottom" and pos[top.ref]["Side"] == "top", bot.ref
        assert cpl[bot.ref]["Layer"] == "Bottom" and cpl[top.ref]["Layer"] == "Top"
        assert float(pos[bot.ref]["Rot"]) % 360 == pytest.approx(float(cpl[bot.ref]["Rotation"]) % 360, abs=1e-6), bot.ref
        assert (float(pos[bot.ref]["PosX"]), float(pos[bot.ref]["PosY"])) == pytest.approx((bot.x, bot.y), abs=1e-3), bot.ref
        # Mid X/Y (the pad-bbox centre, seen from the top) is the twin's turned over: same x offset from the origin, y mirrored
        tx, ty = mid(top.ref)
        assert mid(bot.ref) == pytest.approx((tx - (top.x - bot.x), 2 * top.y - ty), abs=1e-3), bot.ref


# ---------------------------------------------------------------------------------------------- (d) ----
def test_circuit_json_and_solid_put_the_part_under_the_board(board):
    b = board["board"]
    els = b.circuit_json()
    comp = {e["pcb_component_id"]: e for e in els if e["type"] == "pcb_component"}
    byname = {e["source_component_id"]: e["name"] for e in els if e["type"] == "source_component"}
    for e in els:
        if e["type"] == "pcb_smtpad":
            ref = byname[comp[e["pcb_component_id"]]["source_component_id"]]
            assert e["layer"] == ("bottom" if ref.startswith("B") else "top"), (ref, e["layer"])
        if e["type"] == "pcb_port":
            ref = byname[comp[e["pcb_component_id"]]["source_component_id"]]
            if ref.startswith("B1") or ref.startswith("T1"):                              # SOIC: all SMD
                assert e["layers"] == (["bottom"] if ref.startswith("B") else ["top"]), (ref, e["layers"])
    assert all(comp[c]["layer"] == ("bottom" if byname[comp[c]["source_component_id"]].startswith("B") else "top") for c in comp)
    bot, top, _ = board["pairs"][0]                                                           # SOIC-8 at 0 / 0
    parts = {p.label: p for p in b.solid(models=True)}
    m_bot, m_top = parts[f"{bot.ref} {bot.fp.name}"], parts[f"{top.ref} {top.fp.name}"]
    assert m_top.bounding_box().min.Z >= b.z + b.thickness - 0.01
    assert m_bot.bounding_box().max.Z <= b.z + 0.01 and m_bot.bounding_box().min.Z < b.z - 0.5
    assert m_bot.bounding_box().size.Z == pytest.approx(m_top.bounding_box().size.Z, abs=1e-3)
    pad = parts[f"{bot.ref} pad 1"]
    assert pad.bounding_box().max.Z == pytest.approx(b.z, abs=1e-6)
    assert (pad.bounding_box().center().X, pad.bounding_box().center().Y) == pytest.approx(bot.pad_xy(bot.fp.pad(1)), abs=1e-3)
