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
| `test_oss_boards.py` | 3. two open-source boards re-expressed through the DSL, Gerber-vs-Gerber |
| `test_jlc.py` | 4. JLCPCB `bom.csv` / `cpl.csv` / `bom_full.csv` |
| `fixtures/oss/` | the two boards + `SOURCES.md` (repo, commit, licence, sha256) |

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
kicad-cli call runs under `nice -n 10`, one at a time (17 calls, ~20 s on the hub).

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

**3. Open-source boards** (`test_oss_boards.py`), `fixtures/oss/SOURCES.md`: *pi-pico-mpu6050-light* (14 footprints: Pico,
HVQFN-24, 0805s, JST PH, barrel jack, 8 vias) and *stepper-playground-12v-pico* (17 footprints: Pico, pin headers, TO-220,
DO-41, radial caps, terminal block, 4 mounting holes), both MIT, KiCad 9 format.  Each is parsed by `kicad_parse`, re-expressed
through the DSL (Face from Edge.Cuts, `kicad_footprint()` by `Lib:Name`, `place(..., center_pads=False)` at the original
origin / rotation, the original net on every pad, no tracks / vias / zones), both exported with the same `kicad-cli` calls.
Two variants: **library** (footprints from the installed KiCad library — what a user of the DSL gets) and **embedded** (the
originals' own footprints, written out as a temporary `.pretty` library — isolates the DSL from library drift).

- `test_outline_matches` — Edge.Cuts lines / arcs identical within 0.01 mm (4 / 4).
- `test_drill_table_matches` — PTH and NPTH holes and slots identical within 0.01 mm, after removing the original's via
  holes (routing is out of scope): 15 + 5 and 76 + 4 holes.
- `test_pad_flashes_match[top|bottom]` — every pad flash (keyed by KiCad's `.P` ref/pad attribute: position, bounding
  box, aperture type and parameters, and the `.N` net attribute) identical within 0.01 mm; tracks, arcs, zone regions and
  via flashes excluded and counted in the report.  Embedded variant: exact (94 / 15 and 119 / 76 flashes).  Library
  variant: every mismatch must be a pad whose embedded footprint differs from the installed library's (`_library_drift`),
  and the list is reported — on the hub that is 6 pads of the stepper board (DO-41 and radial-cap pads changed shape between
  the KiCad 9 and 10 libraries).
- `test_netlists_match_pad_by_pad` — `kicad_parse` reads both `.kicad_pcb`: the same net on every `(ref, pad)` (96 and 115
  keys, 0 differ) and the same set of net names.

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

## What the suite does NOT prove

- **Routing.** Copper tracks, vias and zone fills are excluded from every comparison by design (the DSL hands routing to
  tscircuit; the round-trip board has one hand trace and one pour and only proves KiCad accepts them and sees the nets
  connected).  `kicad_pcb(traces=...)` (routed Circuit JSON -> segments / vias) is not exercised.
- **Circuit JSON** (`circuit_json()` / `write()`), the **schematic** (`kicad_sch()`, ERC, `check_netlist()`), and **`solid()`**
  (the board back as build123d geometry) are not tested here beyond `write_kicad()` writing the schematic without error.
- **Silkscreen, mask, paste, courtyard, fab layers** are not compared (only F.Cu / B.Cu / Edge.Cuts / drills).
- **Bottom-side parts**: the DSL writes every footprint on F.Cu; the fixtures were chosen with top-side parts only, and
  `reexpress()` asserts that.
- **Non-rectangular open-source outlines**: both fixtures use a `gr_rect` outline; arcs on Edge.Cuts are proven only on the
  DSL's own round-trip board (`helpers.face_from_edge_cuts` handles lines / arcs / circles / rects but is exercised on rects).
- **Rotations other than multiples of 90** for the DSL's pad size (the Gerber test uses 0 / 90 / 180 / 270); positions use
  full trigonometry and would hold, sizes are only checked at those angles.
- **Library drift is tolerated, not resolved**, in the `library` variant: the test proves the DSL reproduces whichever
  footprint it is given; which library version a fab receives is the user's responsibility.
- **JLC conventions beyond KiCad's**: the CPL rotation is proven equal to KiCad's own position file; whether JLC's part
  library wants +90 / 180 for a given part (the README's "check in their order preview") is outside what can be tested.
- **KiCad version**: run here against kicad-cli 10.0.6 (board re-saved in format 20260206) with the KiCad 10.0 libraries;
  KiCad 9 should behave the same but was not run.
- **The 3D models**: the full STEP export is only checked to be larger than the board-only one (the models landed), not that
  each model sits at its pad.

## Moving to the cadview repo

Copy this directory to `tests/` in bjsi/cadview; `conftest.py` then finds `../cadview/pcb.py` on its own.  The fixtures
and `kicad_parse.py` have no arenas dependencies.  Add `pytest` + `gerbonara` to that repo's dev dependencies.
