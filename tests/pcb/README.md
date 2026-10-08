# Conformance tests for the build123d -> KiCad board DSL (`openworkshop.pcb`, formerly `cadpcb.py`)

The question these answer: **does what the DSL writes mean the same thing to KiCad, and does it reproduce real
open-source boards?**  Every check goes through an independent reader (`kicad_parse.py`, written here, no code shared
with the module) and through KiCad's own `kicad-cli`, with Gerbers / Excellon read back by `gerbonara`.

Nothing in here is specific to the arenas repo: the module under test is found by path (see *Running*), the fixtures are
self-contained, and the suite can be dropped into the openworkshop repo as `tests/` next to `openworkshop/pcb.py`.

## Layout

| file | what |
|---|---|
| `conftest.py` | finds and loads the module under test by file path; serialised `nice`d `kicad-cli` runner (with the libprotobuf shim lookup); output dir; the terminal summary |
| `kicad_parse.py` | the independent oracle: s-expression parser, `.kicad_mod` / `.kicad_pcb` readers (pads, nets, Edge.Cuts, vias and their layer spans; KiCad 5 `(module ...)` files and centre / angle arcs included), IPC-D-356 reader, Gerber / Excellon summaries via gerbonara, tolerant multiset matcher |
| `helpers.py` | DSL-side helpers: build123d Face from Edge.Cuts, the round-trip board, re-expression of a parsed board through the DSL, KiCad pad semantics (offset / rotation / custom primitives) |
| `test_footprints.py` | 1. footprint fidelity (15 footprints across 9 libraries) |
| `test_roundtrip.py` | 2. DSL board -> kicad-cli DRC / Gerbers / drill / STEP / IPC-D-356 |
| `test_oss_boards.py` | 3. twenty-seven open-source boards re-expressed through the DSL, Gerber-vs-Gerber; the gap table |
| `test_jlc.py` | 4. JLCPCB `bom.csv` / `cpl.csv` / `bom_full.csv` |
| `test_bottom_side.py` | 5. bottom-side parts: KiCad's flip storage, Gerbers against a top twin turned over, pos / CPL, Circuit JSON, `solid()` |
| `test_layers_curves.py` | 6. a 4-layer board (`Board(layers=4)`): layer table + stackup through kicad-cli (ids against a KiCad-9-written board), inner-layer Gerbers; bezier / spline / ellipse outlines as `gr_curve` within tolerance; blind / buried via points refused |
| `test_cutouts.py` | 7. circular inner wires as NPTH (default) or `gr_circle` cutouts; slot cutouts as a closed Edge.Cuts chain; `Board.hole()` |
| `fixtures/oss/` | the twenty-seven boards (big ones gzipped) + `SOURCES.md` (repo, commit, licence, sha256) |

## Running

```bash
pip install -e ".[pcb,dev]" build123d           # shapely, pytest, gerbonara; plus kicad-cli and the KiCad libraries on the box
python -m pytest tests/pcb -q -ra               # from the openworkshop repo root (CI runs this job on ubuntu with KiCad 9)
PCB_TEST_OUT=/tmp/pcb-dsl python -m pytest tests/pcb   # keep every board / Gerber / STEP / drc.json it produced
```

Needs: `pytest`, `gerbonara` (dev dependency group), `build123d` + `shapely` (the module's own needs), KiCad's footprint
library on disk (`KICAD_FOOTPRINTS`, default `/usr/share/kicad/footprints`), and `kicad-cli` (KiCad 9 or 10).

| env | meaning |
|---|---|
| `CADPCB_PATH` | the module file to test; otherwise `../cadpcb.py`, `../openworkshop/pcb.py`, then the installed `openworkshop/pcb.py` |
| `KICAD_CLI` | the binary (default `kicad-cli` on PATH) |
| `KICAD_CLI_LD_LIBRARY_PATH` | a directory holding `libprotobuf.so.36` when the system's is older (the hub's partial Arch upgrade); `~/.claude/jobs/*/tmp/pb36/usr/lib` is tried automatically |
| `PCB_TEST_OUT` | where to leave the outputs (default: pytest's tmp dir, printed in the summary) |

Without a runnable `kicad-cli` the tests that need it are **skipped** (shown in the `-ra` summary), not passed.  Every
kicad-cli call runs under `nice -n 10`, one at a time (~220 calls, 3-5 min on the hub; 530 passed / 118 skipped / 16 xfailed
on 2026-10-08 with kicad-cli 10.0.6 - the skips are the `library` variant of the eight boards whose footprints exist only in
their own project library (8 tests x 8 boards), the `library` variant of `test_blind_buried_vias_are_refused` (19, it owes nothing
to the footprints), and the checks a board has nothing for: no bottom-side part (13), no via (3), a bottom part with no copper (3)).

## What each test proves

**1. Footprint fidelity** (`test_footprints.py`), 15 footprints: SOIC-8, SOT-23, LQFP-48, DIP-16, R/C 0603, CP_Elec 6.3x5.4,
CP_Radial D5, JST XH 1x05, PinHeader 1x04 / 2x03, USB Micro-B Molex (oval drills), Pico SMD, Pico THT, MountingHole M3.

- `test_pads_match_independent_parse` — `kicad_footprint()` pads equal `kicad_parse`'s reading of the same `.kicad_mod`:
  number, kind, shape, position (y flipped), size (swapped for pads rotated 90 inside the footprint, widened to the
  primitives of custom pads), drill, copper layers, resolved 3D model path.
- `test_slot_drill_is_the_long_dimension` — the DSL's documented lossy rule for `(drill oval a b)`: `max(a, b)`.
- `test_reread_*` — a board with all 15 footprints -> `.kicad_pcb` -> `kicad-cli pcb drc --save-board` (KiCad re-serialises it,
  format 20260206 on KiCad 10) -> `kicad_parse`: every footprint at the DSL's position / rotation, every pad identical to
  the library file (position, size, rotation, drill, offset, layers, custom primitives' extent).
- `test_gerber_flashes_match_pad_xy` — the same footprints at 0 / 90 / 180 / 270 -> `kicad-cli pcb export gerbers` -> for every
  copper pad the flash KiCad drew (position = bounding-box centre, size) equals `Placed.pad_xy()` and the DSL's pad size
  within 0.01 mm, on F.Cu and B.Cu (1120 flashes).
- `test_offset_rotated_custom_and_paste_only_pads_pico_smd` — the pads that are not just the anchor shape at the pad
  position: `(drill (offset dx dy))` (Pico SMD D1 / D3 copper sits 0.8 mm off), custom pads rotated inside their footprint
  (D2's primitive offset turns with the pad's angle), and paste-only pads (`(layers "F.Paste")`, 47 on the Pico SMD —
  no copper layers, so no port / flash / JLC pad).  Pinned as a strict xfail while these were real deviations; fixed in
  `kicad_footprint()` on 2026-10-07, so it is an ordinary test now.
- `test_hex_timestamp_stays_a_symbol` — a KiCad 5 / 6 footprint's `(tedit 527E5841)` (hex edit stamp) is kept as the symbol
  it is and written back verbatim.  Found by hackrf-one: Python's `float()` reads that token as 5.27e5843 = inf and the
  serialiser crashed on it (`50997E90` would silently have become 5.1e94); the DSL's parser now takes only plain decimals,
  the only numbers KiCad writes, as numbers.
- `test_unlocked_text_position_turns_with_the_part` — a KiCad 7 footprint stores a text's position as `(at x y unlocked)` or
  `(at x y 180 unlocked)` (placebo's, olimex's).  The writer added the part's rotation to whatever followed `x y`, so the symbol
  crashed it (`str + float`; found by the third fixture set).  The angle is now the number after `x y` (0 when absent) and
  `unlocked` is kept after it, on top and bottom parts (`_turn`).

**2. Round trip through KiCad** (`test_roundtrip.py`): a 60 x 40 mm rounded-rectangle board (4 lines + 4 arcs), two 3.2 mm
NPTH, an 8 x 3 mm cutout, SOIC-8 + 0603 + JST XH 1x02, nets GND / SIG, one hand trace, a GND pour on F.Cu.

- `test_drc_zero_errors_zero_unconnected` — `kicad-cli pcb drc --refill-zones` on the `.kicad_pcb` + `.kicad_pro`: 0 error-severity
  violations, 0 unconnected items; the only warnings are the headless `lib_footprint_issues` (no fp-lib-table in a bare run).
- `test_exports_succeed` — Gerbers (all layers), Excellon PTH / NPTH, IPC-D-356, board-only STEP and a full STEP with the
  footprints' 3D models all succeed and exist.
- `test_step_bbox_equals_face` — the board-only STEP's XY bounding box equals the build123d Face's within 0.05 mm (and
  `Board.bbox`); its volume equals face area x body thickness within 1 %, i.e. the holes and the cutout are in the solid.
  Note: KiCad's board body is 1.51 mm for a 1.6 mm board (1.6 - 2 x 0.035 Cu - 2 x 0.01 mask), so Z is checked as a range.
- `test_pcb_netlist_equals_board_nets` — the netlist KiCad exports **from the board** (`pcb export ipcd356`, parsed by
  column) equals `Board.nets` exactly, and so does the net on every pad of the re-saved board.
- `test_edge_cuts_and_drills` — the Edge.Cuts Gerber has 8 lines + 4 arcs with the Face's extent, each arc centred r inside
  its corner, the 4 cutout edges; NPTH drill = the two CAD holes at their CAD positions (y-up frame); PTH = J1's two pins.

**3. Open-source boards** (`test_oss_boards.py`), twenty-seven boards in three sets, `fixtures/oss/SOURCES.md` (repo, commit, licence, sha256 - checked by
`test_fixture_matches_sources`; boards over 1 MB are stored gzip-compressed).  Each is parsed by `kicad_parse`, re-expressed through
the DSL (Face from Edge.Cuts, `kicad_footprint()` by `Lib:Name`, `place(..., center_pads=False)` at the original origin / rotation, the
original net on every pad, no tracks / vias / zones), both exported with the same `kicad-cli` calls.  Two variants: **library**
(footprints from the installed KiCad library where the footprint exists there - what a user of the DSL gets - the board's own
project-library footprints embedded; skipped when nothing on the board is in the installed library) and **embedded** (the originals'
own footprints, written out as a temporary `.pretty` library - isolates the DSL from library drift).  What a board has is detected
from the file (`_features`) and checked against what it was picked for (`BOARDS`); a feature the DSL cannot express is in `GAPS`,
which turns the test it breaks into a **strict xfail** naming the feature (the gap list below).  Bottom-side parts take part in every
pad / drill / netlist comparison (placed with `layer="bottom"`) and are reported on their own by `test_bottom_side_parts` as well; the
embedded library of a footprint that only ever sits on the bottom is mirrored back to its library form first (`_unflip`), since the
DSL does the flip itself.  A circular inner wire of the Face came from a `gr_circle` on Edge.Cuts, so the re-expression uses
`Board(..., inner_circles="cutout")` to send it back there (the DSL's default is an NPTH drill, which is what a CAD mounting hole wants).

| board | KiCad | layers | footprints (B.Cu) | libs | picked for | result |
|---|---|---|---|---|---|---|
| pi-pico-mpu6050-light | 9 | 2 | 14 (0) | 7 | the original pair: Pico, QFN, JST, barrel jack | pass |
| stepper-playground-12v-pico | 9 | 2 | 17 (0) | 9 | the original pair: THT, mounting holes, terminal block | pass (library: 6 drift pads) |
| hsp-usb-led | 9 | 2 | 6 (0) | 4 | rounded-rectangle outline (4 arcs), USB-C slot drills | pass (library: USB-C shell pad renamed S1 -> SH, drift) |
| capacitive-soil-moisture-sensor | 6 format | 2 | 23 (14) | 9 | 45 / 135 deg rotations, `fp_text reference`, arcs, bottom parts | pass (59 bottom-side flashes; library: 47 drift pads on B.Cu) |
| generic-pan-tilt-motor | 8 | 2 | 74 (11) | 14 | 14 custom pads, a pad-less logo, test points, fiducials | pass (16 bottom-side flashes) |
| generic-pan-tilt-main | 8 | 2 | 91 (78) | 17 | 8 `gr_rect` cutouts, slots, custom pads, 78 bottom parts | pass (350 + 34 bottom-side flashes on B.Cu / F.Cu, 78 PTH + 8 NPTH) |
| pico-ice-rev3 | 8 | **4** | 101 (32) | 14 | castellated custom pads, slots, 4 layers | pass (re-expressed as `layers=4`; 83 bottom-side flashes) |
| antmicro-usb-c-power-adapter | 9 | **4** | 124 (46) | 1 | trapezoid pads, 34 zones, 4 um Edge.Cuts step, project-only library | embedded only: pass (`layers=4`; 133 + 4 bottom-side flashes) |
| crkbd-corne-cherry-hotswap | 7 format | 2 | 180 (168) | 12 | 100 bezier edges, 12 circle cutouts, 184 footprint-level Edge.Cuts, 113.88 deg keys, 44 slots | pass: pads (648 + 50 bottom-side flashes), 286 NPTH + 58 PTH, netlist, outline (the 100 beziers as `gr_curve`, 5192 Gerber segments, + the 12 `gr_circle` cutouts) |
| hackrf-one | 6 format | **4** | **437** (0) | 3 | the volume case: 1639 pads, ±45 / ±135 deg, 14 arcs, user-named copper layers, 19 footprints without a library prefix, mask-only pads, hex `tedit` stamps | embedded only: pass (1616 + 305 flashes, 297 PTH, 1369 netlist keys; two DSL fixes came out of it, below) |
| mozc-doublesided-main-panel | 8 | **4** | 234 (189) | 6 | a V-cut panel of 9 copies: every reference 9 times, 396 NPTH of which 216 oval NPTH slots, 189 bottom parts | pass (297 + 855 flashes of which 207 + 765 bottom-side; library: 7 drift pads x 9 copies) |
| aykevl-earring-rgb36-v3 | 9 | 2 | 63 (5) | 5 | 4 beziers + 4 arcs, 50 distinct rotations, outline closed by the hanger footprint's Edge.Cuts | pads / drills / netlist pass (217 + 11 flashes); **outline: gap** (below) - `test_outline_matches` fails before comparing anything, so its 4 beziers + 4 arcs are not compared at all |
| jumperless-probe | 8 | 2 | 18 (0) | 1 | 80 custom + 10 chamfered + 311 odd-ratio roundrect pads, 80 footprint-level Edge.Cuts, copper graphics in footprints, two 58 mm flat arcs | embedded only: pass (415 + 341 flashes, 338 PTH, 93 Edge.Cuts items; the flat arcs exposed the 4-decimal rounding, fixed below) |
| toraneko-mk3-panel | 9 | 2 | 21 (6) | 4 | `gr_rect` frame + 9 `gr_poly` cutouts (28-123 vertices) + 1 `gr_circle`, mouse bites as a 48-NPTH footprint | pass (428 Edge.Cuts items, 54 NPTH, 96 + 36 flashes; library: 12 drift pads) |
| wiimote-ir-sensor-kikit-panel | 9 | 2 | 92 (12) | 8 | KiKit 2-up: 64 `NPTH-0.5mm` mouse-bite footprints (`REF**`), 6 tooling holes, the same references twice with per-copy net names | outline / drills / bottom-side parts pass (46 Edge.Cuts, 70 NPTH); the 46 + 52 flashes match geometrically but `test_pad_flashes_match` is xfailed as a whole in both variants (its last assertion, the `.N` net attribute, is the gap), so only the report line says so, not a passing test - which also leaves its 4 custom pads (JP1) asserted by no test; **net names: gap** (below) |
| mumo-castellated-module | 9 | **4** | 25 (1) | 2 | `(castellated_pads yes)`, 26 oval edge pads with 12 drill offsets, 2 custom pads, a pad-less logo on B.Cu | embedded only: pass (99 + 25 flashes, 25 PTH; the bottom-side check skips - the logo has nothing to flash) |
| antmicro-m2-oculink-adapter | 9 | **4** | 25 (10) | 1 | 22 `gr_circle` cutouts + 17 lines + 4 arcs on Edge.Cuts, project-only library | embedded only: pass (65 Edge.Cuts items incl. the 22 circles, 97 + 53 flashes, 20 bottom-side) |
| glasgow-revC3 | 7 format | **4** | 272 (94) | 14 | 1149 pads, 94 bottom parts, 45 deg, two footprint names each embedded with two pad geometries | pass (965 + 321 flashes, 169 bottom-side, 149 PTH + 4 NPTH, 1075 netlist keys; library: 557 drift pads, the KiCad 7 0402 / 0603 / 0805 libraries vs 10.0) |
| oxplot-fpx | **5 format** | 2 | 36 (19) | 9 | the KiCad 5 case: `(module ...)`, `fp_text` everywhere, bare symbols, `(width)` strokes, centre / angle arcs; 4 USB-C slots, 8 custom pads with anchors, 62 mirrored texts, 60 deg, a stray `(via blind ...)` spanning F.Cu-B.Cu | outline (the 4 legacy arcs), drills (24 PTH), bottom parts (76 flashes) pass in both variants; **nets: gap** (below) - MH1 / MH2 have nine pads numbered 1 on two nets, so `test_pad_flashes_match` / `test_netlists_match_pad_by_pad` xfail in the embedded variant (the 80 + 100 flashes match per the report line, 139 keys / 2 differ) and pass in the library variant, where those pads are drift (the installed MountingHole has one pad; 92 drift pads in all, 16 + 14 of them in the Gerbers).  The 8 custom pads with anchors are U3's (`Package_DFN_QFN:VQFN-20`), a drifted footprint, so no passing test asserts them - a KiCad 5 custom pad is proven by fomu's 36 only |
| fomu-pvt | **5 format** | **4** | 55 (50) | 1 | 196 micro + 53 buried vias (no through via at all), 36 custom pads with anchors, 74 paste-only pads, 138 mirrored texts, 6 legacy arcs, a keepout | embedded only: pass (95 Edge.Cuts items, 12 + 136 flashes of which the 136 bottom-side, 172 netlist keys; 0 PTH - every hole is a via); `test_blind_buried_vias_are_refused`: the oracle classes all 249 as micro / buried, the first of them handed to the DSL is refused (no through via to write) |
| advanced-linear-motor | 8 | **6** | 10 (0) | 3 | **six copper layers** through kicad-cli (`Board(layers=6)`: In3.Cu / In4.Cu ids 8 / 10, five dielectrics), 60 vias all blind / buried (F-In1, In2-In3, In4-B), 4 NPTH mounting holes | pass (`test_layer_stack` on 6 layers, 4 Edge.Cuts, 5 PTH + 4 NPTH, 13 + 5 flashes, 17 keys); `test_blind_buried_vias_are_refused`: the oracle classes all 60 as blind / buried, the first of them handed to the DSL is refused by ValueError; library: 8 pads differ from the installed library by the oracle's comparison, none of them in the Gerbers |
| placebo | 7 format | 2 | 18 (1) | 9 | 102 rounded tracks (`(arc ...)` on copper), 50 teardrop zones, `unlocked` text positions, 2 footprints without a library prefix, 8 deg; **no board-level Edge.Cuts** - the outline is 14 `fp_line` items in a locked footprint | drills (24 PTH + 3 NPTH), pads (76 + 24 flashes, the arcs / teardrops excluded and counted), netlist (77 keys) pass on a stand-in rectangle; **outline: gap** (below); library: 45 drift pads |
| locust | 7.99 format | 2 | 42 (3) | 16 | 5 `NetTie` footprints with `net_tie_pad_groups` (pads on different nets joined by copper `fp_poly`), **unrouted** (0 segments / vias), 4 slots, 1 chamfered pad, 20 mask-only pads | pass (16 Edge.Cuts, 43 PTH + 6 NPTH, 307 + 53 flashes, 282 netlist keys - each net-tie pad keeps its own net; the DSL re-emits the 5 footprints' `net_tie_pad_groups` with their tree, seen in the regenerated board but asserted by nothing; library: 143 drift pads, 58 + 4 of them in the Gerbers and 26 drill differences at them) |
| adsbee-panel-saw-eval | 8 | 2 | 36 (0) | 2 | a V-cut panel of 12 coupons (`V-CUT` texts), J1 / J2 / X1 twelve times with per-copy nets, 12 keepout rule areas, project-only libraries | embedded only: outline (14 lines) passes; **net names: gap** (the KiKit row below), as wiimote - `test_pad_flashes_match` is xfailed as a whole, so its 144 + 48 flashes match only per the report line and no passing test asserts the coupons' pads; netlist: 10 (ref, pad) keys, every one differs |
| olimex-esp32-poe-revM2 | 7 format | **4** | 143 (84) | 12 | heavy B.Cu (84 parts, 191 mirrored texts), 608 teardrop zones + 8 keepouts, 10 trapezoid + 105 mask-only pads, 6 slots, 13 NPTH, 135 deg, project-only libraries | embedded only: pass (8 Edge.Cuts, 62 PTH + 13 NPTH, 239 + 308 flashes of which 30 + 276 bottom-side, 452 netlist keys; the zones excluded as 287 + 328 Gerber regions) |
| neopico-hd-fpc20 | 9 | 2 | 3 (0) | 3 | 54 custom pads with `(anchor ...)` primitives AND a `(drill (offset ...))` each, Edge.Cuts = 3 `gr_rect` cutouts inside a `gr_poly` | pass (24 Edge.Cuts items, 54 PTH, 77 + 54 flashes, 76 keys; library: 0 drift) |
| fly2040-cpu-flex | 7 format | 2 | 9 (5) | 2 | a flex circuit (0.025 mm Polyimide core), outline = 5 `gr_poly` (tail + 4 finger slots), 4 drill offsets, 2 groups, 5 bottom parts | pass (32 Edge.Cuts, 3 PTH, 7 + 29 flashes of which 26 bottom-side, 33 keys; library: 4 drift pads) |

The third set needed the oracle to read KiCad 5 (`kicad_parse.read_board`: `(module ...)` nodes, `(width w)` strokes, a via's drill
from the setup's `via_drill` / `uvia_drill`, and Edge.Cuts arcs stored as centre / start point / sweep angle converted to the
start / mid / end triple - the sense (positive = clockwise on the y-down screen) checked against kicad-cli's own Edge.Cuts Gerber
on all 10 arcs of oxplot and fomu), plus three harness additions: a `(module ...)` block is cut out and written as a `.kicad_mod`
with the KiCad 6+ head `(footprint "Name"` and its instance-only nodes stripped whether quoted or bare (`(path /5F86B766)`, `(net 1
GND)`), the un-flip of a bottom-only footprint swaps bare as well as quoted `F.*` / `B.*` layer names, and a board with no Edge.Cuts
item at board level gets a stand-in rectangle around its footprints (`fallback_face`).  The oracle also reads each via's layer span
and kind (`via_spans`, `blind_buried_vias()` - by the layers, so oxplot's mis-flagged through via is a through via), track arcs,
teardrop / keepout zones, net ties, V-cut texts, a Polyimide stackup, groups and mirrored texts for `_features`.  Two DSL fixes
came out of it (sections 1 and 6): `unlocked` text positions, and blind / buried via points refused.

The second set needed four harness additions, no DSL change: a footprint placed without a library prefix (hackrf's KiCad 5
imports) is filed under the library `local` (`helpers.split_name`); a name the board embeds with two different pad geometries
(glasgow's 0402 / 0603 from two library versions - KiCad keeps every instance's copy) is written out as `Name__v2` and the
instances renamed, so each is re-expressed with the footprint it was drawn with (`_fp_sig`); copper `fp_line` / `fp_arc`
graphics inside footprints (the probe's tip, antmicro's) are part of the re-embedded tree, so the "no copper routing" check
allows the DSL's copper Gerber as many lines as the original has footprint-level copper items; and the Gerber files are picked
by extension, since a board with user-named copper layers exports `-C1F.gtl` instead of `-F_Cu.gtl`.  The oracle reads the
pad `chamfer` / `roundrect_rratio` and the `castellated_pads` setting for `_features`.

Gap table (feature -> boards -> what the DSL does; every row is a strict xfail, so the day the DSL learns it the suite says so).
A row xfails the *whole* named test for that board, not just the assertion the gap breaks: while a row is open, every other
check in that test is reported (the summary lines) but not asserted for that board - `test_pad_flashes_match` on wiimote
fails at its last assertion (the `.N` net attribute) after the geometry matched, `test_outline_matches` on the earring fails at
its first (no Face), before any Edge.Cuts comparison.  A row can carry a `bites(oss)` predicate: the net rows apply only when a
pad they concern is compared at all - in the `library` variant oxplot's MH1 pads are library drift (the installed MountingHole has
one pad) and excused before the net check, so there the test is not xfailed and passes.  The first set's four gaps closed on
2026-10-07 (below); the second set opened two, the third set two more:

| feature | boards | DSL status |
|---|---|---|
| outline closed through footprint Edge.Cuts | earring | the board-level Edge.Cuts stop 3.4 mm short and the hanger footprint's 2 `fp_line` + 1 `fp_arc` close the loop (KiCad reads all of it as the outline).  The DSL takes a Face and writes every edge at board level while the placed footprint re-emits its own items, so the same edge would be drawn twice; the harness builds no Face from the open loop and compares the pads / drills / netlist on a stand-in rectangle.  `test_outline_matches` xfails |
| outline only in footprint Edge.Cuts | placebo | no Edge.Cuts item at board level at all: the whole outline is 14 `fp_line` items inside the locked footprint `placebo:PlaceboConnect_Cutout`, which KiCad reads as the board edge.  Same DSL limit as the row above (the placed footprint re-emits the items, so a Face built from them would draw the outline twice); the harness has nothing to build a Face from and compares the rest on a rectangle around the footprints.  `test_outline_matches` xfails |
| same reference on different nets | wiimote (KiKit), adsbee | a KiKit-style panel keeps each copy's references and prefixes its nets per copy (`Board_0-GND` / `Board_1-GND`; adsbee's `J1` twelve times on `Board_0-/RF_IN` ... `Board_11-/RF_IN`); `Board.net()` keys a pad's net by `(ref, pad)`, so the twelve `J1.1` pads can only share one net - the later call wins and the other copies' flashes carry the wrong `.N` attribute.  A panel of identical copies with identical net names (mozc's 9) is fine.  `test_pad_flashes_match` (its net check) and `test_netlists_match_pad_by_pad` xfail |
| pads sharing a number on different nets | oxplot, wiimote | one footprint instance has several pads with the same number on different nets: oxplot's `MH1` / `MH2` (nine pads numbered 1, three on GND, six on no net - a KiCad 5 file where hand-edited pads kept their own net; pcbnew's netlist update gives every pad of a number the same net), wiimote's `U1` (two pads numbered 4, each on its own `unconnected-(U1-NC-Pad4)` net, KiCad 8's one net per unconnected pad).  `Board.net()` keys a net by `(ref, pad number)` exactly as that netlist does, so every pad of the number gets one net.  The same two tests xfail, in the variant where the pads are compared |

Closed gaps (were strict xfails; the row says what the DSL does now):

| feature | boards | DSL status |
|---|---|---|
| bottom-side footprints | soil-moisture, pan-tilt motor + main, pico-ice, antmicro, corne | `place(..., layer="bottom")`: `kicad_pcb()` writes the library tree the way KiCad's top/bottom flip stores it (`_flip_tree`: pad y mirrored, pad and text angles negated, `F.*` <-> `B.*` layers, chamfers top <-> bottom, text mirrored) at `(layer "B.Cu") (at x -y rot)`; `Placed.pad_xy()` / `pad_layers()` mirror the same way for Circuit JSON, the CPL and `solid()`.  All six fixtures store their bottom parts this way (0 of 178 library-matched bottom footprints use the left/right mirror).  Section 5 below is the focused test |
| circular Edge.Cuts cutouts (`gr_circle` inside the outline) | corne | `Board(..., inner_circles="cutout")` keeps a circular inner wire on Edge.Cuts (`gr_circle`); the default `"npth"` still makes it a non-plated drill (a CAD mounting hole), and `Board.hole(at, d)` adds one explicitly.  Corne's 12 circles: Edge.Cuts match, NPTH 286 / 286 |
| inner copper layers (4-layer) | pico-ice, antmicro | `Board(layers=4)` (2 / 4 / 6 accepted; only 2 and 4 are tested) writes the KiCad 9/10 layer table (copper on the even ids: F.Cu 0, In1.Cu 4, In2.Cu 6, B.Cu 2) and a `(setup (stackup ...))` with the copper / dielectric layers summing to the board thickness; `reexpress()` passes the original's copper count, so `test_layer_stack` passes for pico-ice and antmicro; section 6 below round-trips a 4-layer board through kicad-cli |
| bezier (`gr_curve`) Edge.Cuts | corne | a BEZIER edge is written as `gr_curve` with its four control points (6 decimals, KiCad's own precision), a BSPLINE as one `gr_curve` per cubic span (OCC's span-to-bezier conversion; rational or higher-degree curves and ellipses are first approximated by a cubic BSpline within `CURVE_TOL` = 1 um and split the same way, no longer a wrong 3-point arc or 0.25 mm lines); the points keep the direction the curve was drawn in (the writer walks `wire.edges()`, not `order_edges()`, which rebuilds a reversed edge's curve backwards), because KiCad's polyline of a bezier depends on it.  Corne's 100 beziers match segment for segment, so with the 12 circles its `test_outline_matches` passes |

Two oracle fixes came with it (`kicad_parse`): `match_multisets` pairs records equal to 1e-6 before the greedy pass within `tol`
(a bezier plots as segments shorter than 0.01 mm, which the greedy pass alone paired with their neighbours and left 32 chain ends
unmatched), and `read_outline` orders a line's endpoints with coordinates within 1 um counting as equal (a line vertical to within
1 um in one file and exactly vertical in the other sorted differently).

Proven by the new boards (no gap): rotations off the 90 deg grid (pad positions AND sizes - the library tree is re-embedded, KiCad
draws it), oval / slot drills, custom-primitive and trapezoid pads, castellated edge pads, arc outlines, `gr_rect` cutouts, Edge.Cuts
chained across a 4 um step (`Wire.combine(tol=0.01)`, as KiCad does), footprint-level Edge.Cuts items, pad-less footprints, 100+
footprints from 12-17 libraries, KiCad 6 / 7 `fp_text reference` footprints (the one `openworkshop/pcb.py` change: `kicad_pcb()` now
rewrites `fp_text reference / value` as well as the KiCad 8+ properties, otherwise an older library's footprint keeps "REF**"),
and parts on both sides (above).  By the second set: 437 footprints / 1639 pads on one board, V-cut and mouse-bite panels with
duplicated references (same nets per copy), chamfered and odd-ratio roundrect pads, castellated oval pads with `(drill (offset))`,
mask-only pads, `gr_poly` cutouts with 123 vertices, 22 `gr_circle` cutouts, NPTH-only mouse-bite footprints, oval NPTH slots
(mozc's 216, through the drill table), user-named copper layers, KiCad 9 (20241229) files.  Two `openworkshop/pcb.py` fixes came out of it: the s-expression parser takes only plain decimals as
numbers (hackrf's hex `(tedit 527E5841)` was read as inf and crashed the writer; section 1), and Edge.Cuts points are written at 6
decimals (jumperless' 58 mm flat arcs lost 0.1 mm of centre at 4; section 6).  By the third set: a KiCad 5 file's footprints
(re-embedded with their legacy syntax - bare layer names, `(width w)`, `fp_text`, hex `tedit` - which KiCad 10 reads in a
20241229 board; oxplot and fomu, 91 modules), six copper layers through kicad-cli (the linear motor's layer table), 54 custom
pads whose anchor is offset from the drill (neopico), a flex outline of five polygons and a Polyimide stackup in the original
(fly2040 - the DSL re-expresses the outline, not the stackup: it writes FR4), rounded tracks / 658 teardrop zones / net ties /
keepout rule areas / groups parsed and left out of the comparison (placebo, olimex, locust, adsbee), an unrouted board
(locust: placement, drills and nets only), a V-cut panel of 12 coupons (adsbee's 14-line frame outline; its pads only per the
report line, see the row), plated slots on a KiCad 5 / 7.99 / 7 board (oxplot's, locust's, olimex's USB-C shells), and blind /
buried / micro vias on 4 and 6 layers refused by the DSL (fomu, linear motor; `test_blind_buried_vias_are_refused` hands the
first such via of the original to `kicad_pcb(traces=...)` and expects the ValueError, then hands one through via of the same
board - oxplot's with the stray `blind` flag first - and expects one `(via ...)` node back; the count only, its `F.Cu` / `B.Cu`
layers are asserted by section 6's unit test).  Of the third set's custom pads with anchors, neopico's 54 are asserted in both
variants and fomu's 36 in the embedded one; oxplot's 8 by no passing test (its row).

- `test_fixture_matches_sources` - sha256 of the (decompressed) fixture equals the SOURCES.md row.
- `test_fixture_is_what_we_think` - footprints, Edge.Cuts (at board level or inside a footprint), routing present unless the board
  was picked as the unrouted case; every feature in `BOARDS` detected.
- `test_layer_stack` - the regenerated board's copper layer table equals the original's.
- `test_outline_matches` - Edge.Cuts lines / arcs identical within 0.01 mm (4 to 428 items per board; a `gr_poly` plots as lines).
- `test_drill_table_matches` - PTH and NPTH holes and slots identical within 0.01 mm, after removing the original's via holes
  (bottom-side parts' holes included; 0 to 396 NPTH).
- `test_pad_flashes_match[top|bottom]` - every pad flash of every part (keyed by KiCad's `.P` ref/pad attribute: position,
  bounding box, aperture type and parameters, and the `.N` net attribute) identical within 0.01 mm; tracks, arcs, zone regions
  and via flashes excluded and counted in the report (copper `fp_poly` inside a footprint is allowed - it is part of the tree).
  Embedded variant: exact (8 to 1616 flashes per layer).  Library variant: every mismatch must be a pad whose embedded footprint
  differs from the installed library's (`_library_drift`, which also catches renamed pads), and the list is reported.
- `test_bottom_side_parts` - the parts the original has on B.Cu are on B.Cu in the regenerated board with every flash in place on
  both copper layers (a bottom part's THT pads flash on F.Cu too); library drift excused as above; skipped on top-only boards and
  when the only bottom parts have no copper pads (mumo's logo).
- `test_netlists_match_pad_by_pad` - `kicad_parse` reads both `.kicad_pcb`: the same net on every `(ref, pad)` (12 to 1369 keys,
  0 differ; a duplicated reference's key lists every copy's net) and the same set of net names.
- `test_blind_buried_vias_are_refused` - on a board with a via that does not span the whole stack (by its layers, not its flag):
  the first such via as a Circuit JSON via point (`from_layer` / `to_layer`) through `kicad_pcb(traces=...)` raises a ValueError
  naming "blind / buried via"; one through via of the same board (if it has one) comes back as exactly one `(via ...)` node - the
  node count is asserted, its layers are not (section 6's unit test asserts `(layers "F.Cu" "B.Cu")`).  One via of each kind per
  board, not all of them: the "249 of 249" / "60 of 60" in the report lines are the oracle's classification.  Embedded variant
  only (the check owes nothing to the footprints); skipped on a board without vias (stepper, jumperless, locust).

**4. JLC outputs** (`test_jlc.py`): a fixture board with R1 / R2 (same part), C1 placed at -90, U1 at 180, J1 without an LCSC
number, a `bom_only` part on another part's pads and a `bom_only(assemble=False)` lead.

- `test_bom_columns_and_grouping` — `Comment,Designator,Footprint,LCSC Part #`; R1 + R2 grouped into `"R1,R2"`; J1 absent.
- `test_cpl_columns_positions_rotations` — `Designator,Mid X,Mid Y,Layer,Rotation`; `10.000mm` formatting; `Top`; rotations
  90 / 0 / 270 / 180 / 0 (negative input normalised).
- `test_bom_full_lists_everything` — every part and extra with `Lib:Name` footprints, MPN, LCSC, note.
- `test_mid_is_pad_bbox_centre_not_origin` — `Mid X/Y` is the pad-bbox centre `place()` put at `at`, not the footprint origin.
- `test_rotation_matches_kicad_pos_file` — `kicad-cli pcb export pos` on the same board gives the same rotation for every
  part and the same X/Y for the footprints whose origin is their pad centre (J1's origin is pin 1, so only its rotation is
  compared and its pos X/Y is checked against `Placed.x/y`).

**5. Bottom-side parts** (`test_bottom_side.py`): SOIC-8, 0603, JST XH (origin on pin 1) and the Pico SMD (drill offsets, rotated
custom pads, paste-only pads) placed with `layer="bottom"` at 0 / 90 / 37 / 180 / 270, each next to a TOP twin at the negated angle.
Turning a part over about its x axis is what KiCad's flip is (`FOOTPRINT::Flip` negates the orientation and mirrors y), so the twin
is an oracle that owes nothing to the DSL's own mirror rules.

- `test_reread_is_kicads_flipped_footprint` - after `kicad-cli pcb drc --save-board`: `(layer "B.Cu")`, `(at x -y rot)`, every pad
  stored as KiCad stores a flipped one (y mirrored, angle = -library + rot, drill offset y mirrored, `F.*` <-> `B.*` layers, custom
  primitives mirrored), and KiCad's own rendering rule (`kicad_parse.pad_abs`, footprint origin + rotation, no mirroring) lands on
  `Placed.pad_xy()` for every plain pad.
- `test_gerber_flashes_are_the_top_twin_turned_over` - the bottom part's copper flashes == the twin's mirrored about the part's y, on
  the other copper layer, same size (335 flashes over 20 parts); a bottom part's SMD pads flash on B.Cu only; plain pads at
  `pad_xy()` with the DSL's size.
- `test_pos_file_and_cpl_agree` - `kicad-cli pcb export pos`: side bottom, the same X/Y as the DSL's CPL (`Layer` = Bottom), and
  the CPL rotation in JLC's convention: a bottom part's angle as seen from the bottom, `(180 - rot) % 360` of KiCad's stored /
  pos-file angle, which is what both KiCad -> JLC exporters write (Fabrication Toolkit, the tool JLC's KiCad guide recommends,
  and kicad-jlcpcb-tools); checked geometrically too - seen from the bottom (x mirrored) the pads lie where the unflipped
  library footprint turned by the CPL angle puts them.  `Mid X/Y` is the twin's pad centre turned over.  (Found by the
  2026-10-07 adversarial review: the CPL had KiCad's angle verbatim for bottom parts.)
- `test_circuit_json_and_solid_put_the_part_under_the_board` - `pcb_smtpad` / `pcb_port` / `pcb_component` on `bottom`; `solid()`
  puts the STEP model (same height) and the pads under the board, the pad at `pad_xy()`.

**6. Inner copper layers and bezier outlines** (`test_layers_curves.py`): a 60 x 40 mm `Board(layers=4)` whose left side is a
cubic bezier, SOIC-8 + 0603, GND stitched down through vias to pours on In1.Cu and B.Cu, the SIG link as a hand trace on In2.Cu
between two through vias.

- `test_four_copper_layers_survive_kicad` — the DSL's file and the one `kicad-cli pcb drc --save-board` re-writes both list
  `F.Cu / In1.Cu / In2.Cu / B.Cu` in the layer table and as `copper` layers of the `(stackup ...)`, whose three dielectrics sum to
  1.6 - 4 x 0.035 - 2 x 0.01; DRC has 0 errors and 0 unconnected items.
- `test_inner_layer_gerbers` — `kicad-cli pcb export gerbers` (every layer, as `tools/pcb/kicad_export.sh` runs it) writes
  `In1_Cu.g1` / `In2_Cu.g2`; In1 carries the pour region, In2 the one trace, F.Cu only the 10 pad flashes; the 4 via flashes
  are on every copper layer.
- `test_four_layer_step_thickness` — the board-only STEP body is 1.4 - 1.65 mm thick: the stackup sums to the board thickness.
- `test_two_layer_output_unchanged` — `Board()` is still 2-layer (`F.Cu / B.Cu`, one dielectric); `layers=3` and a pour or
  trace on a layer the board lacks raise `ValueError`.
- `test_four_layer_circuit_json_and_jlc` — Circuit JSON `num_layers` 4, an In2.Cu trace as `inner2`; the JLC CPL is unchanged.
- `test_bezier_outline_roundtrip` — the written and the re-saved `.kicad_pcb` each hold one `gr_curve` whose four points are the
  Face's bezier poles (y flipped, 1e-6) in the drawn order, plus 4 lines; `face_from_edge_cuts` rebuilds a Face of the same area
  with one BEZIER edge.
- `test_bezier_gerber_lies_on_the_edge` — KiCad plots the curve as ~1500 short lines; every vertex is within 0.01 mm of the
  build123d edge (measured 0.0000).
- `test_bezier_keeps_drawn_direction` — the same curve drawn forwards and backwards, in a wire built either way round: the
  `gr_curve` points come out in the drawn order every time.
- `test_spline_outline_is_cubic_spans` — a BSPLINE through 4 points -> 3 `gr_curve` items chained end to end, each span's ends
  and quarter points on the spline within 1e-6, and no `gr_arc`.
- `test_curve_outline_within_tolerance` — a 6-span cubic spline, a degree-5 spline, a rational quadratic and a 10 x 1 half
  ellipse each on one side of a board: every one comes out as `gr_curve` spans (exact for the cubic; within 0.002 mm of the CAD
  edge for the rest, measured by OCC's point-on-curve projection at 41 points per span) and the outline has no open end.
  The 2026-10-07 review found the sampled-lines fallback 0.029 mm off on the ellipse; the DSL now approximates such curves
  with cubic beziers within `CURVE_TOL` = 1 um (`GeomConvert_ApproxCurve`).
- `test_flat_arc_keeps_its_centre` — a 58 mm radius arc over a 3.2 mm chord (sagitta 0.022 mm; the jumperless probe's tip) as
  a 3-point `gr_arc`: the circumcentre of the three stored points is within 0.01 mm of the CAD centre.  Edge.Cuts points were
  written at 4 decimals, which moved that centre 0.1 mm (KiCad reconstructs the circle from the three points); they are now
  written at 6 decimals, KiCad's own nm precision, like the `gr_curve` points already were.
- `test_layer_table_ids_match_a_kicad9_board` — the DSL's `(layers ...)` ids equal, name for name, the ones KiCad 9 wrote in the
  antmicro 4-layer fixture (copper on the even ids 0 / 4 / 6 / 2; KiCad 8's 0 / 1 / 2 / 31 would be wrong for format 20241229),
  and its 4-layer dielectrics are prepreg / core / prepreg like that board's.
- `test_blind_buried_vias_are_refused` — on a `Board(layers=6)`, a routed via point from top to inner1 (blind), inner2 to inner3
  (buried), inner4 to bottom or top to inner4 raises `ValueError("blind / buried via at (x, y) a -> b: the DSL writes through vias
  only ...")`; a top-to-bottom point, and one without layers (older routers), is written as the through via it always was.  Before
  this the span was ignored and every via became a through via, which on a 6-layer board shorts the other layers' copper at that
  spot.  The fixture-driven twin of this test is in section 3 (fomu's 249, the linear motor's 60).

**7. Inner wires: NPTH drills vs Edge.Cuts cutouts** (`test_cutouts.py`): a Face with a circular and a slot-shaped inner wire.

- `test_circle_inner_wire` — default `inner_circles="npth"`: the circle is one `openworkshop:NPTH` footprint at the CAD position
  and no `gr_circle` (what every board written before the option existed got - the ordered nose-poke board's M2.5 clearance
  holes are such wires); `"cutout"`: a `gr_circle` and no drill.  The slot is 2 `gr_arc` + 2 `gr_line` either way, a closed
  chain `face_from_edge_cuts` rebuilds as one inner wire of the right area.
- `test_explicit_hole` / `test_bad_inner_circles_value` — `Board.hole()` adds an NPTH; a bad `inner_circles` raises.

## What the suite does NOT prove

- **Routing.** Copper tracks, vias and zone fills are excluded from every comparison by design (the DSL hands routing to
  tscircuit; the round-trip board has one hand trace and one pour and only proves KiCad accepts them and sees the nets
  connected).  `kicad_pcb(traces=...)` (routed Circuit JSON -> segments / vias) is not exercised.
- **Circuit JSON** (`circuit_json()` / `write()`), the **schematic** (`kicad_sch()`, ERC, `check_netlist()`), and **`solid()`**
  (the board back as build123d geometry) are not tested here beyond `write_kicad()` writing the schematic without error,
  section 5's bottom-side checks (pad / port / component layers; the model and pads under the board) and section 6's
  `num_layers` / inner-layer trace names.  Concretely: no test runs `kicad-cli sch erc` or `sch export netlist` on the
  schematic, `check_netlist()` and the `.net` file (`netlist()`) are never called or imported, the Circuit JSON is never
  run through tscircuit (`tools/pcb/export.mjs`) or checked against its schema, and `solid()` is never compared with the
  STEP KiCad exports from the same board (the model's position / orientation per part is unproven either way; the full
  STEP is only checked to be larger than the board-only one).
- **Never through kicad-cli at all**: `keepout()` / `hole_keepout()` (rule-area zones, the `F&B.Cu` layer spelling),
  `label()` silkscreen text, `ref_at`, and `kicad_pcb(traces=...)` (its via points are only parsed back by `kicad_parse`, never
  exported).  A one-off check on 2026-10-07 found KiCad 10 loads and re-saves all of these and that the `.kicad_pro` clearance
  rule is applied (a 0.1 mm pad-to-track gap raises a `clearance` error), but no test pins that down.  `Board(layers=6)` goes
  through kicad-cli since the linear-motor fixture (layer table and Gerbers), but its five-dielectric stackup and the STEP
  thickness are only checked on the 4-layer board.
- **Blind / buried / micro vias** are refused, not expressed: the DSL has no via that stops at an inner layer, and the
  fixtures that have them (fomu, linear motor) are compared with their routing left out like every other board's.
- **A flex stackup** (fly2040's 0.025 mm Polyimide core) is not re-expressed: `Board` writes an FR4 stackup of its own
  `thickness`; only the flex outline and parts are compared.  Teardrops, rounded tracks, keepout rule areas, V-cut texts and
  groups in a fixture are parsed by the ORACLE (`kicad_parse`, for `_features`) and excluded from the comparison - the DSL has no
  board reader (`kicad_footprint()` is its only parser) and never sees a board-level item, so "the DSL parses teardrops / rule
  areas" is not something this suite can show; it writes none of them either (its own `keepout()` is the untested rule area
  above).  What the DSL does parse from these fixtures is the footprint blocks: `net_tie_pad_groups` (re-emitted, unasserted),
  custom-pad `(anchor ...)` primitives, `(at x y unlocked)`, KiCad 5 legacy syntax, KiCad 7.99+ `(property ...)` fields.
- **The pads of the three net-gap boards** (wiimote, adsbee, oxplot-embedded) are asserted by no passing test: the gap rows xfail
  `test_pad_flashes_match` as a whole, so their pad geometry (wiimote's 4 custom pads, adsbee's 24 coax connectors, oxplot's 8
  anchored custom pads - also library drift in the other variant) is matched only in the report lines.
- **KiCad 5 files** are proven as fixtures (the oracle reads them, their footprints are re-embedded with their legacy syntax and
  KiCad 10 accepts the result); the DSL never writes KiCad 5 and `kicad_footprint()` reads a KiCad 5 `.kicad_mod` only as the
  harness rewrites it (`(footprint "Name"` head).
- **A chamfered pad on a bottom-side part** (`_flip_tree`'s corner swap) is exercised by no fixture (the only chamfered pads,
  jumperless', are all on top) and no unit test; the same holds for the harness's `_unflip`.
- **Silkscreen, mask, paste, courtyard, fab layers** are not compared (only F.Cu / B.Cu / Edge.Cuts / drills) - so the mirrored
  text and `B.SilkS` / `B.Fab` / `B.CrtYd` of a bottom-side part are written as KiCad does but only re-read, not rendered.
- **Bottom-side parts in JLC's terms**: the CPL rotation follows the convention the two KiCad -> JLC exporters implement
  (180 - KiCad's angle, section 5), not a JLC document - JLC's own KiCad guide only says to use one of those tools; whether JLC
  wants a further offset for a given part is, as for the top, outside what can be tested.
- **Inner-layer pads**: a 4-layer board is proven to the layer table / stackup / inner Gerbers (section 6); nothing checks an
  inner-layer *pad* (there are none).  Beziers are proven on corne's 100 and the section-6 board; the approximation of
  ellipses / rational / high-degree curves is proven against the CAD edge (section 6) but not through kicad-cli.
- **Rotations other than multiples of 90** are proven for the KiCad path only (soil-moisture 45 / 135, corne 113.88 ...): the
  library tree is re-embedded and KiCad draws it.  The DSL's own `Pad.w / h` (Circuit JSON, `solid()`) still only swap at 90 / 270.
- **Library drift is tolerated, not resolved**, in the `library` variant: the test proves the DSL reproduces whichever
  footprint it is given; which library version a fab receives is the user's responsibility.
- **Panels** are proven only as far as KiCad's own file goes: duplicated references place and flash correctly (mozc, wiimote,
  hackrf's 17 `TESTPOINT-30MIL-MASKONLY`), but the DSL has no notion of a copy - per-copy nets are the open gap above, and
  V-cut lines / mouse-bite tabs are only compared as the Edge.Cuts / NPTH geometry they are drawn as.  Chamfered and odd-ratio
  roundrect pads, castellations and drill offsets are proven through KiCad's rendering of the re-embedded tree (the Gerber
  flash), not in the DSL's own `Pad` model.
- **JLC conventions beyond KiCad's**: the CPL rotation is proven equal to KiCad's own position file (top) / 180 minus it
  (bottom); whether JLC's part library wants +90 / 180 for a given part (the README's "check in their order preview") is
  outside what can be tested.
- **KiCad version**: run here against kicad-cli 10.0.6 (board re-saved in format 20260206) with the KiCad 10.0 libraries;
  KiCad 9 should behave the same but was not run.
- **The 3D models**: the full STEP export is only checked to be larger than the board-only one (the models landed), not that
  each model sits at its pad.

## Moving to the openworkshop repo

Copy this directory to `tests/` in bjsi/openworkshop; `conftest.py` then finds `../openworkshop/pcb.py` on its own.  The fixtures
and `kicad_parse.py` have no arenas dependencies.  Add `pytest` + `gerbonara` to that repo's dev dependencies.
