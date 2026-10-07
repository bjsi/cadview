# Open-source boards used as comparison fixtures

Nine KiCad boards fetched verbatim from GitHub at the commits below (the first two on 2026-10-07 as the original pair, the
rest on 2026-10-07 as the stress set), so the suite runs offline and the comparison is reproducible; the tests never modify
them (kicad-cli works on a copy).  Boards over 1 MB are stored gzip-compressed (`.kicad_pcb.gz`); the sha256 is always of
the upstream file as fetched (`test_fixture_matches_sources` checks it on the decompressed copy).  Licences are the
repositories' own: MIT / Apache-2.0 / CERN-OHL-P-2.0 / CC-BY-4.0, all of which allow redistributing the design file with
this attribution.

| fixture | repository | path in repo | commit | licence | sha256 of the upstream file |
|---|---|---|---|---|---|
| `pi-pico-mpu6050-light.kicad_pcb` | https://github.com/Muditha-Kumara/pi-pico-mpu6050-light | `PCB/pico.kicad_pcb` | `1baeb39614741bc24a66ca37102f6afc9079f2c2` (main) | MIT (`LICENSE`, (c) 2025 MH Muditha Chinthana Kumara) | `cdb525aadedb918ac6a29b27cef1d6037182d21ce230b03b0eecb02b139d7d10` |
| `stepper-playground-12v-pico.kicad_pcb` | https://github.com/jhmcaleely/stepper-playground | `12v-pico/12v-pico.kicad_pcb` | `d3c5cc9a198889bdb19677549f96d78d1fc87dda` (main) | MIT (`LICENSE`, (c) 2022 John McAleely) | `249db863689448eb1adf24d6fa6a0fb8bdcb487e371f5f296153dfbcee6b9027` |
| `hsp-usb-led.kicad_pcb` | https://github.com/nushackers/hsp-pcb-intro | `src/usb_led.kicad_pcb` | `ad3fbd582e3915b585c453ea202f591720a1f427` (main) | CERN-OHL-P-2.0 (`LICENSE.md`) | `a8e69c14ceec9dd0954c3027cc89ca6bbb9c0b0ec3aeede5feacfdd47736f362` |
| `capacitive-soil-moisture-sensor.kicad_pcb` | https://github.com/RonMcKay/capacitive-soil-moisture-sensor | `hardware/soil-moisture-sensor.kicad_pcb` | `d252a7cbcbff4727b947b9d368cec6be50aa740a` (master) | CERN-OHL-P v2 (README, "License") | `d30e14c54b5361c7e90debc239906d8502570a072cc6afb11bbcb118fec2c484` |
| `generic-pan-tilt-motor.kicad_pcb` | https://github.com/mitmedialab/generic-pan-tilt-pcb | `generic-pan-tilt-motor-pcb/generic-pan-tilt-motor-pcb.kicad_pcb` | `9a0c21770e967b68a4ab5e6a5ae65d44953b1125` (main) | CERN-OHL-P-2.0 (`LICENSE`) | `b70c771fcb00ee1e83ca102e7d8910dfdcddd2cc0d26c4f455481ef172048543` |
| `generic-pan-tilt-main.kicad_pcb.gz` | https://github.com/mitmedialab/generic-pan-tilt-pcb | `generic-pan-tilt-pcb/generic-pan-tilt-pcb.kicad_pcb` | `9a0c21770e967b68a4ab5e6a5ae65d44953b1125` (main) | CERN-OHL-P-2.0 (`LICENSE`) | `054e580fbb4904d1c3ee6477a24fbfb99c90ccf18ddebda4daca6409e32b78b2` |
| `pico-ice-rev3.kicad_pcb.gz` | https://github.com/tinyvision-ai-inc/pico-ice | `Board/Rev3/pico-ice.kicad_pcb` | `00e13360969d01fbb9663e4ea17f723c1a8e8400` (main) | MIT (`LICENSE`, (c) 2023 tinyVision.ai) | `71471afa7c6aea83338bfd1e36d463f3a8efba5c6cce07795d70bea1a53675b8` |
| `antmicro-usb-c-power-adapter.kicad_pcb.gz` | https://github.com/antmicro/usb-c-power-adapter | `usb-c-power-adapter.kicad_pcb` | `4d3e9e289a294f7953bf48dde6c96af8327a0611` (main) | Apache-2.0 (`LICENSE`) | `f2ca55189e62f4f2638b7bde1058085ea6ab8bce9f7d846ca6946c1174d9c0e3` |
| `crkbd-corne-cherry-hotswap.kicad_pcb.gz` | https://github.com/foostan/crkbd | `pcbs/corne-cherry/hotswap/corne-cherry.kicad_pcb` | `63366fb7f51cf2a796462fdd90527e99dd126055` (main) | CC-BY-4.0 (`LICENSE_CC`; the firmware is `LICENSE_MIT`) | `71538a202cb28882b9c9f7b6fe60bf402fb705703a29c59cd6ebb99b9edbb540` |

What is on them (from `kicad_parse.read_board`; "B.Cu" = parts on the bottom side):

- **pi-pico-mpu6050-light** — KiCad 9 (20241229), 2 layers, 14 footprints, all top: `Module:RaspberryPi_Pico_Common_SMD`,
  `Package_DFN_QFN:HVQFN-24-1EP_4x4mm_P0.5mm_EP2.1x2.1mm`, 6 x `Capacitor_SMD:C_0805_2012Metric`, `Capacitor_THT:CP_Radial_D8.0mm_P2.50mm`,
  `Connector_JST:JST_PH_S3B/S4B-PH-K` (horizontal), `Connector_PinHeader_2.54mm:PinHeader_1x02`,
  `Connector_BarrelJack:BarrelJack_CUI_PJ-063AH_Horizontal`; `gr_rect` outline, 171 track segments, 8 vias, 1 zone; rotations 0 / 180.
- **stepper-playground-12v-pico** — KiCad 9, 2 layers, 17 footprints, all top: `Module:RaspberryPi_Pico_SMD_HandSolder`, 2 x `PinHeader_1x20`,
  `PinHeader_1x07`, `PinHeader_1x03`, `PinSocket_1x03`, `TO-220-3_Vertical`, 2 x `D_DO-41_SOD81_P10.16mm_Horizontal`, `CP_Radial_D4.0mm_P2.00mm`,
  `CP_Radial_Tantal_D4.5mm_P2.50mm`, `SW_PUSH_6mm`, `TerminalBlock_Phoenix_PT-1,5-4-3.5-H_1x04`, 4 x `MountingHole_3.2mm_M3_Pad`;
  `gr_rect` outline, 104 track segments, 0 vias, 1 zone; rotations 0 / 90 / -90 / 180.
- **hsp-usb-led** (NUS Hackers "hardware starter pack" intro board) — KiCad 9, 2 layers, 6 footprints, all top, 4 libraries
  (`Resistor_SMD`, `Connector_USB`, `LED_SMD`, the project's `usb_led`); 22 pads of which 4 oval-drill slots (the USB-C shell);
  outline 4 lines + 4 arcs (rounded rectangle); 41 segments, 6 vias, 2 zones.  Small on purpose: arcs + slots with nothing else in the way.
- **capacitive-soil-moisture-sensor** — KiCad 6 file format (20211014), 2 layers, 23 footprints, 14 on B.Cu, 9 libraries (7 from the
  project's `MyFootprints` / `local_footprints`); rotations 0 / 45 / 90 / 135 / 180; 96 pads, 7 NPTH; outline lines + 3 arcs
  (a probe shape); 159 segments, 44 vias, 3 zones.  The KiCad 6 format carries the reference as `fp_text reference`.
- **generic-pan-tilt-motor** (MIT Media Lab pan-tilt camera mount, motor board) — KiCad 8 (20240108), 2 layers, 74 footprints,
  11 on B.Cu, 1 without pads (a logo), 14 libraries (`Capacitor_SMD`, `Resistor_SMD`, `TestPoint`, `MountingHole`, `Fiducial`, `Connector_JST`,
  `LED_SMD`, the project's `generic-pan-tilt-motor-pcb`, ...); 230 pads of which 14 custom-shaped, 4 NPTH; outline 4 lines + 4 arcs;
  740 segments, 224 vias, 1 zone, 5 dimensions.
- **generic-pan-tilt-main** (the main board of the same project) — KiCad 8, 2 layers, 91 footprints, 78 on B.Cu, 17 libraries;
  409 pads of which 5 slots, 4 custom, 8 NPTH; outline 4 lines + 4 arcs plus 8 `gr_rect` cutouts; 1001 segments, 409 vias, 5 zones,
  15 dimensions.  Stored gzip-compressed (1.5 MB of zone fills).
- **pico-ice-rev3** (tinyVision.ai RP2040 + iCE40 FPGA board in the Pico form factor) — KiCad 8, **4 layers**, 101 footprints,
  32 on B.Cu, 4 without pads, 14 libraries (`Capacitor_SMD`, `Resistor_SMD`, the project's `CUSTOM` / `RP2040_minimal`, `Fiducial`, `Jumper`,
  `MountingHole`, `Diode_SMD`, ...); 455 pads of which 18 custom (the castellated edge pads), 4 slots, 6 NPTH; outline 4 lines + 4 arcs;
  1689 segments, 189 vias, 9 zones.  Stored gzip-compressed (2.3 MB).
- **antmicro-usb-c-power-adapter** — KiCad 9, **4 layers**, 124 footprints, 46 on B.Cu, 2 without pads, every footprint from the
  project's own `antmicro-footprints` library (so only the `embedded` variant runs); 351 pads of which 4 trapezoid, 1 custom, 4 slots,
  4 NPTH; outline 10 lines; 600 segments, 229 vias, 34 zones, 4 dimensions.  Stored gzip-compressed (7.9 MB).
- **crkbd-corne-cherry-hotswap** (foostan's Corne split keyboard, Cherry hotswap PCB) — KiCad 7 file format (20221018), 2 layers,
  180 footprints, 168 on B.Cu, 2 without pads, 12 libraries (`kbd_local` 70, `kbd` 42, `Capacitor_SMD` 32, `Resistor_SMD` 18, ...);
  rotations include 113.88 / 168.06 / 191.94 / 246.12 (the thumb keys); 950 pads of which 44 slots, 4 custom, 286 NPTH (switch and
  hotswap-socket guides); Edge.Cuts = 120 lines + 32 arcs + 100 `gr_curve` beziers + 12 circles at board level plus 184 `fp_line`
  items inside footprints; 3027 segments, 452 vias, 933 zones (teardrops).  Stored gzip-compressed (4.6 MB).  The extreme case: it
  hits every gap at once.

Library drift seen on 2026-10-07 with the KiCad 10.0 footprint library on the hub: the stepper board's `D_DO-41_SOD81_P10.16mm_Horizontal`
and `CP_Radial_D4.0mm_P2.00mm` / `CP_Radial_Tantal_D4.5mm_P2.50mm` pads changed shape between the KiCad 9 library the board
embeds and the installed one (rect / oval -> roundrect / circle; 6 pads).  The `library` variant of the comparison reports and
tolerates exactly those pads; the `embedded` variant (the originals' own footprints) must match completely.  The newer boards'
drift is listed in the terminal summary of a run.
