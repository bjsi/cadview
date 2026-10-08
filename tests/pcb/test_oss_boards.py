"""3. Open-source board comparison.

Twenty-seven open-source KiCad boards from GitHub (fixtures/oss/, provenance + licence + sha256 in fixtures/oss/SOURCES.md) are
parsed with kicad_parse (footprints, placements, rotations, the net on every pad, the Edge.Cuts outline), re-expressed
through the DSL with the same library footprints / placements / nets and no copper routing, and both boards are
exported with kicad-cli.  gerbonara then compares, per layer:
  - Edge.Cuts: the same lines / arcs within 0.01 mm,
  - drill files: the same PTH / NPTH holes and slots within 0.01 mm,
  - F.Cu / B.Cu: every pad flash at the same place with the same aperture (and the same net attribute); tracks and
    zone fills are excluded on purpose.
The two .kicad_pcb netlists are compared pad by pad as well.  The per-layer diff goes into the terminal summary.

The boards were picked as a stress test (parts on both sides, rotations off the 90 deg grid, slot drills, custom and
trapezoid pads, arc / bezier / polygon outlines, cutouts, 100+ footprints from a dozen libraries, a 4-layer board; the second
set adds a 437-footprint board, V-cut / mouse-bite / KiKit panels with duplicated references, chamfered and odd-ratio roundrect
pads, castellations with drill offsets, 22 circular cutouts, KiCad 9 files; the third set KiCad 5 files, blind / buried / micro
vias on a 4- and a 6-layer board, flex stackups, teardrops and rounded tracks, net ties, keepout rule areas, a V-cut panel of
coupons, an unrouted board, an outline that exists only inside a footprint).  What a
board has is DETECTED from the file (`_features`) and checked against what it was picked for (BOARDS).  Where a feature is
one the DSL cannot express yet, GAPS names the test it breaks and the board's test is a strict xfail with that reason -
the gap list is the point; a board is never dropped for it.  Bottom-side parts take part in every comparison (the DSL
mirrors them the way KiCad's flip stores them) and `test_bottom_side_parts` reports them on their own as well.

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
    # the second set (2026-10-07): scale, panels, pad shapes, KiCad 9 files
    "hackrf-one": {"300+ footprints", "inner copper layers", "odd rotations", "arc outline", "KiCad 6/7 format", "footprints without a library prefix",
                   "copper-less pads", "duplicate references"},
    "mozc-doublesided-main-panel": {"duplicate references", "inner copper layers", "bottom-side footprints", "slot drills", "50+ footprints"},
    "aykevl-earring-rgb36-v3": {"bezier Edge.Cuts", "odd rotations", "bottom-side footprints", "arc outline", "footprint-level Edge.Cuts",
                                "outline closed through footprint Edge.Cuts", "KiCad 9 format", "50+ footprints"},
    "jumperless-probe": {"custom pads", "chamfered pads", "roundrect odd ratio", "footprint-level Edge.Cuts", "arc outline", "slot drills"},
    "toraneko-mk3-panel": {"polygon Edge.Cuts", "circular Edge.Cuts cutouts", "cutouts", "NPTH-only footprints", "bottom-side footprints",
                           "roundrect odd ratio", "KiCad 9 format"},
    "wiimote-ir-sensor-kikit-panel": {"duplicate references", "same reference on different nets", "NPTH-only footprints", "bottom-side footprints",
                                      "custom pads", "50+ footprints", "many libraries", "KiCad 9 format"},
    "mumo-castellated-module": {"castellated edges", "offset drills", "inner copper layers", "custom pads", "bottom-side footprints", "KiCad 9 format"},
    "antmicro-m2-oculink-adapter": {"inner copper layers", "circular Edge.Cuts cutouts", "cutouts", "arc outline", "bottom-side footprints", "KiCad 9 format"},
    "glasgow-revC3": {"inner copper layers", "bottom-side footprints", "50+ footprints", "many libraries", "slot drills", "arc outline", "odd rotations",
                      "KiCad 6/7 format"},
    # the third set (2026-10-08): KiCad 5 files, blind / buried vias, flex, teardrops, net ties, project-only libraries, a V-cut panel
    "oxplot-fpx": {"KiCad 5 format", "slot drills", "custom pads", "bottom-side footprints", "mirrored text", "arc outline"},
    "fomu-pvt": {"KiCad 5 format", "inner copper layers", "blind/buried vias", "micro vias", "custom pads", "bottom-side footprints", "mirrored text",
                 "keepout rule areas", "arc outline"},
    "advanced-linear-motor": {"6 copper layers", "inner copper layers", "blind/buried vias", "NPTH-only footprints", "KiCad 8 format"},
    "placebo": {"rounded tracks", "teardrops", "outline only in footprint Edge.Cuts", "footprint-level Edge.Cuts", "footprints without a library prefix",
                "bottom-side footprints", "odd rotations", "KiCad 6/7 format"},
    "locust": {"net ties", "unrouted board", "copper graphics in footprints", "slot drills", "chamfered pads", "bottom-side footprints", "arc outline",
               "many libraries", "KiCad 6/7 format"},
    "adsbee-panel-saw-eval": {"V-cut panel", "duplicate references", "same reference on different nets", "keepout rule areas",
                              "footprints only in the project's own library", "KiCad 8 format"},
    "olimex-esp32-poe-revM2": {"inner copper layers", "bottom-side footprints", "mirrored text", "teardrops", "keepout rule areas", "slot drills",
                               "trapezoid pads", "copper-less pads", "footprints only in the project's own library", "odd rotations", "50+ footprints",
                               "many libraries", "KiCad 6/7 format"},
    "neopico-hd-fpc20": {"custom pads", "offset drills", "polygon Edge.Cuts", "cutouts", "KiCad 9 format"},
    "fly2040-cpu-flex": {"flex stackup", "polygon Edge.Cuts", "cutouts", "offset drills", "bottom-side footprints", "mirrored text", "groups",
                         "KiCad 6/7 format"},
}

# feature the DSL cannot express -> (tests it breaks, why[, bites]).  Strict: when the DSL learns it, the xfail turns into a failure
# here.  `bites(oss)` says whether the gap reaches the comparison in this variant at all: a net gap on pads the `library` variant
# already excuses as library drift (oxplot's MH1 against the installed one-pad MountingHole) cannot fail, so it is not xfailed there.
_NET_GAP_BITES = lambda oss: bool(set().union(*_multi_net_keys(oss["rec"])) - set(oss["drift"]))
GAPS = {
    # the first nine boards' gaps (bottom-side footprints, inner copper layers, bezier Edge.Cuts, circular Edge.Cuts cutouts) closed 2026-10-07
    "outline closed through footprint Edge.Cuts": (("test_outline_matches",),
        "the board-level Edge.Cuts items do not close (the earring's ring stops 3.4 mm short at the top) - the loop is completed by fp_line / fp_arc "
        "items inside a footprint (the hanger), which KiCad counts as part of the outline.  The DSL takes a Face and writes every edge of it at "
        "board level while the placed footprint re-emits its own items, so the outline would be drawn twice there; the harness builds no Face "
        "from an open board-level loop and compares the rest of the board on a stand-in rectangle"),
    "same reference on different nets": (("test_pad_flashes_match", "test_netlists_match_pad_by_pad"),
        "a KiKit panel keeps every copy's references (X1 twice ...) and prefixes its nets per copy (Board_0-GND / Board_1-GND); the DSL keys a "
        "pad's net by (ref, pad), so the two X1.2 pads can only share one net - the later `net()` call wins and the other copy's pads carry "
        "the wrong net name (a panel of identical copies with identical net names, like mozc's, is fine)", _NET_GAP_BITES),
    "pads sharing a number on different nets": (("test_pad_flashes_match", "test_netlists_match_pad_by_pad"),
        "one footprint instance has several pads with the same number on different nets (oxplot's MH1 / MH2: nine pads numbered 1, three "
        "on GND, six on no net - a KiCad 5 file, where a hand-edited pad kept its own net; pcbnew's netlist update gives every pad of a "
        "number the same net.  wiimote's U1: two pads numbered 4, each on its own `unconnected-(U1-NC-Pad4)` net, KiCad 8's one-net-per-"
        "unconnected-pad).  `Board.net()` keys a net by (ref, pad number) exactly as that netlist does, so the re-expression puts one net "
        "on every pad of the number and the flashes carry a .N attribute the original has differently or not at all", _NET_GAP_BITES),
    "outline only in footprint Edge.Cuts": (("test_outline_matches",),
        "the board has no Edge.Cuts item at board level at all: the whole outline is 14 fp_line items inside a locked footprint (placebo's "
        "PlaceboConnect_Cutout), which KiCad reads as the board edge.  The DSL takes a Face and writes it at board level while the placed "
        "footprint re-emits its own items, so the same outline would be drawn twice; the harness builds no Face (nothing to build it from) and "
        "compares the pads / drills / netlist on a stand-in rectangle around the footprints"),
}


def _multi_net_keys(rec: kp.BoardRec) -> tuple:
    """the (ref, pad number) keys whose pads carry more than one net name - split into ACROSS footprint instances (a panel's
    copies of X1 on Board_0-GND / Board_1-GND) and WITHIN one instance (oxplot's MH1: nine pads numbered 1, three on GND and
    six on no net).  The DSL keys a net by (ref, pad number), so neither can be re-expressed."""
    per_instance: dict = {}                                                  # (ref, number) -> [set of nets per instance]
    for fp in rec.footprints:
        nets: dict = {}
        for p in fp.pads:
            nets.setdefault(p.number, set()).add(p.net)
        for num, s in nets.items():
            per_instance.setdefault((fp.ref, num), []).append(s)
    within = {k for k, ss in per_instance.items() if any(len(s) > 1 for s in ss)}
    across = {k for k, ss in per_instance.items() if len(ss) > 1 and len(set().union(*ss)) > 1} - within
    return across, within


def _features(rec: kp.BoardRec) -> set:
    """what a board has, read off the file"""
    pads = [p for fp in rec.footprints for p in fp.pads]
    kinds = {e.kind for e in rec.edge}
    libs = {H.split_name(fp.name)[0] for fp in rec.footprints}
    refs = [fp.ref for fp in rec.footprints]
    f = set()
    if any(fp.layer == "B.Cu" for fp in rec.footprints): f.add("bottom-side footprints")
    if len(rec.copper_layers) > 2: f.add("inner copper layers")
    if any(fp.rot % 90 for fp in rec.footprints): f.add("odd rotations")
    if any(p.drill and p.drill[0] == "oval" for p in pads): f.add("slot drills")
    if any(p.offset != (0.0, 0.0) for p in pads): f.add("offset drills")
    if any(p.shape == "custom" for p in pads): f.add("custom pads")
    if any(p.shape == "trapezoid" for p in pads): f.add("trapezoid pads")
    if any(p.chamfer for p in pads): f.add("chamfered pads")
    if any(p.rratio is not None and p.rratio != 0.25 for p in pads): f.add("roundrect odd ratio")      # 0.25 is KiCad's default
    if any(not p.copper for p in pads): f.add("copper-less pads")                                      # mask- / paste-only
    if rec.castellated: f.add("castellated edges")
    if "arc" in kinds: f.add("arc outline")
    if "curve" in kinds: f.add("bezier Edge.Cuts")
    if "poly" in kinds: f.add("polygon Edge.Cuts")
    if "circle" in kinds and kinds - {"circle"}: f.add("circular Edge.Cuts cutouts")
    if len([e for e in rec.edge if e.kind in ("rect", "poly", "circle")]) > 1: f.add("cutouts")        # closed items beyond the outline
    if rec.fp_edge_items: f.add("footprint-level Edge.Cuts")
    ends = [p for e in rec.edge if e.kind in ("line", "arc", "curve") for p in (e.pts[0], e.pts[-1])]
    gaps = [min(math.hypot(p[0] - q[0], p[1] - q[1]) for j, q in enumerate(ends) if j != i) for i, p in enumerate(ends)]
    if gaps and 1e-5 < max(gaps) <= 0.02: f.add("Edge.Cuts gaps under 0.02 mm")
    if gaps and max(gaps) > 0.02 and rec.fp_edge_items: f.add("outline closed through footprint Edge.Cuts")
    if len(rec.footprints) >= 50: f.add("50+ footprints")
    if len(rec.footprints) >= 300: f.add("300+ footprints")
    if sum(1 for fp in rec.footprints if fp.pads and all(p.kind == "np_thru_hole" for p in fp.pads)) >= 2: f.add("NPTH-only footprints")   # mouse bites, tooling holes
    if len(libs) >= 8: f.add("many libraries")
    if any(":" not in fp.name for fp in rec.footprints): f.add("footprints without a library prefix")
    if len(set(refs)) < len(refs): f.add("duplicate references")                                        # a panel of copies
    across, within = _multi_net_keys(rec)
    if across: f.add("same reference on different nets")
    if within: f.add("pads sharing a number on different nets")
    if not rec.edge and rec.fp_edge_items: f.add("outline only in footprint Edge.Cuts")
    if len(rec.copper_layers) >= 6: f.add("6 copper layers")
    if rec.blind_buried_vias(): f.add("blind/buried vias")                                              # by the layers a via spans, not its flag
    if any(k == "micro" for k, _, _ in rec.via_spans): f.add("micro vias")
    if rec.track_arcs: f.add("rounded tracks")
    if rec.teardrop_zones: f.add("teardrops")
    if rec.keepout_zones: f.add("keepout rule areas")
    if rec.net_ties: f.add("net ties")
    if rec.vcut_texts: f.add("V-cut panel")
    if rec.flex: f.add("flex stackup")
    if rec.groups: f.add("groups")
    if rec.mirrored_texts: f.add("mirrored text")
    if rec.fp_copper_items: f.add("copper graphics in footprints")
    if rec.segments == 0 and not rec.vias: f.add("unrouted board")
    if rec.version < 20200000: f.add("KiCad 5 format")                                                  # 20171130: (module ...), bare symbols
    elif rec.version < 20240000: f.add("KiCad 6/7 format")
    elif rec.version < 20241229: f.add("KiCad 8 format")
    else: f.add("KiCad 9 format")
    return f


def _export(kicad, pcb: str, out: pathlib.Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    kicad.ok("pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu,Edge.Cuts", "-o", str(out) + "/", pcb)
    kicad.ok("pcb", "export", "drill", "--excellon-separate-th", "-o", str(out) + "/", pcb)
    f = {n: str(out / n) for n in os.listdir(out)}
    pick = lambda suffix: next((v for k, v in f.items() if k.endswith(suffix)), None)
    # by extension, not layer name: a board with user-named copper layers (hackrf's "C1F" / "C4B") exports `<name>-C1F.gtl`
    return dict(top=pick(".gtl"), bottom=pick(".gbl"), edge=pick(".gm1"), pth=pick("-PTH.drl"), npth=pick("-NPTH.drl"))


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
_AT_INLINE = re.compile(r"^(\t\t\((?:pad|fp_text) .*?\(at [-\d.]+ [-\d.]+)(?: ([-\d.]+))?\)", re.M)   # KiCad 5 / 6 / 7: `(pad "1" smd rect (at x y a) ...` inline
_TOK = r"(?:\"[^\"]*\"|[^\s()]+)"                                                                   # a quoted string or a bare symbol (KiCad 5 writes `(path /5F86B766)`, `(net 1 GND)`)
_STRIP = re.compile(rf"^\t\t(?:\(at [-\d. ]+\)|\(path {_TOK}\)|\(sheetname \"[^\"]*\"\)|\(sheetfile \"[^\"]*\"\))\n"
                    rf"|\s*\((?:net (?:\d+ )?{_TOK}|pinfunction \"[^\"]*\"|pintype \"[^\"]*\")\)", re.M)
_INDENT = re.compile(r"^((?:  )+)", re.M)
_FP_HEAD = re.compile(r"\n\t\((?:footprint|module) ")                                                 # `(module Lib:Name ...` is KiCad 5's spelling
_XY = re.compile(r"\((at|start|end|mid|center|xy|offset|rect_delta) (-?[\d.]+) (-?[\d.]+)((?: -?[\d.]+)?)((?: unlocked)?)\)")
_LAYER = re.compile(r'(?<=["\s])([FB])\.(?=(?:Cu|Paste|Mask|SilkS|Fab|CrtYd|Adhes)\b)')              # quoted (KiCad 6+) or bare (KiCad 5) layer names
_CORNER = {"top_left": "bottom_left", "bottom_left": "top_left", "top_right": "bottom_right", "bottom_right": "top_right"}


def _fmt(v: float) -> str:
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _unflip(body: str) -> str:
    """a footprint block KiCad stored on B.Cu, mirrored back to the way its library file has it (the inverse of FOOTPRINT::Flip,
    top/bottom): every y and angle negated (pads, texts, fp_* graphics, custom-pad primitives, drill offsets), F.* <-> B.*
    layers, chamfer corners top <-> bottom, text un-mirrored.  Textual, so the block stays KiCad's own text otherwise."""
    def xy(m):
        ang = m.group(4)
        if ang and m.group(1) == "at":
            ang = " " + _fmt(-float(ang))
        return f"({m.group(1)} {m.group(2)} {_fmt(-float(m.group(3)))}{ang}{m.group(5)})"
    body = _XY.sub(xy, body)
    body = _LAYER.sub(lambda m: "B." if m.group(1) == "F" else "F.", body)
    body = re.sub(r"\((chamfer(?: \w+)+)\)", lambda m: "(" + " ".join(_CORNER.get(w, w) for w in m.group(1).split()) + ")", body)
    body = re.sub(r"\(justify mirror\)\s*", "", body)
    body = re.sub(r"\(justify ([^)]*?) mirror\)", r"(justify \1)", body)
    return body


def _fp_sig(fp: kp.FootprintRec) -> tuple:
    """the pad geometry of a board footprint instance in its library frame (a bottom-side instance mirrored back), so two
    instances embedded under the same name can be told apart; pad angles are absolute in a board and left out"""
    m = -1 if fp.layer == "B.Cu" else 1
    return tuple(sorted((p.number, p.kind, p.shape, round(p.x, 4), round(m * p.y, 4), round(p.w, 4), round(p.h, 4), p.drill,
                         (round(p.offset[0], 4), round(m * p.offset[1], 4))) for p in fp.pads))


def _footprint_library(rec: kp.BoardRec, path: str, dest: pathlib.Path, installed_root: str | None = None) -> set:
    """<dest>/<Lib>.pretty/<Name>.kicad_mod for every footprint the board uses, so the DSL reads one directory.  With
    `installed_root` a footprint that exists in the installed KiCad library is symlinked from there (the `library`
    variant: what a user of the DSL gets; returns those names); the rest - and everything in the `embedded` variant -
    is the original's own embedded footprint written out.  Those blocks are cut out of KiCad's own text (balanced
    parentheses) and only what a board instance adds is removed: the placement, path / sheet, the nets / pin functions
    on pads; pad and text angles (absolute in a board, and omitted when 0) go back to the footprint frame.  A footprint
    placed on both sides is taken from a top-side instance (KiCad stores a flipped footprint mirrored); one that only
    ever sits on the bottom is mirrored back to its library form (`_unflip`) - the DSL flips it again when it places it
    on the bottom.  KiCad 6 / 7 files indent with two spaces: normalised to tabs first.
    A board can embed two different definitions under one name (glasgow's `C_0402_1005Metric` from two library versions:
    KiCad keeps each instance's copy): every further pad geometry (`_fp_sig`) is written as `Name__v2`, `__v3` ... and the
    instances in `rec` are renamed to match, so each is re-expressed with the footprint it was drawn with.
    A KiCad 5 file's `(module Lib:Name (layer B.Cu) ...)` blocks are cut the same way and written out with the KiCad 6+ head
    `(footprint "Name"`; the rest of the block (bare layer names, `(width w)` strokes, `(fp_text reference R1 ...)`, hex
    `(tedit ...)`) is what KiCad 6+ still reads as its legacy footprint syntax, so it stays."""
    text = open(path).read()
    if "\n  (footprint " in text or "\n  (module " in text:
        text = _INDENT.sub(lambda m: "\t" * (len(m.group(1)) // 2), text)
    blocks: dict = {}
    sigs: dict = {}                                                          # name -> [distinct pad signatures, file order]
    order = []
    i = 0
    while True:
        m = _FP_HEAD.search(text, i)
        if not m:
            break
        i = m.start()
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
        s = _fp_sig(fp)
        vs = sigs.setdefault(fp.name, [])
        if s not in vs:
            vs.append(s)
        k = vs.index(s)
        name = fp.name if k == 0 else f"{fp.name}__v{k + 1}"
        blocks.setdefault(name, []).append((fp, block))
        order.append(name)
        i = j
    assert len(order) == len(rec.footprints) and all(n.startswith(fp.name) for n, fp in zip(order, rec.footprints)), "footprint blocks and the parsed board disagree"
    for n, fp in zip(order, rec.footprints):
        fp.name = n
    from_installed = set()
    for name, inst in blocks.items():
        lib, fname = H.split_name(name)
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
        if fp.layer == "B.Cu":
            body = _unflip(body)
        body = re.sub(rf"^\t\((?:footprint|module) {_TOK}", f'\t(footprint "{fname}"', body, count=1)
        (d / f"{fname}.kicad_mod").write_text(body.replace("\n\t", "\n")[1:])
    return from_installed


def _library_drift(m, rec: kp.BoardRec, from_installed: set) -> dict:
    """{(ref, pad): why} for every pad whose embedded definition differs from the installed library's (the board was
    drawn with an older KiCad library): compared through kicad_parse only.  A renamed pad is listed under both numbers."""
    out, cache = {}, {}
    for fp in rec.footprints:
        lib, name = H.split_name(fp.name)
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
    assert rec.version >= 20171130, f"{name}: a KiCad 5+ board expected, version {rec.version}"
    features = _features(rec)
    libs = {H.split_name(fp.name)[0] for fp in rec.footprints}
    if not any(os.path.isfile(H.lib_path(cadpcb, *H.split_name(fp.name))) for fp in rec.footprints):
        features.add("footprints only in the project's own library")
    libdir = d / "footprints"
    shutil.rmtree(libdir, ignore_errors=True)                                # a re-run into the same PCB_TEST_OUT: the symlinks would already exist
    installed = _footprint_library(rec, orig, libdir, cadpcb.KICAD_FP if variant == "library" else None)
    twice = sorted({fp.name for fp in rec.footprints if "__v" in fp.name})
    if twice:
        conftest.REPORT.append(f"{name}: {len(twice)} footprint names embedded with more than one pad geometry, re-expressed per instance: {', '.join(twice)}")
    if variant == "library" and not installed:
        pytest.skip(f"{name}: no footprint of it is in the installed KiCad library (libraries: {', '.join(sorted(libs))}); only the embedded variant applies")
    face, face_error = None, ""
    try:
        face = H.face_from_edge_cuts(rec.edge)
    except Exception as e:                                                   # the rest of the board is still compared on a stand-in outline
        face, face_error = H.fallback_face(rec.edge, rec.footprints), f"{type(e).__name__}: {e}"
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
        tests, why, *bites = GAPS.get(feat, ((), ""))
        if test in tests and (not bites or bites[0](oss)):
            request.applymarker(pytest.mark.xfail(strict=True, reason=f"{oss['name']}: {feat} - {why}"))


def _report(oss, layer, matched, left, right, extra=""):
    line = (f"{oss['name']} [{oss['variant']} footprints] {layer}: {matched} match, {len(left)} only in original, "
            f"{len(right)} only in DSL{extra}")
    conftest.REPORT.append(line)
    return line


# ---------------------------------------------------------------------------------------------------- tests ----
def test_fixture_matches_sources(oss):
    """the fixture is byte-for-byte the upstream file SOURCES.md says it is"""
    rows = {m.group(1): m.group(2) for m in re.finditer(r"^\| `([^`]+)\.kicad_pcb(?:\.gz)?` \|.*\| `([0-9a-f]{64})` \|$", (FIX / "SOURCES.md").read_text(), re.M)}
    assert oss["name"] in rows, f"{oss['name']} has no row in SOURCES.md"
    assert hashlib.sha256(open(oss["orig"], "rb").read()).hexdigest() == rows[oss["name"]]


def test_fixture_is_what_we_think(oss):
    rec = oss["rec"]
    assert rec.footprints and (rec.edge or rec.fp_edge_items), "no footprints / no Edge.Cuts"
    # a board with no copper routing would not exercise the exclusion - unless it was picked as the placement-only case (locust)
    assert rec.segments > 0 or "unrouted board" in BOARDS[oss["name"]]
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
    for kind in ("pth", "npth"):
        a = kp.read_drills(oss["a"][kind]) if oss["a"][kind] else []
        b = kp.read_drills(oss["b"][kind]) if oss["b"][kind] else []
        # via holes belong to the routing, which the re-expression leaves out: drop the original's via drills
        via_holes = [("hole", x, y, d) for x, y, d in oss["vias"]]
        if kind == "pth":
            _, _, a = kp.match_multisets(via_holes, a, TOL, key=lambda r: r[0])   # right = the original's holes that are not vias
        matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: r[0])
        msg = _report(oss, kind.upper() + " drill", matched, left, right, extra=f" (excluded: {len(via_holes)} via holes)" if kind == "pth" else "")
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
    a = [_SIG(f) for f in A["flashes"] if f.ref != ""]
    b = [_SIG(f) for f in B["flashes"]]
    assert all(f.ref for f in B["flashes"]), "the re-expression must carry no vias"
    matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: (r[0], r[1]))
    lname = {"top": "F.Cu", "bottom": "B.Cu"}[layer]
    msg = _report(oss, lname + " pads", matched, left, right,
                  extra=f" (excluded: original {A['lines']} track segments + {A['arcs']} arcs + {A['regions']} zone regions + {len(vias)} vias; "
                        f"DSL {B['lines']}/{B['arcs']}/{B['regions']}/0; {sum(1 for r in a if r[0] in bottom)} flashes of bottom-side parts included)")
    detail = "\n".join(f"  original only: {r[:8]} {r[8:]}" for r in left[:5]) + "\n" + "\n".join(f"  DSL only: {r[:8]} {r[8:]}" for r in right[:5])
    # copper graphics inside footprints (fp_line / fp_arc / fp_poly on F.Cu - the probe's tip, a castellation's bar) are part of the
    # re-embedded tree and plot as lines / regions; the DSL may carry those and nothing more
    fp_cu = oss["rec"].fp_copper_items
    assert (B["lines"] == 0 and B["arcs"] == 0) or (fp_cu and B["lines"] + B["arcs"] <= A["lines"] + A["arcs"]), \
        f"the re-expression must carry no copper routing (DSL {B['lines']} lines + {B['arcs']} arcs; the original has {fp_cu} fp_* copper items)"
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
    an = sorted((f.ref, f.pad, f.net) for f in A["flashes"] if f.ref != "" and (f.ref, f.pad) not in drift)
    bn = sorted((f.ref, f.pad, f.net) for f in B["flashes"] if (f.ref, f.pad) not in drift)
    assert an == bn


def test_bottom_side_parts(oss):
    """the parts the original places on B.Cu are on B.Cu in the regenerated board, with every pad flash where KiCad put it
    (on both copper layers: a bottom part's THT pads flash on F.Cu too).  In the `library` variant every mismatch must be a
    pad whose embedded footprint differs from the installed one, as in test_pad_flashes_match."""
    bottom = oss["bottom"]
    if not bottom:
        pytest.skip("no bottom-side parts on this board")
    layers = {fp.ref: fp.layer for fp in oss["regen_rec"].footprints}
    wrong = sorted(r for r in bottom if layers.get(r) != "B.Cu")
    assert not wrong, f"{len(wrong)} of {len(bottom)} bottom-side parts are not on B.Cu in the DSL's board: {wrong[:8]}"
    if not any(p.copper for fp in oss["rec"].footprints if fp.ref in bottom for p in fp.pads):
        pytest.skip(f"the bottom-side parts ({', '.join(sorted(bottom))}) have no copper pads (a logo): on B.Cu, nothing to flash")
    total = 0
    for layer in ("top", "bottom"):
        a = [_SIG(f) for f in kp.read_copper(oss["a"][layer])["flashes"] if f.ref in bottom]
        b = [_SIG(f) for f in kp.read_copper(oss["b"][layer])["flashes"] if f.ref in bottom]
        matched, left, right = kp.match_multisets(a, b, TOL, key=lambda r: (r[0], r[1]))
        unexplained = {(r[0], r[1]) for r in left + right} - set(oss["drift"])
        msg = _report(oss, f"bottom-side parts on {layer}", matched, left, right,
                      extra=f" ({len(set(oss['drift']) & {(r[0], r[1]) for r in left + right})} library-drift pads)" if oss["variant"] == "library" else "")
        assert not unexplained, msg + f"\n  original only: {left[:5]}\n  DSL only: {right[:5]}"
        total += matched
    assert total > 0


_CJ_LAYER = lambda k: {"F.Cu": "top", "B.Cu": "bottom"}.get(k, "inner" + k[2:-3])    # KiCad copper name -> Circuit JSON layer name


def test_blind_buried_vias_are_refused(oss):
    """a board whose vias do not all span the whole stack (fomu's micro / buried vias on 4 layers, the linear motor's 60
    blind / buried vias on 6): the DSL has no such via - handed the original's vias as routed copper (`kicad_pcb(traces=...)`,
    Circuit JSON via points with from_layer / to_layer) it must refuse with a ValueError naming the feature, not write them as
    through vias or crash; the same board's through vias (and oxplot's `(via blind ...)` that spans F.Cu to B.Cu anyway) go in."""
    if oss["variant"] != "embedded":
        pytest.skip("the DSL's via check does not depend on the footprints")
    rec = oss["rec"]
    if not rec.vias:
        pytest.skip("no via on this board (unrouted)")
    bb = rec.blind_buried_vias()
    flagged = [(k, a, c) for k, a, c in rec.via_spans if k != "through"]
    b, net = oss["board"], next(iter(oss["board"].nets))
    via = lambda x, y, a, c: dict(type="pcb_trace", pcb_trace_id="pcb_trace_0", source_trace_id="source_trace_0",
                                  route=[dict(route_type="via", x=x, y=-y, from_layer=_CJ_LAYER(a), to_layer=_CJ_LAYER(c))])
    traces = [dict(type="source_trace", source_trace_id="source_trace_0", display_name=net)]
    if bb:
        with pytest.raises(ValueError, match="blind / buried via"):
            b.kicad_pcb(traces + [via(*bb[0][:2], bb[0][3], bb[0][4])])
    outer = {rec.copper_layers[0], rec.copper_layers[-1]}
    through = sorted(((k == "through", x, y, a, c) for (x, y, _), (k, a, c) in zip(rec.vias, rec.via_spans) if {a, c} == outer))   # a flagged one first
    if through:
        assert len(kp.children(kp.parse(b.kicad_pcb(traces + [via(*through[0][1:])])), "via")) == 1
    if bb or flagged:
        conftest.REPORT.append(f"{oss['name']}: {len(bb)} of {len(rec.vias)} vias are blind / buried / micro "
                               f"({', '.join(sorted({f'{a}-{c}' for _, _, _, a, c in bb})) or 'none'}; written with the flags "
                               f"{', '.join(sorted({k for k, _, _ in flagged})) or 'none'}): the DSL refuses the former by ValueError, takes the rest")


def test_netlists_match_pad_by_pad(oss):
    a = oss["rec"].pad_nets()
    regen = oss["regen_rec"]
    regen.footprints = [fp for fp in regen.footprints if not fp.name.startswith("openworkshop:")]   # the DSL's own NPTH footprints for circular cutouts
    b = regen.pad_nets()
    drift = set(oss["drift"])                                           # library variant: a pad the installed library renamed cannot carry its net
    assert set(a) - drift == set(b) - drift, (set(a) ^ set(b)) - drift
    diff = {k: (a[k], b[k]) for k in a if k not in drift and a[k] != b[k]}
    conftest.REPORT.append(f"{oss['name']} [{oss['variant']}] netlist: {len(a)} (ref, pad) keys, {len(diff)} differ")
    assert not diff, diff
    nets_a = {n for v in a.values() for n in v if n}
    assert set(oss["board"].nets) == nets_a
