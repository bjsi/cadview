"""3. Open-source board comparison.

Two small MIT-licensed KiCad 9 boards from GitHub (fixtures/oss/, provenance in fixtures/oss/SOURCES.md) are parsed
with kicad_parse (footprints, placements, rotations, the net on every pad, the Edge.Cuts outline), re-expressed
through the DSL with the same library footprints / placements / nets and no copper routing, and both boards are
exported with kicad-cli.  gerbonara then compares, per layer:
  - Edge.Cuts: the same lines / arcs within 0.01 mm,
  - drill files: the same PTH / NPTH holes and slots within 0.01 mm,
  - F.Cu / B.Cu: every pad flash at the same place with the same aperture (and the same net attribute); tracks and
    zone fills are excluded on purpose.
The two .kicad_pcb netlists are compared pad by pad as well.  The per-layer diff goes into the terminal summary.

The regenerated board uses the footprints from the KiCad library installed here; the original embeds the footprints
it was drawn with.  Where those differ the mismatch is reported pad by pad - it is library drift, not a DSL error,
and the `embedded` variant below re-runs the same comparison with the originals' own footprints written out as a
temporary .pretty library, which isolates the DSL.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil

import pytest

import conftest
import helpers as H
import kicad_parse as kp

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "oss"
BOARDS = ["pi-pico-mpu6050-light", "stepper-playground-12v-pico"]
TOL = 0.01


def _export(kicad, pcb: str, out: pathlib.Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    kicad.ok("pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu,Edge.Cuts", "-o", str(out) + "/", pcb)
    kicad.ok("pcb", "export", "drill", "--excellon-separate-th", "-o", str(out) + "/", pcb)
    f = {n: str(out / n) for n in os.listdir(out)}
    pick = lambda suffix: next((v for k, v in f.items() if k.endswith(suffix)), None)
    return dict(top=pick("F_Cu.gtl"), bottom=pick("B_Cu.gbl"), edge=pick("Edge_Cuts.gm1"), pth=pick("-PTH.drl"), npth=pick("-NPTH.drl"))


_AT3 = re.compile(r"^(\t\t\t\(at [-\d.]+ [-\d.]+) ([-\d.]+)\)$", re.M)      # a pad's / property's `at` with an angle (depth 3)
_STRIP = re.compile(r"^\t\t(?:\(at [-\d. ]+\)|\(path \"[^\"]*\"\)|\(sheetname \"[^\"]*\"\)|\(sheetfile \"[^\"]*\"\))\n"
                    r"|^\t\t\t(?:\(net \d+ \"[^\"]*\"\)|\(pinfunction \"[^\"]*\"\)|\(pintype \"[^\"]*\"\))\n", re.M)


def _embedded_library(rec: kp.BoardRec, path: str, dest: pathlib.Path) -> str:
    """write every footprint embedded in the original board out as <dest>/<Lib>.pretty/<Name>.kicad_mod, so the DSL can
    read the originals' own footprints instead of the installed library's.  The blocks are cut out of KiCad's own
    text (balanced parentheses) and only what a board instance adds is removed: the placement, path / sheet, the
    nets / pin functions on pads; pad and text angles (absolute in a board) go back to the footprint frame."""
    text = open(path).read()
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
        lib, _, name = fp.name.partition(":")
        d = dest / f"{lib}.pretty"; d.mkdir(parents=True, exist_ok=True)
        p = d / f"{name}.kicad_mod"
        if not p.exists():
            body = _STRIP.sub("", block)
            body = _AT3.sub(lambda m: f"{m.group(1)} {(float(m.group(2)) - fp.rot) % 360:g})", body)
            body = body.replace(f'(footprint "{fp.name}"', f'(footprint "{name}"', 1)
            p.write_text(body.replace("\n\t", "\n")[1:])
        i = j
    return str(dest)


def _library_drift(m, rec: kp.BoardRec) -> dict:
    """{(ref, pad): why} for every pad whose embedded definition differs from the installed library's (the board was
    drawn with an older KiCad library): compared through kicad_parse only"""
    out, cache = {}, {}
    for fp in rec.footprints:
        lib, _, name = fp.name.partition(":")
        if fp.name not in cache:
            cache[fp.name] = kp.read_kicad_mod(H.lib_path(m, lib, name))
        lp = cache[fp.name].pads
        if len(lp) != len(fp.pads):
            for p in fp.pads:
                out[(fp.ref, p.number)] = f"{len(lp)} pads in the library, {len(fp.pads)} embedded"
            continue
        for e, l in zip(fp.pads, lp):
            geo_e = (e.shape, round(e.x, 4), round(e.y, 4), round(e.w, 4), round(e.h, 4), e.drill, e.offset, e.layers, e.kind)
            geo_l = (l.shape, round(l.x, 4), round(l.y, 4), round(l.w, 4), round(l.h, 4), l.drill, l.offset, l.layers, l.kind)
            if geo_e != geo_l:
                out[(fp.ref, e.number)] = f"embedded {geo_e[:5]} vs library {geo_l[:5]}"
    return out


@pytest.fixture(scope="module", params=["library", "embedded"])
def variant(request):
    return request.param


@pytest.fixture(scope="module", params=BOARDS)
def oss(request, variant, cadpcb, kicad, outdir):
    name = request.param
    src = str(FIX / f"{name}.kicad_pcb")
    d = outdir / "oss" / f"{name}-{variant}"; d.mkdir(parents=True, exist_ok=True)
    orig = str(d / "original.kicad_pcb"); shutil.copy(src, orig)
    rec = kp.read_board(orig)
    assert rec.version >= 20240000, f"{name}: KiCad 8+ board expected, version {rec.version}"
    lib = _embedded_library(rec, orig, d / "embedded-lib") if variant == "embedded" else None
    b = H.reexpress(cadpcb, rec, name, footprint_dir=lib)
    regen = H.write_pcb(b, str(d / "regenerated.kicad_pcb"))
    drift = _library_drift(cadpcb, rec) if variant == "library" else {}
    if drift:
        conftest.REPORT.append(f"{name}: {len(drift)} pads differ between the embedded (KiCad {rec.version:.0f}) and the installed "
                               f"library footprints: " + ", ".join(f"{r}.{p}" for r, p in sorted(drift)))
    return dict(name=name, variant=variant, rec=rec, board=b, orig=orig, regen=regen, drift=drift,
                vias=[(x, -y, dr) for x, y, dr in rec.vias],           # gerber frame
                a=_export(kicad, orig, d / "gerb-original"), b=_export(kicad, regen, d / "gerb-regenerated"))


def _report(oss, layer, matched, left, right, extra=""):
    line = (f"{oss['name']} [{oss['variant']} footprints] {layer}: {matched} match, {len(left)} only in original, "
            f"{len(right)} only in DSL{extra}")
    conftest.REPORT.append(line)
    return line


def test_fixture_is_what_we_think(oss):
    rec = oss["rec"]
    assert rec.footprints and all(fp.layer == "F.Cu" for fp in rec.footprints)
    assert rec.edge, "no Edge.Cuts"
    assert rec.segments > 0, "a board with no copper routing would not exercise the exclusion"
    assert len(oss["board"].parts) == len(rec.footprints)


def test_outline_matches(oss):
    a = [e for e in kp.read_outline(oss["a"]["edge"]) if e[0] != "region"]
    b = [e for e in kp.read_outline(oss["b"]["edge"]) if e[0] != "region"]
    matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: r[0])
    msg = _report(oss, "Edge.Cuts", matched, left, right)
    assert not left and not right, msg + f"\n  original only: {left[:6]}\n  DSL only: {right[:6]}"
    assert matched > 0


def test_drill_table_matches(oss):
    for kind in ("pth", "npth"):
        a = kp.read_drills(oss["a"][kind]) if oss["a"][kind] else []
        b = kp.read_drills(oss["b"][kind]) if oss["b"][kind] else []
        # via holes belong to the routing, which the re-expression leaves out: drop the original's via drills
        via_holes = [("hole", x, y, d) for x, y, d in oss["vias"]]
        if kind == "pth":
            _, _, a = kp.match_multisets(via_holes, a, TOL, key=lambda r: r[0])   # right = the original's holes that are not vias
        matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: r[0])
        msg = _report(oss, kind.upper() + " drill", matched, left, right,
                      extra=f" (excluded: {len(via_holes)} via holes)" if kind == "pth" else "")
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


@pytest.mark.parametrize("layer", ["top", "bottom"])
def test_pad_flashes_match(oss, layer):
    A = kp.read_copper(oss["a"][layer])
    B = kp.read_copper(oss["b"][layer])
    sig = lambda f: (f.ref, f.pad, f.x, f.y, f.cx, f.cy, f.bw, f.bh) + f.sig
    vias = [f for f in A["flashes"] if f.ref == ""]                    # via flashes carry no .P (ref, pad) attribute
    a = [sig(f) for f in A["flashes"] if f.ref != ""]
    b = [sig(f) for f in B["flashes"]]
    assert all(f.ref for f in B["flashes"]), "the re-expression must carry no vias"
    matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: (r[0], r[1]))
    lname = {"top": "F.Cu", "bottom": "B.Cu"}[layer]
    msg = _report(oss, lname + " pads", matched, left, right,
                  extra=f" (excluded: original {A['lines']} track segments + {A['arcs']} arcs + {A['regions']} zone regions + {len(vias)} vias; "
                        f"DSL {B['lines']}/{B['arcs']}/{B['regions']}/0)")
    detail = "\n".join(f"  original only: {r[:8]} {r[8:]}" for r in left[:5]) + "\n" + "\n".join(f"  DSL only: {r[:8]} {r[8:]}" for r in right[:5])
    assert B["lines"] == 0 and B["arcs"] == 0 and B["regions"] == 0, "the re-expression must carry no copper routing"
    assert matched > 0
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
    an = sorted((f.ref, f.pad, f.net) for f in A["flashes"] if f.ref != "")
    bn = sorted((f.ref, f.pad, f.net) for f in B["flashes"])
    assert an == bn


def test_netlists_match_pad_by_pad(oss):
    a = kp.read_board(oss["orig"]).pad_nets()
    b = kp.read_board(oss["regen"]).pad_nets()
    assert set(a) == set(b), (set(a) ^ set(b))
    diff = {k: (a[k], b[k]) for k in a if a[k] != b[k]}
    conftest.REPORT.append(f"{oss['name']} [{oss['variant']}] netlist: {len(a)} (ref, pad) keys, {len(diff)} differ")
    assert not diff, diff
    nets_a = {n for v in a.values() for n in v if n}
    assert set(oss["board"].nets) == nets_a
