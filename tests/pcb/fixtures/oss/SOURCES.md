# Open-source boards used as comparison fixtures

Both are small 2-layer KiCad 9 boards (file format 20241229) with a Raspberry Pi Pico and only top-side parts,
fetched from GitHub on 2026-10-07 at the commits below.  They are kept here verbatim (so the suite runs offline and
the comparison is reproducible); the tests never modify them (kicad-cli works on a copy).

| fixture | repository | path in repo | commit | licence | sha256 of the fixture |
|---|---|---|---|---|---|
| `pi-pico-mpu6050-light.kicad_pcb` | https://github.com/Muditha-Kumara/pi-pico-mpu6050-light | `PCB/pico.kicad_pcb` | `1baeb39614741bc24a66ca37102f6afc9079f2c2` (main) | MIT (`LICENSE`, (c) 2025 MH Muditha Chinthana Kumara) | `cdb525aadedb918ac6a29b27cef1d6037182d21ce230b03b0eecb02b139d7d10` |
| `stepper-playground-12v-pico.kicad_pcb` | https://github.com/jhmcaleely/stepper-playground | `12v-pico/12v-pico.kicad_pcb` | `d3c5cc9a198889bdb19677549f96d78d1fc87dda` (main) | MIT (`LICENSE`, (c) 2022 John McAleely) | `249db863689448eb1adf24d6fa6a0fb8bdcb487e371f5f296153dfbcee6b9027` |

What is on them (from `kicad_parse.read_board`):

- **pi-pico-mpu6050-light** — 14 footprints: `Module:RaspberryPi_Pico_Common_SMD`, `Package_DFN_QFN:HVQFN-24-1EP_4x4mm_P0.5mm_EP2.1x2.1mm`,
  6 x `Capacitor_SMD:C_0805_2012Metric`, `Capacitor_THT:CP_Radial_D8.0mm_P2.50mm`, `Connector_JST:JST_PH_S3B/S4B-PH-K` (horizontal),
  `Connector_PinHeader_2.54mm:PinHeader_1x02`, `Connector_BarrelJack:BarrelJack_CUI_PJ-063AH_Horizontal`; `gr_rect` outline,
  171 track segments, 8 vias, 1 zone; rotations 0 / 180.
- **stepper-playground-12v-pico** — 17 footprints: `Module:RaspberryPi_Pico_SMD_HandSolder`, 2 x `PinHeader_1x20`, `PinHeader_1x07`,
  `PinHeader_1x03`, `PinSocket_1x03`, `TO-220-3_Vertical`, 2 x `D_DO-41_SOD81_P10.16mm_Horizontal`, `CP_Radial_D4.0mm_P2.00mm`,
  `CP_Radial_Tantal_D4.5mm_P2.50mm`, `SW_PUSH_6mm`, `TerminalBlock_Phoenix_PT-1,5-4-3.5-H_1x04`, 4 x `MountingHole_3.2mm_M3_Pad`;
  `gr_rect` outline, 104 track segments, 0 vias, 1 zone; rotations 0 / 90 / -90 / 180.

Library drift seen on 2026-10-07 with the KiCad 10.0 footprint library on the hub: the stepper board's `D_DO-41_SOD81_P10.16mm_Horizontal`
and `CP_Radial_D4.0mm_P2.00mm` / `CP_Radial_Tantal_D4.5mm_P2.50mm` pads changed shape between the KiCad 9 library the board
embeds and the installed one (rect / oval -> roundrect / circle; 6 pads).  The `library` variant of the comparison reports and
tolerates exactly those pads; the `embedded` variant (the originals' own footprints) must match completely.
