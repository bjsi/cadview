# Conformance tests for the build123d -> KiCad board DSL (`cadview.pcb`, formerly `cadpcb.py`)

The question these answer: **does what the DSL writes mean the same thing to KiCad, and does it reproduce real
open-source boards?**  Every check goes through an independent reader (`kicad_parse.py`, written here, no code shared
with the module) and through KiCad's own `kicad-cli`, with Gerbers / Excellon read back by `gerbonara`.

Nothing in here is specific to the arenas repo: the module under test is found by path (see *Running*), the fixtures are
self-contained, and the suite can be dropped into the cadview repo as `tests/` next to `cadview/pcb.py`.

## Layout

| file | what |
|---|---|
| `conftest.py` | finds and loads the module under test by file path; serialised `nice`d `kicad-cli` runner (with the libprotobuf shim lookup); output dir; the terminal summary |
| `kicad_parse.py` | the independent oracle: s-expression parser, `.kicad_mod` / `.kicad_pcb` readers (pads, nets, Edge.Cuts, vias), IPC-D-356 reader, Gerber / Excellon summaries via gerbonara, tolerant multiset matcher |
| `helpers.py` | DSL-side helpers: build123d Face from Edge.Cuts, the round-trip board, re-expression of a parsed board through the DSL, KiCad pad semantics (offset / rotation / custom primitives) |
| `test_footprints.py` | 1. footprint fidelity (15 footprints across 9 libraries) |
| `test_roundtrip.py` | 2. DSL board -> kicad-cli DRC / Gerbers / drill / STEP / IPC-D-356 |
| `test_oss_boards.py` | 3. nine open-source boards re-expressed through the DSL, Gerber-vs-Gerber; the gap table |
| `test_jlc.py` | 4. JLCPCB `bom.csv` / `cpl.csv` / `bom_full.csv` |
| `test_bottom_side.py` | 5. bottom-side parts: KiCad's flip storage, Gerbers against a top twin turned over, pos / CPL, Circuit JSON, `solid()` |
| `test_layers_curves.py` | 6. a 4-layer board (`Board(layers=4)`): layer table + stackup through kicad-cli (ids against a KiCad-9-written board), inner-layer Gerbers; bezier / spline / ellipse outlines as `gr_curve` within tolerance |
| `test_cutouts.py` | 7. circular inner wires as NPTH (default) or `gr_circle` cutouts; slot cutouts as a closed Edge.Cuts chain; `Board.hole()` |
| `fixtures/oss/` | the nine boards (big ones gzipped) + `SOURCES.md` (repo, commit, licence, sha256) |

## Running

```bash
pip install -e ".[pcb,dev]" build123d           # shapely, pytest, gerbonara; plus kicad-cli and the KiCad libraries on the box
python -m pytest tests/pcb -q -ra               # from the cadview repo root (CI runs this job on ubuntu with KiCad 9)
PCB_TEST_OUT=/tmp/pcb-dsl python -m pytest tests/pcb   # keep every board / Gerber / STEP / drc.json it produced
```

Needs: `pytest`, `gerbonara` (dev dependency group), `build123d` + `shapely` (the module's own needs), KiCad's footprint
library on disk (`KICAD_FOOTPRINTS`, default `/usr/share/kicad/footprints`), and `kicad-cli` (KiCad 9 or 10).

| env | meaning |
|---|---|
| `CADPCB_PATH` | the module file to test; otherwise `../cadpcb.py`, `../cadview/pcb.py`, then the installed `cadview/pcb.py` |
| `KICAD_CLI` | the binary (default `kicad-cli` on PATH) |
| `KICAD_CLI_LD_LIBRARY_PATH` | a directory holding `libprotobuf.so.36` when the system's is older (the hub's partial Arch upgrade); `~/.claude/jobs/*/tmp/pb36/usr/lib` is tried automatically |
| `PCB_TEST_OUT` | where to leave the outputs (default: pytest's tmp dir, printed in the summary) |

Without a runnable `kicad-cli` the tests that need it are **skipped** (shown in the `-ra` summary), not passed.  Every
kicad-cli call runs under `nice -n 10`, one at a time (~80 calls, ~2 min on the hub).

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

**3. Open-source boards** (`test_oss_boards.py`), nine boards, `fixtures/oss/SOURCES.md` (repo, commit, licence, sha256 - checked by
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

Gap table (feature -> boards -> what the DSL does; every row is a strict xfail, so the day the DSL learns it the suite says so).
**Empty as of 2026-10-07**: every feature the nine boards were picked for is expressed; `GAPS` in `test_oss_boards.py` is where a
new fixture's gap goes.

| feature | boards | DSL status |
|---|---|---|

Closed gaps (were strict xfails; the row says what the DSL does now):

| feature | boards | DSL status |
|---|---|---|
| bottom-side footprints | soil-moisture, pan-tilt motor + main, pico-ice, antmicro, corne | `place(..., layer="bottom")`: `kicad_pcb()` writes the library tree the way KiCad's top/bottom flip stores it (`_flip_tree`: pad y mirrored, pad and text angles negated, `F.*` <-> `B.*` layers, chamfers top <-> bottom, text mirrored) at `(layer "B.Cu") (at x -y rot)`; `Placed.pad_xy()` / `pad_layers()` mirror the same way for Circuit JSON, the CPL and `solid()`.  All six fixtures store their bottom parts this way (0 of 178 library-matched bottom footprints use the left/right mirror).  Section 5 below is the focused test |
| circular Edge.Cuts cutouts (`gr_circle` inside the outline) | corne | `Board(..., inner_circles="cutout")` keeps a circular inner wire on Edge.Cuts (`gr_circle`); the default `"npth"` still makes it a non-plated drill (a CAD mounting hole), and `Board.hole(at, d)` adds one explicitly.  Corne's 12 circles: Edge.Cuts match, NPTH 286 / 286 |
| inner copper layers (4-layer) | pico-ice, antmicro | `Board(layers=4)` (2 / 4 / 6) writes the KiCad 9/10 layer table (copper on the even ids: F.Cu 0, In1.Cu 4, In2.Cu 6, B.Cu 2) and a `(setup (stackup ...))` with the copper / dielectric layers summing to the board thickness; `reexpress()` passes the original's copper count, so `test_layer_stack` passes for pico-ice and antmicro; section 6 below round-trips a 4-layer board through kicad-cli |
| bezier (`gr_curve`) Edge.Cuts | corne | a BEZIER edge is written as `gr_curve` with its four control points (6 decimals, KiCad's own precision), a BSPLINE as one `gr_curve` per cubic span (OCC's span-to-bezier conversion; rational or higher-degree curves and ellipses are first approximated by a cubic BSpline within `CURVE_TOL` = 1 um and split the same way, no longer a wrong 3-point arc or 0.25 mm lines); the points keep the direction the curve was drawn in (the writer walks `wire.edges()`, not `order_edges()`, which rebuilds a reversed edge's curve backwards), because KiCad's polyline of a bezier depends on it.  Corne's 100 beziers match segment for segment, so with the 12 circles its `test_outline_matches` passes |

Two oracle fixes came with it (`kicad_parse`): `match_multisets` pairs records equal to 1e-6 before the greedy pass within `tol`
(a bezier plots as segments shorter than 0.01 mm, which the greedy pass alone paired with their neighbours and left 32 chain ends
unmatched), and `read_outline` orders a line's endpoints with coordinates within 1 um counting as equal (a line vertical to within
1 um in one file and exactly vertical in the other sorted differently).

Proven by the new boards (no gap): rotations off the 90 deg grid (pad positions AND sizes - the library tree is re-embedded, KiCad
draws it), oval / slot drills, custom-primitive and trapezoid pads, castellated edge pads, arc outlines, `gr_rect` cutouts, Edge.Cuts
chained across a 4 um step (`Wire.combine(tol=0.01)`, as KiCad does), footprint-level Edge.Cuts items, pad-less footprints, 100+
footprints from 12-17 libraries, KiCad 6 / 7 `fp_text reference` footprints (the one `cadview/pcb.py` change: `kicad_pcb()` now
rewrites `fp_text reference / value` as well as the KiCad 8+ properties, otherwise an older library's footprint keeps "REF**"),
and parts on both sides (above).

- `test_fixture_matches_sources` - sha256 of the (decompressed) fixture equals the SOURCES.md row.
- `test_fixture_is_what_we_think` - footprints, Edge.Cuts, routing present; every feature in `BOARDS` detected.
- `test_layer_stack` - the regenerated board's copper layer table equals the original's.
- `test_outline_matches` - Edge.Cuts lines / arcs identical within 0.01 mm (4 to 40 items per board).
- `test_drill_table_matches` - PTH and NPTH holes and slots identical within 0.01 mm, after removing the original's via holes
  (bottom-side parts' holes included).
- `test_pad_flashes_match[top|bottom]` - every pad flash of every part (keyed by KiCad's `.P` ref/pad attribute: position,
  bounding box, aperture type and parameters, and the `.N` net attribute) identical within 0.01 mm; tracks, arcs, zone regions
  and via flashes excluded and counted in the report (copper `fp_poly` inside a footprint is allowed - it is part of the tree).
  Embedded variant: exact (8 to 656 flashes per layer).  Library variant: every mismatch must be a pad whose embedded footprint
  differs from the installed library's (`_library_drift`, which also catches renamed pads), and the list is reported.
- `test_bottom_side_parts` - the parts the original has on B.Cu are on B.Cu in the regenerated board with every flash in place on
  both copper layers (a bottom part's THT pads flash on F.Cu too); library drift excused as above; skipped on top-only boards.
- `test_netlists_match_pad_by_pad` - `kicad_parse` reads both `.kicad_pcb`: the same net on every `(ref, pad)` (17 to 682 keys,
  0 differ) and the same set of net names.

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
- `test_layer_table_ids_match_a_kicad9_board` — the DSL's `(layers ...)` ids equal, name for name, the ones KiCad 9 wrote in the
  antmicro 4-layer fixture (copper on the even ids 0 / 4 / 6 / 2; KiCad 8's 0 / 1 / 2 / 31 would be wrong for format 20241229),
  and its 4-layer dielectrics are prepreg / core / prepreg like that board's.

**7. Inner wires: NPTH drills vs Edge.Cuts cutouts** (`test_cutouts.py`): a Face with a circular and a slot-shaped inner wire.

- `test_circle_inner_wire` — default `inner_circles="npth"`: the circle is one `cadview:NPTH` footprint at the CAD position
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
  `num_layers` / inner-layer trace names.
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
- **JLC conventions beyond KiCad's**: the CPL rotation is proven equal to KiCad's own position file (top) / 180 minus it
  (bottom); whether JLC's part library wants +90 / 180 for a given part (the README's "check in their order preview") is
  outside what can be tested.
- **KiCad version**: run here against kicad-cli 10.0.6 (board re-saved in format 20260206) with the KiCad 10.0 libraries;
  KiCad 9 should behave the same but was not run.
- **The 3D models**: the full STEP export is only checked to be larger than the board-only one (the models landed), not that
  each model sits at its pad.

## Moving to the cadview repo

Copy this directory to `tests/` in bjsi/cadview; `conftest.py` then finds `../cadview/pcb.py` on its own.  The fixtures
and `kicad_parse.py` have no arenas dependencies.  Add `pytest` + `gerbonara` to that repo's dev dependencies.
