# Open-source boards used as comparison fixtures

Twenty-seven KiCad boards fetched verbatim from GitHub at the commits below (the first two on 2026-10-07 as the original pair, the
next seven the same day as the stress set, nine that evening as the scale / panel / pad-shape set, and nine on 2026-10-08 as the
format / via / flex / panel set), so the suite runs offline and the comparison is reproducible; the tests never modify them
(kicad-cli works on a copy).  Boards over 1 MB are stored gzip-compressed (`.kicad_pcb.gz`); the sha256 is always of the upstream
file as fetched (`test_fixture_matches_sources` checks it on the decompressed copy; every one was re-fetched from
`raw.githubusercontent.com` at its commit and compared before being copied in).  Licences are the repositories' own: MIT /
BSD-3-Clause / Apache-2.0 / GPL-2.0 / GPL-3.0 / CERN-OHL-P-2.0 / CERN-OHL-S-2.0 / 0BSD / CC-BY-4.0 / CC-BY-SA-4.0 / Unlicense /
public domain, all of which allow redistributing the design file with this attribution (the share-alike and GPL files are
redistributed unchanged, with their source named here).

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
| `hackrf-one.kicad_pcb.gz` | https://github.com/greatscottgadgets/hackrf | `hardware/hackrf-one/hackrf-one.kicad_pcb` | `468c5d93b66032c892c95bbf9ff15ff1b803e84f` (master) | GPL-2.0 (`COPYING`) | `558d73553c7c2b2ae77dad541c87e671f3b2e982306f25e6fabed8d1e879e438` |
| `mozc-doublesided-main-panel.kicad_pcb.gz` | https://github.com/google/mozc-devices | `mozc-doublesided/board/main_panel/main_panel.kicad_pcb` | `e6a233680ee1967bfaa0eadfe9b931ee4b22ab6d` (master) | Apache-2.0 (`LICENSE`) | `baf72bcd4f538caa918b34e0a22783d33c7bfe69c522ce7b5b41b2fbd964b1bf` |
| `aykevl-earring-rgb36-v3.kicad_pcb` | https://github.com/aykevl/things | `earring-ring-rgb36v3/earringv3.kicad_pcb` | `a63d2868fd031de49d51624811310f6c643e7428` (master) | public domain / MIT at the user's option (README "License"; no LICENSE file) | `0a89b5bc9cd4d3720c3700e23ba581bbc54a5e58014fa646d1cccc5314eba58a` |
| `jumperless-probe.kicad_pcb` | https://github.com/Architeuthis-Flux/Jumperless-Probe | `JumperlessProbe.kicad_pcb` | `aed090b7d84846a95fc1509014b61210d42991a2` (main) | MIT (`LICENSE`) | `cf481fed4c5560352e5a03765b3702e976679ca5e9c32ca83479082b1b48f3b8` |
| `toraneko-mk3-panel.kicad_pcb` | https://github.com/Tokoro0917/ToraNeko.Mk3 | `hardware/kicad/TORANEKO.Mk3/panel/TORANEKO.Mk3_panel.kicad_pcb` | `63f4c2939045f3ade5313928798e4953e9e4d6a7` (main) | MIT (`LICENSE`) | `ad4f309f27c0985ba9171aaae850931638a8cd6626bf9cafa5ca2d9f45ddc78f` |
| `wiimote-ir-sensor-kikit-panel.kicad_pcb` | https://github.com/eatnooM/pixart-sensor-adapter | `inline/wiimote-ir-sensor-inline-panel-2-vert.kicad_pcb` | `865efbf09756a82105bfd7ecbb151cbddc509357` (main) | CC-BY-SA-4.0 (`LICENSE`) | `d30aa46e461928950f20d61c0d27e1f06f062952ac5a7c586f868247a866e6ff` |
| `mumo-castellated-module.kicad_pcb` | https://github.com/kounocom/Mumo | `Mumo.kicad_pcb` | `1467871c37d08ca8a79a2acd36a26ef3afcab6bb` (main) | CERN-OHL-S-2.0 (`LICENSE.md`) | `afd0e14e429bf0184ba5ef4ce19f19d931a3cfa7e382b3ac406776065177db52` |
| `antmicro-m2-oculink-adapter.kicad_pcb.gz` | https://github.com/antmicro/m2-oculink-adapter | `antmicro-m2-oculink-adapter-hw.kicad_pcb` | `067f60727046cd0c0db1d39c51c9396f89f48b65` (main) | Apache-2.0 (`LICENSE`) | `9a6d5edb57d075730ce6091585560d3e0d8e9666fd5e066f07831b49d09bd190` |
| `glasgow-revC3.kicad_pcb.gz` | https://github.com/GlasgowEmbedded/glasgow | `hardware/boards/glasgow/revC3/glasgow.kicad_pcb` | `e3e4bc46b29a8ae7075dfcb027ddc6e9af984952` (main) | 0BSD or Apache-2.0 (`LICENSE-0BSD.txt`, `LICENSE-Apache-2.0.txt`) | `74ef350bc764a48f750a17e71df6bba7364e0d7fbb48d5555e94afa0b0d97c4d` |
| `oxplot-fpx.kicad_pcb` | https://github.com/oxplot/fpx | `board/fpx.kicad_pcb` | `3d84b37751c5bb397c331c54ff978818b7e6e53b` (master) | BSD-3-Clause (`LICENSE`, (c) 2022 Mansour Behabadi) | `796204b8dbdadb398cb57d92d9f06eb95c1e5550cb7f22c33d1ee2b7b68f1759` |
| `fomu-pvt.kicad_pcb` | https://github.com/im-tomu/fomu-hardware | `archive/pvt/pcb/tomu-fpga.kicad_pcb` | `9fdebede731c1d963335d65d25c7663cb934f925` (master) | CC-BY-SA-4.0 (`LICENSE`; `LICENSE.TAPR` alongside) - share-alike: redistributed unchanged, source named here | `f97aef8a70d8010ecf31eba9403964db468cfa227286808359524630e426a322` |
| `advanced-linear-motor.kicad_pcb` | https://github.com/gxurma/Advanced-Linear-Motor | `Advanced Linear Motor.kicad_pcb` (a space in the name: URL-encode it) | `8470b889294581a8c642747af6b55eee568da2cc` (main) | GPL-2.0 (`LICENSE`) - redistributed unchanged, source named here | `5a0e456f44fcf07923d64dbabc4e9b41dbe119d3656fe884d71797a41faf71e7` |
| `placebo.kicad_pcb` | https://github.com/dotcypress/placebo | `placebo.kicad_pcb` | `c5da1b37fa3adf2bd180505f552df92d45fefc87` (main) | Apache-2.0 OR MIT (`LICENSE-APACHE`, `LICENSE-MIT`) | `65ef2ba1a1c9a7a7a58db3d80259860f57b1a38e0d73f35c91b0c7c465add629` |
| `locust.kicad_pcb` | https://github.com/hlord2000/Locust | `Locust.kicad_pcb` | `c6009d8c6927e3376ccf945290beeb022fa9800a` (main) | CERN-OHL-P-2.0 (`LICENSE`) | `5d7c798bf8e82e5a3f82b673ba9c1be93f47b2af46fff67f694fcc884b9e70d6` |
| `adsbee-panel-saw-eval.kicad_pcb` | https://github.com/PantsForBirds/adsbee | `kicad/prototyping/panel_saw_eval_board/panel_saw_eval_board.kicad_pcb` | `fe8a150a52b2b4aba3366e756fe43cc02388c8c7` (main) | GPL-3.0 (`LICENSE`) - redistributed unchanged, source named here | `d479203aa8fc9e25d88518b8881cc0199f22bc295223bbf3446e37d619a4e451` |
| `olimex-esp32-poe-revM2.kicad_pcb.gz` | https://github.com/OLIMEX/ESP32-POE | `HARDWARE/ESP32-PoE-hardware-revision-M2/ESP32-PoE_Rev_M2.kicad_pcb` | `deb38a377d50eadb04ddc7118a17a5ae58b1ee53` (master) | Apache-2.0 (`LICENSE`) | `7c9f634768ff4e8aee67b8f2f83d0495ab00e2f50209c5dd133a9f39e8bce9fa` |
| `neopico-hd-fpc20.kicad_pcb` | https://github.com/fliperama86/neopico-hd | `hardware/neopico-hd/fpc-20/fpc.kicad_pcb` | `398762c9155a74d90443bf9b9fa32f4b37de3a51` (main) | Unlicense (`LICENSE`, public domain) | `c0490626c14da15f309dcb83b5b6e94f8d2e1cb1bc4f17622e83eb50c291e2f3` |
| `fly2040-cpu-flex.kicad_pcb` | https://github.com/floxcap/fly2040 | `pcb/cpu_flex/cpu_flex.kicad_pcb` | `efd34028a29b96322d9d85ffb3281dea2220937e` (main) | MIT (`LICENSE`, (c) 2023 floxcap) | `3379fe8526fea9484599b0f5b19fb122a8cac13a9a654c105adc1994f7fb04f6` |

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
- **hackrf-one** (Great Scott Gadgets' HackRF One SDR) — KiCad 6 file format (20211014), **4 layers** with user-named copper
  (`C1F` / `C2` / `C3` / `C4B`, so kicad-cli names the Gerbers `-C1F.gtl` / `-C4B.gbl`), **437 footprints**, all top, from the
  project's `hackrf` (395) and `gsg-modules` (23) libraries plus 19 placed without a library prefix (`GSG-TESTPOINT-30MIL-MASKONLY`,
  `GSG-MARK1MM` - a KiCad 5 import; the harness files them under `local`); 17 of those share the reference
  `TESTPOINT-30MIL-MASKONLY` and have mask-only pads (no copper); rotations 0 / ±45 / ±90 / ±135 / 180; 1639 pads; outline
  18 lines + 14 arcs; 3817 segments, 498 vias, 9 zones.  Carries `(tedit 527E5841)`-style hex stamps (see the DSL fix in
  tests/pcb/README.md).  Stored gzip-compressed (4.6 MB).  The volume case.
- **mozc-doublesided-main-panel** (Google's Gboard double-sided keyboard, the main panel) — KiCad 8 (20240108), **4 layers**, a
  V-cut panel of 9 copies: 234 footprints of which 189 on B.Cu, 6 libraries (117 footprints in the installed library), every
  reference 9 times (`U1`, `SW1` ...) with the same net names in every copy; 1251 pads of which 216 oval slots and 396 NPTH;
  outline 4 lines, `v-cut` texts on User.2; 4572 segments, 324 vias, 18 zones.  Stored gzip-compressed (4.8 MB).
- **aykevl-earring-rgb36-v3** (a ring of 36 RGB LEDs) — KiCad 9 (20241229), 2 layers, 63 footprints, 5 on B.Cu, 5 libraries;
  50 distinct rotations (every 10 deg plus 25.71 / 51.43 / 77.14 / 102.86 / 128.57 / 154.29); 243 pads, 6 NPTH; Edge.Cuts = 4 arcs
  + 4 `gr_curve` beziers at board level that stop 3.4 mm short at the top, closed by 2 `fp_line` + 1 `fp_arc` inside the hanger
  footprint; 703 segments, 76 vias.
- **jumperless-probe** (Architeuthis Flux's Jumperless probe) — KiCad 8, 2 layers, 18 footprints, all top, one project library
  (`JumperlessFootprints`); 418 pads of which 80 custom (primitives), 10 chamfered (`chamfer`), 311 roundrect with ratios 0.05 /
  0.2 / 0.4 / 0.45 / 0.5, 3 slots; 80 `fp_line` items on Edge.Cuts and copper `fp_*` graphics inside the footprints (the tip);
  outline 3 lines + 10 arcs, two of them 58 mm radius over a 3.2 mm chord (the flat-arc case); 238 segments, no vias.
- **toraneko-mk3-panel** (ToraNeko Mk3 encoder boards, hand-panelised) — KiCad 9, 2 layers, 21 footprints, 6 on B.Cu, 4 libraries
  (6 footprints installed); Edge.Cuts = a `gr_rect` frame + 9 `gr_poly` cutouts (28-123 vertices: the rails and mouse-bite slots)
  + 1 `gr_circle`; 186 pads of which 54 NPTH (`MouseBites` MB1 = 48 holes, `UpperPlateHoles` H101 = 6), 36 roundrect with ratio
  0.2; 219 segments, 36 vias.
- **wiimote-ir-sensor-kikit-panel** (a PixArt IR sensor adapter, KiKit 2-up panel) — KiCad 9, 2 layers, 92 footprints, 12 on B.Cu,
  8 libraries (18 installed): 64 `Panelization:NPTH-0.5mm` mouse-bite footprints (reference `REF**`, one NPTH pad each) and 6 NPTH
  tooling holes; two copies of the board with the same references (`X1` twice ...) and KiKit's per-copy net names
  (`Board_0-GND` / `Board_1-GND`); 158 pads, 4 custom; outline 46 lines (frame + tabs, 1 inner loop); 126 segments, 40 vias, 4 zones.
- **mumo-castellated-module** (Mumo, a castellated 4-layer module) — KiCad 9, **4 layers**, `(castellated_pads yes)` in the stackup,
  25 footprints (1 on B.Cu: a pad-less logo), 2 libraries (`Mumo Footprints` + 1 without a prefix); 99 pads of which 26 oval edge
  pads with 12 `(drill (offset ...))`, 2 custom; `gr_rect` outline; 169 segments, 44 vias, 1 zone.
- **antmicro-m2-oculink-adapter** — KiCad 9, **4 layers**, 25 footprints, 10 on B.Cu, every one from `antmicro-footprints` (embedded
  variant only); 168 pads, 2 NPTH; Edge.Cuts = 17 lines + 4 arcs + **22 `gr_circle` cutouts** (the M.2 keying and mounting
  openings); copper `fp_*` graphics inside footprints; 569 segments, 183 vias, 24 zones.  Stored gzip-compressed (1.4 MB).
- **glasgow-revC3** (Glasgow Interface Explorer) — KiCad 7 file format (20221018), **4 layers**, 272 footprints, 94 on B.Cu, 14
  libraries (195 footprints installed); `Capacitor_SMD:C_0402_1005Metric` and `C_0603_1608Metric` are each embedded with two
  different pad geometries (two library versions in one board - the harness re-expresses them as `__v2`); one part at 45 deg;
  1149 pads, 4 slots, 4 NPTH; outline 4 lines + 4 arcs; 4715 segments, 416 vias, 32 zones.  Stored gzip-compressed (3.5 MB).
- **oxplot-fpx** (a USB-PD trigger board) — **KiCad 5.1.9 file format** (20171130: `(module ...)` not `(footprint ...)`, `(page A4)`
  / `(host pcbnew ...)` header, bare symbols, `fp_text reference` / `value` on all 36 modules, hex `(tstamp ...)` stamps, `(width w)`
  strokes, Edge.Cuts arcs as centre / start / angle), 2 layers, 36 footprints, 19 on B.Cu (62 `(justify mirror)` texts), 9 libraries
  (`Resistor_SMD` 9, `Capacitor_SMD` 8, the project's `fpx` 7, `TestPoint` 4, ...; `C_0603_1608Metric` embedded with two pad geometries),
  one part at 60 deg; 164 pads of which 8 custom with `(anchor ...)` primitives (paste-only), 4 oval slots (the USB-C shell); the two
  `MH` mounting-hole modules have nine pads each all numbered 1, three on GND and six on no net; outline 4 lines + 4 arcs; 237 segments,
  14 vias of which one is written `(via blind ...)` but spans F.Cu to B.Cu (a through via with a stray flag), 5 zones.
- **fomu-pvt** (Fomu, the FPGA in a USB port, PVT revision) — **KiCad 5.0.1 file format**, **4 layers** in a 0.6 mm board, 55 modules
  (50 on B.Cu, 2 pad-less, 138 mirrored texts), every one from the project's `tomu-fpga` library (embedded variant only); 222 pads of
  which 36 custom with anchors, 2 trapezoid, 74 copper-less (paste-only); **249 vias, none through: 196 `(via micro ...)` (29 F.Cu-In1.Cu,
  167 In2.Cu-B.Cu) and 53 `(via blind ...)` In1.Cu-In2.Cu (buried)**, drills from the setup's `via_drill` / `uvia_drill` when a via
  carries none; outline 89 lines + 6 KiCad 5 angle arcs; 579 segments, 24 zones, 1 keepout.
- **advanced-linear-motor** (a planar linear-motor coil board) — KiCad 8 (20240108), **6 layers** (`F.Cu In1.Cu In2.Cu In3.Cu In4.Cu
  B.Cu`), 10 footprints (4 `MountingHole` NPTH-only, 4 `Resistor_SMD`, 2 `Connector_JST`; all installed), 17 pads; `gr_rect` outline;
  1080 segments (the coils on every layer), **60 vias, all blind / buried: 20 F.Cu-In1.Cu, 20 In2.Cu-In3.Cu, 20 In4.Cu-B.Cu** (kicad-cli
  writes a drill file per span); 8 dimensions.  The path in the repository has a space in it.
- **placebo** (dotcypress's placebo board) — KiCad 7 (20221018), 2 layers, 18 footprints (1 on B.Cu: a logo; 3 pad-less), 9 libraries,
  2 placed without a library prefix (`LOGO`, `kibuzzard-631021FD`), one part at 8 deg; 79 pads, 3 NPTH; **no Edge.Cuts item at board
  level: the outline is 14 `fp_line` items inside the locked footprint `placebo:PlaceboConnect_Cutout`**; 197 segments + **102 `(arc ...)`
  track items** (rounded routing), 10 vias, 51 zones of which **50 teardrops** (`(attr (teardrop ...))`); texts positioned `(at x y unlocked)`.
- **locust** (an nRF5340 board) — KiCad 7.99 / 8-nightly file format (20231007: `(property ...)` fields with `tstamp`), 2 layers, 42
  footprints (3 on B.Cu) from 16 libraries (38 installed), **5 `NetTie:*` footprints with `(net_tie_pad_groups ...)`** whose pads are
  joined by copper `fp_poly` graphics (6 copper fp items); 343 pads: 4 oval slots (USB-C), 1 chamfered, 6 NPTH, 20 copper-less, roundrect
  ratios 0.05-0.25; outline 8 lines + 8 arcs; **unrouted: 0 segments, 0 vias, 0 zones** (placement only); 153 nets.
- **adsbee-panel-saw-eval** (SAW-filter evaluation coupons, panelised) — KiCad 8, 2 layers, **a V-cut panel of 12 coupons** (5 `V-CUT`
  texts; outline = 14 lines, the frame + coupon boundaries), 36 footprints all from the project's `Custom_Connector_Coaxial` (24) /
  `Custom_Filter` (12) libraries (embedded variant only), the references `J1` / `J2` / `X1` each 12 times with KiKit-style per-copy nets
  (`Board_0-/RF_IN` ... `Board_11-/RF_IN`); 192 pads; 48 segments, 96 vias, 24 zones of which **12 keepout rule areas** (`(keepout
  (tracks not_allowed) ...)` around the RF paths).
- **olimex-esp32-poe-revM2** (Olimex ESP32-PoE, revision M2) — KiCad 7 (20221018), **4 layers**, 143 footprints of which **84 on B.Cu**
  (6 pad-less, 191 mirrored texts), every one from the 12 project `OLIMEX_*-FP` libraries (embedded variant only), one part at 135 deg;
  603 pads: 6 oval slots, 10 trapezoid, 13 NPTH, 105 copper-less; 8-line outline; 2528 segments, 233 vias, 636 zones of which **608
  teardrops** and 8 keepout rule areas.  Stored gzip-compressed (2.8 MB).
- **neopico-hd-fpc20** (a 20-way FPC adapter) — KiCad 9 (20241229), 2 layers (FR4 1.51 mm core; a `Stiffener - Polyimide` note on
  User.1), 3 footprints (`TestPoint`, `Connector_FFC-FPC` installed; the project's `Library:MVS_Color_Latches`), 77 pads of which **54
  custom pads with `(anchor ...)` primitives and a `(drill (offset ...))` each**; Edge.Cuts = 3 `gr_rect` + 1 `gr_poly` (the rects are
  cutouts inside the polygon); 144 segments, 8 vias, 2 zones, 54 nets.
- **fly2040-cpu-flex** (fly2040, the CPU flex) — KiCad 7 (20221018), 2 layers on a **0.025 mm Polyimide core (a flex circuit)**, 9
  footprints of which 5 on B.Cu (13 mirrored texts), 7 from the project's `kicad_lceda` library + 2 `Resistor_SMD` (installed); 33 pads
  with 4 `(drill (offset ...))`; Edge.Cuts = 5 `gr_poly` (the flex outline with its tail + 4 finger slots); 12 segments, 20 vias, 4 zones,
  2 `(group ...)` blocks.

Library drift seen on 2026-10-07 with the KiCad 10.0 footprint library on the hub: the stepper board's `D_DO-41_SOD81_P10.16mm_Horizontal`
and `CP_Radial_D4.0mm_P2.00mm` / `CP_Radial_Tantal_D4.5mm_P2.50mm` pads changed shape between the KiCad 9 library the board
embeds and the installed one (rect / oval -> roundrect / circle; 6 pads).  The `library` variant of the comparison reports and
tolerates exactly those pads; the `embedded` variant (the originals' own footprints) must match completely.  The newer boards'
drift is listed in the terminal summary of a run.
