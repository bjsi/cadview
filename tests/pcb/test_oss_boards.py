"""3. Open-source board comparison.

Nine open-source KiCad boards from GitHub (fixtures/oss/, provenance + licence + sha256 in fixtures/oss/SOURCES.md) are
parsed with kicad_parse (footprints, placements, rotations, the net on every pad, the Edge.Cuts outline), re-expressed
through the DSL with the same library footprints / placements / nets and no copper routing, and both boards are
exported with kicad-cli.  gerbonara then compares, per layer:
  - Edge.Cuts: the same lines / arcs within 0.01 mm,
  - drill files: the same PTH / NPTH holes and slots within 0.01 mm,
  - F.Cu / B.Cu: every pad flash at the same place with the same aperture (and the same net attribute); tracks and
    zone fills are excluded on purpose.
The two .kicad_pcb netlists are compared pad by pad as well.  The per-layer diff goes into the terminal summary.

The boards were picked as a stress test (parts on both sides, rotations off the 90 deg grid, slot drills, custom and
trapezoid pads, arc / bezier / polygon outlines, cutouts, 100+ footprints from a dozen libraries, a 4-layer board).  What a
board has is DETECTED from the file (`_features`) and checked against what it was picked for (BOARDS).  Where a feature is
one the DSL cannot express yet, GAPS names the test it breaks and the board's test is a strict xfail with that reason -
the gap list is the point; a board is never dropped for it.  Bottom-side parts are excluded from the pad / drill
comparisons (so the top side of such a board is still proven exactly) and pinned by `test_bottom_side_parts`.

The regenerated board uses the footprints from the KiCad library installed here; the original embeds the footprints
it was drawn with.  Where those differ the mismatch is reported pad by pad - it is library drift, not a DSL error,
and the `embedded` variant below re-runs the same comparison with the originals' own footprints written out as a
temporary .pretty library, which isolates the DSL.  Footprints from a board's own project library (not installed) are
always taken from the embedded set; a board with no installed-library footprint at all skips the `library` variant.
"""
from __future__ import annotations

import gzip
import hashlib
import math
import os
import pathlib
import re
import shutil

import pytest

import conftest
import helpers as H
import kicad_parse as kp

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "oss"
TOL = 0.01

# board -> the features it was picked for (every one must be detected in the file, see test_fixture_is_what_we_think)
BOARDS = {
    "pi-pico-mpu6050-light": set(),
    "stepper-playground-12v-pico": set(),
    "hsp-usb-led": {"arc outline", "slot drills"},
    "capacitive-soil-moisture-sensor": {"bottom-side footprints", "odd rotations", "arc outline", "KiCad 6/7 format"},
    "generic-pan-tilt-motor": {"bottom-side footprints", "custom pads", "arc outline", "50+ footprints", "many libraries"},
    "generic-pan-tilt-main": {"bottom-side footprints", "custom pads", "slot drills", "arc outline", "cutouts", "50+ footprints", "many libraries"},
    "pico-ice-rev3": {"inner copper layers", "bottom-side footprints", "custom pads", "slot drills", "arc outline", "50+ footprints", "many libraries"},
    "antmicro-usb-c-power-adapter": {"inner copper layers", "bottom-side footprints", "trapezoid pads", "custom pads", "slot drills", "50+ footprints"},
    "crkbd-corne-cherry-hotswap": {"bottom-side footprints", "odd rotations", "slot drills", "custom pads", "bezier Edge.Cuts", "circular Edge.Cuts cutouts",
                                   "footprint-level Edge.Cuts", "50+ footprints", "many libraries", "KiCad 6/7 format"},
}

# feature the DSL cannot express -> (tests it breaks, why).  Strict: when the DSL learns it, the xfail turns into a failure here.
GAPS = {
    "bottom-side footprints": (("test_bottom_side_parts",),
                               "kicad_pcb() writes every footprint on F.Cu (Placed.layer is ignored); a bottom-side part needs layer B.Cu and the "
                               "library tree the way KiCad stores a flipped footprint: pad y -> -y, pad angles negated, F.<layer> <-> B.<layer>"),
    "inner copper layers": (("test_layer_stack",),
                            "the DSL is 2-layer: F.Cu / B.Cu only in the layer table, no In1.Cu / In2.Cu copper"),
    "bezier Edge.Cuts": (("test_outline_matches",),
                         "gr_curve (cubic bezier) outline segments: kicad_pcb() writes every edge that is not a line or a full circle as a 3-point gr_arc"),
    "circular Edge.Cuts cutouts": (("test_outline_matches", "test_drill_table_matches"),
                                   "a circle inside the outline becomes an NPTH footprint (Board.holes), not a gr_circle on Edge.Cuts"),
}


def _features(rec: kp.BoardRec) -> set:
    """what a board has, read off the file"""
    pads = [p for fp in rec.footprints for p in fp.pads]
    kinds = {e.kind for e in rec.edge}
    libs = {fp.name.partition(":")[0] for fp in rec.footprints}
    f = set()
    if any(fp.layer == "B.Cu" for fp in rec.footprints): f.add("bottom-side footprints")
    if len(rec.copper_layers) > 2: f.add("inner copper layers")
    if any(fp.rot % 90 for fp in rec.footprints): f.add("odd rotations")
    if any(p.drill and p.drill[0] == "oval" for p in pads): f.add("slot drills")
    if any(p.shape == "custom" for p in pads): f.add("custom pads")
    if any(p.shape == "trapezoid" for p in pads): f.add("trapezoid pads")
    if "arc" in kinds: f.add("arc outline")
    if "curve" in kinds: f.add("bezier Edge.Cuts")
    if "poly" in kinds: f.add("polygon Edge.Cuts")
    if "circle" in kinds and kinds - {"circle"}: f.add("circular Edge.Cuts cutouts")
    if len([e for e in rec.edge if e.kind == "rect"]) > 1: f.add("cutouts")
    if rec.fp_edge_items: f.add("footprint-level Edge.Cuts")
    ends = [p for e in rec.edge if e.kind in ("line", "arc", "curve") for p in (e.pts[0], e.pts[-1])]
    gaps = [min(math.hypot(p[0] - q[0], p[1] - q[1]) for j, q in enumerate(ends) if j != i) for i, p in enumerate(ends)]
    if gaps and 1e-5 < max(gaps) <= 0.02: f.add("Edge.Cuts gaps under 0.02 mm")
    if len(rec.footprints) >= 50: f.add("50+ footprints")
    if len(libs) >= 8: f.add("many libraries")
    if rec.version < 20240000: f.add("KiCad 6/7 format")
    return f


def _export(kicad, pcb: str, out: pathlib.Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    kicad.ok("pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu,Edge.Cuts", "-o", str(out) + "/", pcb)
    kicad.ok("pcb", "export", "drill", "--excellon-separate-th", "-o", str(out) + "/", pcb)
    f = {n: str(out / n) for n in os.listdir(out)}
    pick = lambda suffix: next((v for k, v in f.items() if k.endswith(suffix)), None)
    return dict(top=pick("F_Cu.gtl"), bottom=pick("B_Cu.gbl"), edge=pick("Edge_Cuts.gm1"), pth=pick("-PTH.drl"), npth=pick("-NPTH.drl"))


def _unpack(name: str, dest: str) -> str:
    """the fixture (plain or gzip-compressed - the big boards are stored compressed) copied to `dest`"""
    plain, gz = FIX / f"{name}.kicad_pcb", FIX / f"{name}.kicad_pcb.gz"
    if plain.exists():
        shutil.copy(plain, dest)
    else:
        with gzip.open(gz, "rb") as f, open(dest, "wb") as g:
            shutil.copyfileobj(f, g)
    return dest


_AT3 = re.compile(r"^(\t\t\t\(at [-\d.]+ [-\d.]+)(?: ([-\d.]+))?\)$", re.M)                       # KiCad 8+: a pad's / property's `at` on its own line
_AT_INLINE = re.compile(r"^(\t\t\((?:pad|fp_text) .*?\(at [-\d.]+ [-\d.]+)(?: ([-\d.]+))?\)", re.M)   # KiCad 6 / 7: `(pad "1" smd rect (at x y a) ...` inline
_STRIP = re.compile(r"^\t\t(?:\(at [-\d. ]+\)|\(path \"[^\"]*\"\)|\(sheetname \"[^\"]*\"\)|\(sheetfile \"[^\"]*\"\))\n"
                    r"|\s*\((?:net (?:\d+ )?\"[^\"]*\"|pinfunction \"[^\"]*\"|pintype \"[^\"]*\")\)", re.M)
_INDENT = re.compile(r"^((?:  )+)", re.M)


def _footprint_library(rec: kp.BoardRec, path: str, dest: pathlib.Path, installed_root: str | None = None) -> set:
    """<dest>/<Lib>.pretty/<Name>.kicad_mod for every footprint the board uses, so the DSL reads one directory.  With
    `installed_root` a footprint that exists in the installed KiCad library is symlinked from there (the `library`
    variant: what a user of the DSL gets; returns those names); the rest - and everything in the `embedded` variant -
    is the original's own embedded footprint written out.  Those blocks are cut out of KiCad's own text (balanced
    parentheses) and only what a board instance adds is removed: the placement, path / sheet, the nets / pin functions
    on pads; pad and text angles (absolute in a board, and omitted when 0) go back to the footprint frame.  A footprint
    placed on both sides is taken from a top-side instance (KiCad stores a flipped footprint mirrored); one that only
    ever sits on the bottom is written as stored.  KiCad 6 / 7 files indent with two spaces: normalised to tabs first."""
    text = open(path).read()
    if "\n  (footprint " in text:
        text = _INDENT.sub(lambda m: "\t" * (len(m.group(1)) // 2), text)
    blocks: dict = {}
    i = 0
    while True:
        i = text.find("\n\t(footprint ", i)
        if i < 0:
            break
        j, depth = i + 1, 0
        while True:
            c = text[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            elif c == '"':
                j = text.index('"', j + 1)
                while text[j - 1] == "\\":
                    j = text.index('"', j + 1)
            j += 1
        block = text[i + 1:j + 1] + "\n"
        fp = kp.read_footprint(kp.parse(block))
        blocks.setdefault(fp.name, []).append((fp, block))
        i = j
    from_installed = set()
    for name, inst in blocks.items():
        lib, _, fname = name.partition(":")
        d = dest / f"{lib}.pretty"; d.mkdir(parents=True, exist_ok=True)
        if installed_root:
            src = os.path.join(installed_root, f"{lib}.pretty", f"{fname}.kicad_mod")
            if os.path.isfile(src):
                os.symlink(src, d / f"{fname}.kicad_mod")
                from_installed.add(name)
                continue
        fp, block = next(((f, b) for f, b in inst if f.layer == "F.Cu"), inst[0])
        body = _STRIP.sub("", block)
        unrot = lambda m: f"{m.group(1)} {(float(m.group(2) or 0) - fp.rot) % 360:g})"
        body = _AT_INLINE.sub(unrot, _AT3.sub(unrot, body))
        body = body.replace(f'(footprint "{name}"', f'(footprint "{fname}"', 1)
        (d / f"{fname}.kicad_mod").write_text(body.replace("\n\t", "\n")[1:])
    return from_installed


def _library_drift(m, rec: kp.BoardRec, from_installed: set) -> dict:
    """{(ref, pad): why} for every pad whose embedded definition differs from the installed library's (the board was
    drawn with an older KiCad library): compared through kicad_parse only.  A renamed pad is listed under both numbers."""
    out, cache = {}, {}
    for fp in rec.footprints:
        lib, _, name = fp.name.partition(":")
        if fp.name not in from_installed:
            continue
        if fp.name not in cache:
            cache[fp.name] = kp.read_kicad_mod(H.lib_path(m, lib, name))
        lp = cache[fp.name].pads
        if len(lp) != len(fp.pads):
            for p in fp.pads + lp:
                out[(fp.ref, p.number)] = f"{len(lp)} pads in the library, {len(fp.pads)} embedded"
            continue
        for e, l in zip(fp.pads, lp):
            geo_e = (e.shape, round(e.x, 4), round(e.y, 4), round(e.w, 4), round(e.h, 4), e.drill, e.offset, e.layers, e.kind)
            geo_l = (l.shape, round(l.x, 4), round(l.y, 4), round(l.w, 4), round(l.h, 4), l.drill, l.offset, l.layers, l.kind)
            if geo_e != geo_l or e.number != l.number:
                out[(fp.ref, e.number)] = out[(fp.ref, l.number)] = f"embedded {e.number} {geo_e[:5]} vs library {l.number} {geo_l[:5]}"
    return out


@pytest.fixture(scope="module", params=["library", "embedded"])
def variant(request):
    return request.param


@pytest.fixture(scope="module", params=list(BOARDS))
def oss(request, variant, cadpcb, kicad, outdir):
    name = request.param
    d = outdir / "oss" / f"{name}-{variant}"; d.mkdir(parents=True, exist_ok=True)
    orig = _unpack(name, str(d / "original.kicad_pcb"))
    rec = kp.read_board(orig)
    assert rec.version >= 20211014, f"{name}: KiCad 6+ board expected, version {rec.version}"
    features = _features(rec)
    libs = {fp.name.partition(":")[0] for fp in rec.footprints}
    libdir = d / "footprints"
    installed = _footprint_library(rec, orig, libdir, cadpcb.KICAD_FP if variant == "library" else None)
    if variant == "library" and not installed:
        pytest.skip(f"{name}: no footprint of it is in the installed KiCad library (libraries: {', '.join(sorted(libs))}); only the embedded variant applies")
    face, face_error = None, ""
    try:
        face = H.face_from_edge_cuts(rec.edge)
    except Exception as e:                                                   # the rest of the board is still compared on a stand-in outline
        face, face_error = H.fallback_face(rec.edge), f"{type(e).__name__}: {e}"
    b = H.reexpress(cadpcb, rec, name, footprint_dir=str(libdir), face=face)
    regen = H.write_pcb(b, str(d / "regenerated.kicad_pcb"))
    regen_rec = kp.read_board(regen)
    drift = _library_drift(cadpcb, rec, installed) if variant == "library" else {}
    conftest.REPORT.append(f"{name} [{variant}]: KiCad {rec.version:.0f}, {len(rec.copper_layers)} copper layers, {len(rec.footprints)} footprints "
                           f"({sum(fp.layer == 'B.Cu' for fp in rec.footprints)} on B.Cu) from {len(libs)} libraries "
                           f"({sum(fp.name in installed for fp in rec.footprints)} footprints from the installed library); "
                           f"features: {', '.join(sorted(features)) or '-'}" + (f"; outline NOT built: {face_error}" if face_error else ""))
    if drift:
        conftest.REPORT.append(f"{name}: {len(drift)} pads differ between the embedded (KiCad {rec.version:.0f}) and the installed "
                               f"library footprints: " + ", ".join(f"{r}.{p}" for r, p in sorted(drift)))
    return dict(name=name, variant=variant, rec=rec, regen_rec=regen_rec, board=b, orig=orig, regen=regen, drift=drift, features=features,
                face_error=face_error, libs=libs, installed=installed,
                bottom={fp.ref for fp in rec.footprints if fp.layer == "B.Cu"},
                vias=[(x, -y, dr) for x, y, dr in rec.vias],           # gerber frame
                a=_export(kicad, orig, d / "gerb-original"), b=_export(kicad, regen, d / "gerb-regenerated"))


@pytest.fixture(autouse=True)
def _gaps(request, oss):
    """a test the board's features put in GAPS is a strict xfail naming the feature"""
    test = request.node.originalname or request.node.name.split("[")[0]
    for feat in sorted(oss["features"]):
        tests, why = GAPS.get(feat, ((), ""))
        if test in tests:
            request.applymarker(pytest.mark.xfail(strict=True, reason=f"{oss['name']}: {feat} - {why}"))


def _report(oss, layer, matched, left, right, extra=""):
    line = (f"{oss['name']} [{oss['variant']} footprints] {layer}: {matched} match, {len(left)} only in original, "
            f"{len(right)} only in DSL{extra}")
    conftest.REPORT.append(line)
    return line


def _drilled(rec: kp.BoardRec, refs: set) -> list:
    """gerber-frame positions of every drilled pad of the footprints `refs` (as that file stores them)"""
    out = []
    for fp in rec.footprints:
        if fp.ref in refs:
            for p in fp.pads:
                if p.drill:
                    x, y = kp.pad_abs(fp, p)
                    out.append((x, -y))
    return out


def _without_holes_at(records: list, pts: list, tol=0.05) -> list:
    """drill records whose hole (or slot midpoint) is not within `tol` of any point in `pts`"""
    def at(r):
        return (r[1], r[2]) if r[0] == "hole" else ((r[1] + r[3]) / 2, (r[2] + r[4]) / 2)
    return [r for r in records if not any(abs(at(r)[0] - x) < tol and abs(at(r)[1] - y) < tol for x, y in pts)]


# ---------------------------------------------------------------------------------------------------- tests ----
def test_fixture_matches_sources(oss):
    """the fixture is byte-for-byte the upstream file SOURCES.md says it is"""
    rows = {m.group(1): m.group(2) for m in re.finditer(r"^\| `([^`]+)\.kicad_pcb(?:\.gz)?` \|.*\| `([0-9a-f]{64})` \|$", (FIX / "SOURCES.md").read_text(), re.M)}
    assert oss["name"] in rows, f"{oss['name']} has no row in SOURCES.md"
    assert hashlib.sha256(open(oss["orig"], "rb").read()).hexdigest() == rows[oss["name"]]


def test_fixture_is_what_we_think(oss):
    rec = oss["rec"]
    assert rec.footprints and rec.edge, "no footprints / no Edge.Cuts"
    assert rec.segments > 0, "a board with no copper routing would not exercise the exclusion"
    assert len(oss["board"].parts) == len(rec.footprints)
    missing = BOARDS[oss["name"]] - oss["features"]
    assert not missing, f"picked for {sorted(missing)} but the file does not have it; detected: {sorted(oss['features'])}"


def test_layer_stack(oss):
    """the regenerated board has the original's copper layers"""
    assert oss["regen_rec"].copper_layers == oss["rec"].copper_layers


def test_outline_matches(oss):
    assert not oss["face_error"], f"Edge.Cuts did not make a build123d Face: {oss['face_error']}"
    a = [e for e in kp.read_outline(oss["a"]["edge"]) if e[0] != "region"]
    b = [e for e in kp.read_outline(oss["b"]["edge"]) if e[0] != "region"]
    matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: r[0])
    msg = _report(oss, "Edge.Cuts", matched, left, right)
    assert not left and not right, msg + f"\n  original only: {left[:6]}\n  DSL only: {right[:6]}"
    assert matched > 0


def test_drill_table_matches(oss):
    skip_a = _drilled(oss["rec"], oss["bottom"])                       # bottom-side parts are pinned by test_bottom_side_parts
    skip_b = _drilled(oss["regen_rec"], oss["bottom"])
    for kind in ("pth", "npth"):
        a = kp.read_drills(oss["a"][kind]) if oss["a"][kind] else []
        b = kp.read_drills(oss["b"][kind]) if oss["b"][kind] else []
        # via holes belong to the routing, which the re-expression leaves out: drop the original's via drills
        via_holes = [("hole", x, y, d) for x, y, d in oss["vias"]]
        if kind == "pth":
            _, _, a = kp.match_multisets(via_holes, a, TOL, key=lambda r: r[0])   # right = the original's holes that are not vias
        na, nb = len(a), len(b)
        a, b = _without_holes_at(a, skip_a), _without_holes_at(b, skip_b)
        matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: r[0])
        msg = _report(oss, kind.upper() + " drill", matched, left, right,
                      extra=(f" (excluded: {len(via_holes)} via holes" if kind == "pth" else " (excluded:") + f", bottom-side parts' holes {na - len(a)} / {nb - len(b)})")
        drift_ok = oss["variant"] == "library" and all(_hole_near_drift_pad(oss, h) for h in left + right)
        assert (not left and not right) or drift_ok, msg + f"\n  original only: {left[:6]}\n  DSL only: {right[:6]}"


def _hole_near_drift_pad(oss, hole) -> bool:
    """a drill difference in the `library` variant is acceptable only at a pad whose footprint drifted"""
    x, y = hole[1], hole[2]
    for fp in oss["rec"].footprints:
        for p in fp.pads:
            if (fp.ref, p.number) in oss["drift"]:
                px, py = kp.pad_abs(fp, p)
                if abs(px - x) < 0.5 and abs(-py - y) < 0.5:
                    return True
    return False


_SIG = lambda f: (f.ref, f.pad, f.x, f.y, f.cx, f.cy, f.bw, f.bh) + f.sig


@pytest.mark.parametrize("layer", ["top", "bottom"])
def test_pad_flashes_match(oss, layer):
    A = kp.read_copper(oss["a"][layer])
    B = kp.read_copper(oss["b"][layer])
    bottom = oss["bottom"]
    vias = [f for f in A["flashes"] if f.ref == ""]                    # via flashes carry no .P (ref, pad) attribute
    a = [_SIG(f) for f in A["flashes"] if f.ref != "" and f.ref not in bottom]
    b = [_SIG(f) for f in B["flashes"] if f.ref not in bottom]
    assert all(f.ref for f in B["flashes"]), "the re-expression must carry no vias"
    matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: (r[0], r[1]))
    lname = {"top": "F.Cu", "bottom": "B.Cu"}[layer]
    msg = _report(oss, lname + " pads", matched, left, right,
                  extra=f" (excluded: original {A['lines']} track segments + {A['arcs']} arcs + {A['regions']} zone regions + {len(vias)} vias"
                        f"{f' + {len(bottom)} bottom-side parts' if bottom else ''}; DSL {B['lines']}/{B['arcs']}/{B['regions']}/0)")
    detail = "\n".join(f"  original only: {r[:8]} {r[8:]}" for r in left[:5]) + "\n" + "\n".join(f"  DSL only: {r[:8]} {r[8:]}" for r in right[:5])
    assert B["lines"] == 0 and B["arcs"] == 0, "the re-expression must carry no copper routing"   # regions: fp_poly copper inside footprints is allowed
    drift = set(oss["drift"])
    assert matched > 0 or not {(r[0], r[1]) for r in a} - drift, msg
    if oss["variant"] == "library":
        # the installed library may differ from the footprints the board embeds: every mismatch must be one of those pads
        odd = {(r[0], r[1]) for r in left + right}
        unexplained = odd - set(oss["drift"])
        if odd:
            conftest.REPORT.append(f"{oss['name']} [library] {lname}: {len(odd)} mismatched pads, all library drift: {sorted(odd)}" if not unexplained
                                   else f"{oss['name']} [library] {lname}: UNEXPLAINED mismatches {sorted(unexplained)}")
        assert not unexplained, msg + "\n" + detail
    else:
        assert not left and not right, msg + "\n" + detail
    # the net attribute on every pad flash agrees too (pad-by-pad netlist through the Gerber X2 attributes)
    an = sorted((f.ref, f.pad, f.net) for f in A["flashes"] if f.ref != "" and f.ref not in bottom and (f.ref, f.pad) not in drift)
    bn = sorted((f.ref, f.pad, f.net) for f in B["flashes"] if f.ref not in bottom and (f.ref, f.pad) not in drift)
    assert an == bn


def test_bottom_side_parts(oss):
    """the parts the original places on B.Cu are on B.Cu in the regenerated board, with every pad flash where KiCad put it"""
    bottom = oss["bottom"]
    if not bottom:
        pytest.skip("no bottom-side parts on this board")
    layers = {fp.ref: fp.layer for fp in oss["regen_rec"].footprints}
    wrong = sorted(r for r in bottom if layers.get(r) != "B.Cu")
    assert not wrong, f"{len(wrong)} of {len(bottom)} bottom-side parts are not on B.Cu in the DSL's board: {wrong[:8]}"
    for layer in ("top", "bottom"):
        a = [_SIG(f) for f in kp.read_copper(oss["a"][layer])["flashes"] if f.ref in bottom]
        b = [_SIG(f) for f in kp.read_copper(oss["b"][layer])["flashes"] if f.ref in bottom]
        matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: (r[0], r[1]))
        msg = _report(oss, f"bottom-side parts on {layer}", matched, left, right)
        assert not left and not right, msg


def test_netlists_match_pad_by_pad(oss):
    a = oss["rec"].pad_nets()
    regen = oss["regen_rec"]
    regen.footprints = [fp for fp in regen.footprints if not fp.name.startswith("cadview:")]   # the DSL's own NPTH footprints for circular cutouts
    b = regen.pad_nets()
    drift = set(oss["drift"])                                           # library variant: a pad the installed library renamed cannot carry its net
    assert set(a) - drift == set(b) - drift, (set(a) ^ set(b)) - drift
    diff = {k: (a[k], b[k]) for k in a if k not in drift and a[k] != b[k]}
    conftest.REPORT.append(f"{oss['name']} [{oss['variant']}] netlist: {len(a)} (ref, pad) keys, {len(diff)} differ")
    assert not diff, diff
    nets_a = {n for v in a.values() for n in v if n}
    assert set(oss["board"].nets) == nets_a
