"""1. Footprint fidelity.

(a) `kicad_footprint()` against an independent parse of the same .kicad_mod (kicad_parse): pad numbers, kinds,
    shapes, positions (y flipped), sizes (swapped for pads rotated 90 inside the footprint, widened to the primitives
    of custom pads), drills (the larger slot dimension), copper layers, and the 3D model path.
(b) write -> kicad-cli (`pcb drc --save-board`, KiCad re-serialises the board) -> re-read with kicad_parse: every
    footprint sits at the DSL's position and every pad comes back exactly as the library file has it (number, kind,
    shape, position, size, drill, offset, layers, custom primitives).
(c) write -> kicad-cli `pcb export gerbers` -> gerbonara: the copper flashes KiCad itself computed for each pad sit
    where the DSL's `Placed.pad_xy()` says, with the DSL's size, for parts at 0 / 90 / 180 / 270 degrees.
(d) known deviations, pinned as strict xfails so a fix shows up: pads with `(drill (offset ..))`, custom pads
    rotated inside their footprint, paste-only pads (all three occur on the Pico SMD footprint's debug / castellation
    pads).  They affect the DSL's own pad model (Circuit JSON, solid(), JLC Mid X/Y), not the .kicad_pcb, which
    embeds the library tree verbatim.
"""
from __future__ import annotations

import math
import os

import pytest

import conftest
import helpers as H
import kicad_parse as kp

FOOTPRINTS = [
    ("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm"),
    ("Package_TO_SOT_SMD", "SOT-23"),
    ("Package_QFP", "LQFP-48_7x7mm_P0.5mm"),
    ("Package_DIP", "DIP-16_W7.62mm"),
    ("Resistor_SMD", "R_0603_1608Metric"),
    ("Capacitor_SMD", "C_0603_1608Metric"),
    ("Capacitor_SMD", "CP_Elec_6.3x5.4"),
    ("Capacitor_THT", "CP_Radial_D5.0mm_P2.00mm"),
    ("Connector_JST", "JST_XH_B5B-XH-A_1x05_P2.50mm_Vertical"),
    ("Connector_PinHeader_2.54mm", "PinHeader_1x04_P2.54mm_Vertical"),
    ("Connector_PinHeader_2.54mm", "PinHeader_2x03_P2.54mm_Vertical"),
    ("Connector_USB", "USB_Micro-B_Molex-105017-0001"),        # oval drills (slots)
    ("Module", "RaspberryPi_Pico_SMD"),                        # custom pads with primitives, offsets, paste-only pads
    ("Module", "RaspberryPi_Pico_Common_THT"),                 # thru_hole custom + roundrect + circle
    ("MountingHole", "MountingHole_3.2mm_M3"),                 # NPTH only, no copper
]
IDS = [n for _, n in FOOTPRINTS]
PICO_SMD = IDS.index("RaspberryPi_Pico_SMD")
TOL = 1e-6          # (a), (b): the same numbers through two parsers
GERB_TOL = 0.01     # (c): Gerber coordinates (6 decimals) vs the DSL's 4-decimal rounding
PITCH = (34.0, 64.0)   # grid for the boards in (b) and (c): the Pico is 21 x 51 mm


def _lib(m, idx):
    lib, name = FOOTPRINTS[idx]
    return kp.read_kicad_mod(H.lib_path(m, lib, name))


# ---------------------------------------------------------------------------------------------- (a) ----
@pytest.mark.parametrize("idx", range(len(FOOTPRINTS)), ids=IDS)
def test_pads_match_independent_parse(cadpcb, idx):
    lib, name = FOOTPRINTS[idx]
    fp = cadpcb.kicad_footprint(lib, name)
    ref = _lib(cadpcb, idx)
    assert fp.name == name and fp.lib == lib
    assert len(fp.pads) == len(ref.pads) > 0
    plain = 0
    for q, p in zip(fp.pads, ref.pads):
        where = f"{name} pad {p.number!r}"
        assert q.number == p.number, where
        assert q.kind == p.kind, where
        assert q.shape == p.shape, where
        assert q.drill == pytest.approx(H.expected_drill(p), abs=TOL), f"{where}: drill"
        if not H.pad_is_plain(p):
            continue                                  # (d)
        plain += 1
        x, y, w, h = H.expected_pad_geom(p)
        assert (q.x, q.y) == pytest.approx((x, y), abs=TOL), f"{where}: position {(q.x, q.y)} vs {(x, y)}"
        assert (q.w, q.h) == pytest.approx((w, h), abs=TOL), f"{where}: size {(q.w, q.h)} vs {(w, h)}"
        assert tuple(q.layers) == H.expected_layers(p), f"{where}: layers {q.layers} vs {H.expected_layers(p)}"
    assert plain == sum(1 for p in ref.pads if H.pad_is_plain(p))
    if ref.model:
        assert fp.model and "${" not in fp.model and fp.model.endswith(ref.model.split("}")[-1]), fp.model
        assert os.path.isabs(fp.model)
    else:
        assert fp.model is None


def test_pad_lookup_by_number(cadpcb):
    fp = cadpcb.kicad_footprint("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm")
    assert fp.pad(1).number == "1" and fp.pad("8").number == "8"
    with pytest.raises(KeyError):
        fp.pad(9)


def test_hex_timestamp_stays_a_symbol(cadpcb, tmp_path):
    """KiCad 5 / 6 footprints carry `(tedit 527E5841)`, a hex edit stamp that Python's float() reads as 5.27e5843 = inf
    (hackrf-one's GSG-QFN20-4; `50997E90` would silently become 5.1e94).  The DSL's parser takes only plain decimals as
    numbers, so the token is kept as the symbol it is and serialised back verbatim."""
    lib = tmp_path / "stamp.pretty"; lib.mkdir()
    (lib / "X.kicad_mod").write_text('(footprint "X" (version 20211014) (layer "F.Cu") (tedit 527E5841)\n'
                                     '  (fp_text reference "REF**" (at 0 0) (layer "F.SilkS") (tedit 50997E90))\n'
                                     '  (pad "1" smd rect (at 0 0) (size 1 1.5) (layers "F.Cu" "F.Mask"))\n)\n')
    saved = cadpcb.KICAD_FP
    cadpcb.KICAD_FP = str(tmp_path)
    try:
        fp = cadpcb.kicad_footprint("stamp", "X")
    finally:
        cadpcb.KICAD_FP = saved
    assert cadpcb._kv(fp.tree, "tedit") == ["tedit", "527E5841"]
    assert fp.pad(1).w == 1.0 and fp.pad(1).h == 1.5
    b = cadpcb.Board(H.face_rect(20, 10), name="stamp")
    b.place(fp, "U1", (0, 0))
    text = b.kicad_pcb()
    assert "(tedit 527E5841)" in text and "(tedit 50997E90)" in text and "inf" not in text


def test_unlocked_text_position_turns_with_the_part(cadpcb, tmp_path):
    """a KiCad 7 footprint writes a text's position as `(at x y unlocked)` or `(at x y 180 unlocked)` (placebo's, olimex's);
    the writer added the part's rotation to whatever followed x y, so the symbol `unlocked` crashed it (str + float).  The
    angle is the number after x y, 0 when there is none, and `unlocked` is kept after it."""
    lib = tmp_path / "unl.pretty"; lib.mkdir()
    (lib / "X.kicad_mod").write_text('(footprint "X" (version 20221018) (layer "F.Cu")\n'
                                     '  (fp_text reference "REF**" (at 0 3 180 unlocked) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))\n'
                                     '  (fp_text user "o" (at 1.143 0.762 unlocked) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))\n'
                                     '  (property "Value" "v" (at 0 -3 unlocked) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n'
                                     '  (pad "1" smd rect (at 0 0) (size 1 1.5) (layers "F.Cu" "F.Mask"))\n)\n')
    saved = cadpcb.KICAD_FP
    cadpcb.KICAD_FP = str(tmp_path)
    try:
        fp = cadpcb.kicad_footprint("unl", "X")
    finally:
        cadpcb.KICAD_FP = saved
    b = cadpcb.Board(H.face_rect(20, 10), name="unl")
    b.place(fp, "U1", (0, 0), rot=90, value="v")
    b.place(fp, "U2", (5, 0), rot=45, value="v", layer="bottom")
    tree = kp.parse(b.kicad_pcb())
    u1, u2 = kp.children(tree, "footprint")[:2]
    texts = lambda f: {(t[1], str(t[2])): kp.child(t, "at")[1:] for t in kp.children(f, "fp_text") + kp.children(f, "property")}
    assert texts(u1)[("reference", "U1")] == [0.0, 3.0, 270.0, "unlocked"]          # 180 + 90
    assert texts(u1)[("user", "o")] == [1.143, 0.762, 90.0, "unlocked"]              # no angle written: 0 + 90
    assert texts(u1)[("Value", "v")] == [0.0, -3.0, 90.0, "unlocked"]
    assert texts(u2)[("reference", "U2")] == [0.0, -3.0, 225.0, "unlocked"]          # flipped: y mirrored, -180 + 45
    assert texts(u2)[("user", "o")] == [1.143, -0.762, 45.0, "unlocked"]
    assert kp.child(kp.children(u1, "pad")[0], "at")[1:] == [0.0, 0.0, 90.0]


def test_slot_drill_is_the_long_dimension(cadpcb):
    """the DSL keeps one drill number per pad: for `(drill oval a b)` that is max(a, b) (documented, lossy)"""
    fp = cadpcb.kicad_footprint("Connector_USB", "USB_Micro-B_Molex-105017-0001")
    ref = kp.read_kicad_mod(H.lib_path(cadpcb, "Connector_USB", "USB_Micro-B_Molex-105017-0001"))
    slots = [p for p in ref.pads if p.drill and p.drill[0] == "oval"]
    assert slots, "fixture footprint has no oval drill any more"
    for p in slots:
        assert fp.pad(p.number).drill == pytest.approx(max(p.drill[1], p.drill[2]))


# ------------------------------------------------------------------------------------- (b) + (c) boards ----
def _grid_board(m, rots):
    """every fixture footprint, one column per footprint, one row per rotation, origin placement (center_pads=False)"""
    n = len(FOOTPRINTS)
    w, h = PITCH[0] * (n + 1), PITCH[1] * (len(rots) + 1)
    b = m.Board(H.face_rect(w, h, w / 2, h / 2), thickness=1.6, name="fpgrid", z=0.0)
    placed = []
    for i, (lib, name) in enumerate(FOOTPRINTS):
        fp = m.kicad_footprint(lib, name)
        for j, rot in enumerate(rots):
            ref = f"F{i + 1}R{j}"
            placed.append((ref, lib, name, b.place(fp, ref, (PITCH[0] * (i + 1), PITCH[1] * (j + 1)), rot=rot, center_pads=False)))
    return b, placed


@pytest.fixture(scope="module")
def reread(cadpcb, kicad, outdir):
    """(b): the grid board at rot 0, re-saved by kicad-cli, parsed back"""
    d = outdir / "footprints"; d.mkdir(exist_ok=True)
    b, placed = _grid_board(cadpcb, [0])
    pcb = H.write_pcb(b, str(d / "fpgrid.kicad_pcb"))
    H.write_pro(b, str(d / "fpgrid.kicad_pro"), "fpgrid")
    before = open(pcb).read()
    r = kicad.run("pcb", "drc", "--refill-zones", "--save-board", "--format", "json", "--severity-all",
                  "-o", str(d / "fpgrid-drc.json"), pcb)
    after = open(pcb).read()
    assert after != before, f"kicad-cli did not re-save the board: {r.stdout} {r.stderr}"
    return b, placed, kp.read_board(pcb)


def test_reread_footprints_at_dsl_positions(reread):
    b, placed, rec = reread
    byref = {fp.ref: fp for fp in rec.footprints}
    assert len(rec.footprints) == len(placed)
    for ref, lib, name, p in placed:
        fp = byref[ref]
        assert fp.name == f"{lib}:{name}"
        assert (fp.x, fp.y) == pytest.approx((p.x, -p.y), abs=TOL), ref
        assert fp.rot % 360 == pytest.approx(p.rot % 360), ref
        assert fp.layer == "F.Cu"


@pytest.mark.parametrize("idx", range(len(FOOTPRINTS)), ids=IDS)
def test_reread_pads_survive_kicad(cadpcb, reread, idx):
    b, placed, rec = reread
    ref, lib, name, p = placed[idx]
    fp = next(f for f in rec.footprints if f.ref == ref)
    lib_fp = _lib(cadpcb, idx)
    assert len(fp.pads) == len(lib_fp.pads) == len(p.fp.pads) > 0
    for k, l in zip(fp.pads, lib_fp.pads):
        where = f"{name} pad {l.number!r} after kicad-cli --save-board"
        assert (k.number, k.kind, k.shape) == (l.number, l.kind, l.shape), where
        assert (k.x, k.y, k.rot % 360, k.w, k.h) == pytest.approx((l.x, l.y, l.rot % 360, l.w, l.h), abs=TOL), where
        assert k.drill == pytest.approx(l.drill, abs=TOL) if l.drill and isinstance(l.drill[0], float) else k.drill == l.drill, where
        assert k.offset == pytest.approx(l.offset, abs=TOL), where
        assert k.layers == l.layers, where
        assert (k.prim_bbox is None) == (l.prim_bbox is None), where
        if l.prim_bbox:
            assert k.prim_bbox == pytest.approx(l.prim_bbox, abs=TOL), where
    # and the DSL's own numbers equal what the re-read pads give, for the plain pads
    for q, k in zip(p.fp.pads, fp.pads):
        if H.pad_is_plain(k):
            assert (q.x, q.y, q.w, q.h) == pytest.approx(H.expected_pad_geom(k), abs=TOL), f"{name} pad {k.number!r}"


@pytest.fixture(scope="module")
def flashes(cadpcb, kicad, outdir):
    """(c): the grid board at 0/90/180/270, Gerbers for F.Cu + B.Cu, flashes read back with gerbonara"""
    d = outdir / "footprints"; d.mkdir(exist_ok=True)
    b, placed = _grid_board(cadpcb, [0, 90, 180, 270])
    pcb = H.write_pcb(b, str(d / "fpgrid-rot.kicad_pcb"))
    g = d / "fpgrid-rot-gerbers"; g.mkdir(exist_ok=True)
    kicad.ok("pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu", "-o", str(g) + "/", pcb)
    files = {f: str(g / f) for f in os.listdir(g)}
    top = kp.read_copper(next(v for k, v in files.items() if k.endswith("F_Cu.gtl")))
    bot = kp.read_copper(next(v for k, v in files.items() if k.endswith("B_Cu.gbl")))
    return b, placed, {"top": top["flashes"], "bottom": bot["flashes"]}


def _want_got(p, lib_fp, fl, layer):
    """(DSL pads, KiCad flashes) for one placed part on one copper layer, plain pads only: the flashes of the
    non-plain pads (d) are taken out of the KiCad side at the position KiCad draws them (kicad_parse's semantics)."""
    want, skip = [], []
    a = math.radians(p.rot)
    for q, l in zip(p.fp.pads, lib_fp.pads):
        if not H.pad_is_plain(l):
            if l.copper:
                x, y, _, _ = H.expected_pad_geom(l)                      # footprint frame, y up
                skip.append((p.x + x * math.cos(a) - y * math.sin(a), p.y + x * math.sin(a) + y * math.cos(a)))
            continue
        if q.kind == "np_thru_hole" or layer not in q.layers:
            continue
        x, y = p.pad_xy(q)
        w, h = (q.w, q.h) if p.rot % 180 == 0 else (q.h, q.w)
        want.append((q.number, x, y, w, h))
    got = [f for f in fl[layer] if f.ref == p.ref]
    for sx, sy in skip:
        i = min(range(len(got)), key=lambda i: math.hypot(got[i].cx - sx, got[i].cy - sy), default=None)
        if i is not None and math.hypot(got[i].cx - sx, got[i].cy - sy) < 0.05:
            got.pop(i)
    return want, [(f.pad, f.cx, f.cy, f.bw, f.bh) for f in got]


@pytest.mark.parametrize("idx", range(len(FOOTPRINTS)), ids=IDS)
def test_gerber_flashes_match_pad_xy(cadpcb, flashes, idx):
    b, placed, fl = flashes
    rows = [p for ref, lib, name, p in placed if (ref.split("R")[0] == f"F{idx + 1}")]
    assert len(rows) == 4
    name = FOOTPRINTS[idx][1]
    lib_fp = _lib(cadpcb, idx)
    n = 0
    for p in rows:
        for layer in ("top", "bottom"):
            want, got = _want_got(p, lib_fp, fl, layer)
            matched, left, right = kp.match_multisets(want, got, GERB_TOL, key=lambda r: r[0])
            assert not left and not right, (f"{name} rot {p.rot} {layer}: {matched} pads match, DSL pads without a KiCad flash: "
                                            f"{left[:4]}, KiCad flashes without a DSL pad: {right[:4]}")
            assert matched == len(want)
            n += matched
    conftest.REPORT.append(f"footprint {name}: {n} pad flashes over 4 rotations x 2 layers match pad_xy() / size within {GERB_TOL} mm")


# ---------------------------------------------------------------------------------------------- (d) ----
def test_offset_rotated_custom_and_paste_only_pads_pico_smd(cadpcb, flashes):
    """the pads that are not 'just the anchor shape at the pad position' — `(drill (offset ..))`, custom pads rotated
    inside their footprint, paste-only pads — come back as KiCad draws them (was a strict xfail; fixed in cadview.pcb)"""
    b, placed, fl = flashes
    lib_fp = _lib(cadpcb, PICO_SMD)
    p = next(p for ref, lib, name, p in placed if ref == f"F{PICO_SMD + 1}R0")
    odd = [(q, l) for q, l in zip(p.fp.pads, lib_fp.pads) if not H.pad_is_plain(l)]
    assert odd, "the Pico SMD footprint no longer has offset / rotated-custom / paste-only pads: drop this test"
    problems = []
    for q, l in odd:
        if not l.copper:
            if q.layers != ():
                problems.append(f"pad {l.number!r} ({'/'.join(l.layers)}) reported on copper {q.layers}")
            continue
        x, y, w, h = H.expected_pad_geom(l)
        if (q.x, q.y, q.w, q.h) != pytest.approx((x, y, w, h), abs=GERB_TOL):
            problems.append(f"pad {l.number!r}: DSL ({q.x}, {q.y}) {q.w}x{q.h} vs KiCad ({x:.3f}, {y:.3f}) {w:.2f}x{h:.2f}")
        f = [f for f in fl["top"] if f.ref == p.ref and f.pad == l.number]
        assert len(f) == 1, (l.number, f)
        if (f[0].cx, f[0].cy) != pytest.approx(p.pad_xy(q), abs=GERB_TOL):
            problems.append(f"pad {l.number!r}: Gerber flash at ({f[0].cx:.3f}, {f[0].cy:.3f}), pad_xy() {p.pad_xy(q)}")
    problems.sort(key=lambda s: "reported on copper" in s)              # the three copper pads first, then the 47 paste pads
    conftest.REPORT.append(f"Pico SMD known deviations ({len(problems)}): " + "; ".join(problems[:7]) + (" ..." if len(problems) > 7 else ""))
    assert not problems, "\n".join(problems)
