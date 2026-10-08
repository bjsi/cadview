"""The 12 V stepper playground — a real Pico board (John McAleely, MIT), laid out
again through openworkshop.pcb: the same 82 x 68 mm outline, the same seventeen
KiCad library footprints at the same places, the same 41 nets on the same pads,
written back out as a KiCad project + JLCPCB files and shown with the parts'
STEP models on the board.

    python examples/stepper_board.py        -> http://127.0.0.1:3941/stepper-board

Source: https://github.com/jhmcaleely/stepper-playground (12v-pico/12v-pico.kicad_pcb,
commit d3c5cc9), MIT licence, (c) 2022 John McAleely — the placement and netlist below are
that board's, re-expressed; copper routing is not reproduced (route it in KiCad or with
tools/pcb/export.mjs). Needs `pip install openworkshop[pcb]` and KiCad's libraries on disk.
"""
import os
from pathlib import Path

from build123d import Pos, RectangleRounded

from openworkshop.pcb import Board, kicad_footprint

os.environ.setdefault("OPENWORKSHOP_SCENE", "stepper-board")

W, H = 82.0, 68.0                  # the board's Edge.Cuts rectangle, lower-left at (0, 0)

# ref, KiCad footprint (library, name), place (x, y) mm from the lower-left corner, rotation, value
PARTS = [
    ('A1', ('Module', 'RaspberryPi_Pico_SMD_HandSolder'), (27.06, 41.53), 0, 'RaspberryPi_Pico'),
    ('C1', ('Capacitor_THT', 'CP_Radial_D4.0mm_P2.00mm'), (70.5, 24.0), 270, '100uF, 25V'),
    ('C2', ('Capacitor_THT', 'CP_Radial_Tantal_D4.5mm_P2.50mm'), (70.5, 14.5), 90, '4.7uF'),
    ('D1', ('Diode_THT', 'D_DO-41_SOD81_P10.16mm_Horizontal'), (77.5, 28.92), 90, '1N4002'),
    ('D2', ('Diode_THT', 'D_DO-41_SOD81_P10.16mm_Horizontal'), (77.5, 56.08), 270, '1N5817'),
    ('J1', ('TerminalBlock_Phoenix', 'TerminalBlock_Phoenix_PT-1,5-4-3.5-H_1x04_P3.50mm_Horizontal'), (66.25, 62.29), 180, 'MERG 12v CBUS'),
    ('J2', ('Connector_PinHeader_2.54mm', 'PinHeader_1x07_P2.54mm_Vertical'), (68.58, 50.0), 270, 'Adafruit CAN Pal'),
    ('J3', ('Connector_PinHeader_2.54mm', 'PinHeader_1x03_P2.54mm_Vertical'), (24.52, 9.02), 90, 'DEBUG'),
    ('J4', ('Connector_PinSocket_2.54mm', 'PinSocket_1x03_P2.54mm_Vertical'), (5.5, 55.0), 0, 'UART0'),
    ('J5', ('Connector_PinHeader_2.54mm', 'PinHeader_1x20_P2.54mm_Vertical'), (11.82, 65.66), 0, 'Pico LHS'),
    ('J6', ('Connector_PinHeader_2.54mm', 'PinHeader_1x20_P2.54mm_Vertical'), (42.3, 65.66), 0, 'Pico RHS'),
    ('SW1', ('Button_Switch_THT', 'SW_PUSH_6mm'), (41.75, 4.75), 180, 'RESET'),
    ('U1', ('Package_TO_SOT_THT', 'TO-220-3_Vertical'), (77.5, 22.0), 270, 'LM7805_TO220'),
    ('H1', ('MountingHole', 'MountingHole_3.2mm_M3_Pad'), (4.46, 63.0), 0, 'MountingHole_3.2mm_M3_Pad'),
    ('H2', ('MountingHole', 'MountingHole_3.2mm_M3_Pad'), (4.5, 5.0), 0, 'MountingHole_3.2mm_M3_Pad'),
    ('H3', ('MountingHole', 'MountingHole_3.2mm_M3_Pad'), (77.5, 5.0), 0, 'MountingHole_3.2mm_M3_Pad'),
    ('H4', ('MountingHole', 'MountingHole_3.2mm_M3_Pad'), (77.5, 63.0), 0, 'MountingHole_3.2mm_M3_Pad'),
]
# schematic symbols per footprint (the Pico has none in KiCad's library, so the
# schematic is skipped below — the board, netlist and JLC files do not need it)
SYMBOLS = {
    'Capacitor_THT:CP_Radial_D4.0mm_P2.00mm': ('Device', 'C_Polarized'),
    'Capacitor_THT:CP_Radial_Tantal_D4.5mm_P2.50mm': ('Device', 'C_Polarized'),
    'Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal': ('Device', 'D'),
    'TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-4-3.5-H_1x04_P3.50mm_Horizontal': ('Connector_Generic', 'Conn_01x04'),
    'Connector_PinHeader_2.54mm:PinHeader_1x07_P2.54mm_Vertical': ('Connector_Generic', 'Conn_01x07'),
    'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical': ('Connector_Generic', 'Conn_01x03'),
    'Connector_PinSocket_2.54mm:PinSocket_1x03_P2.54mm_Vertical': ('Connector_Generic', 'Conn_01x03'),
    'Connector_PinHeader_2.54mm:PinHeader_1x20_P2.54mm_Vertical': ('Connector_Generic', 'Conn_01x20'),
    'MountingHole:MountingHole_3.2mm_M3_Pad': ('Mechanical', 'MountingHole_Pad'),
    'Button_Switch_THT:SW_PUSH_6mm': ('Switch', 'SW_Push'),
    'Package_TO_SOT_THT:TO-220-3_Vertical': ('Regulator_Linear', 'LM7805_TO220'),
}
# net -> (ref, pad) — the original board's netlist
NETS = {
    'GND': [('A1', '13'), ('A1', '18'), ('A1', '23'), ('A1', '28'), ('A1', '3'), ('A1', '38'), ('A1', '8'), ('A1', 'D2'), ('C1', '2'), ('C2', '2'), ('J1', '4'), ('J2', '2'), ('J3', '2'), ('J4', '2'), ('J5', '13'), ('J5', '18'), ('J5', '3'), ('J5', '8'), ('J6', '13'), ('J6', '18'), ('J6', '3'), ('SW1', '1'), ('U1', '2')],
    'Net-(A1-3V3)': [('A1', '36'), ('J2', '1'), ('J6', '5')],
    'Net-(A1-3V3_EN)': [('A1', '37'), ('J6', '4')],
    'Net-(A1-ADC_VREF)': [('A1', '35'), ('J6', '6')],
    'Net-(A1-AGND)': [('A1', '33'), ('J6', '8')],
    'Net-(A1-GPIO0)': [('A1', '1'), ('J4', '3'), ('J5', '1')],
    'Net-(A1-GPIO1)': [('A1', '2'), ('J4', '1'), ('J5', '2')],
    'Net-(A1-GPIO10)': [('A1', '14'), ('J5', '14')],
    'Net-(A1-GPIO11)': [('A1', '15'), ('J5', '15')],
    'Net-(A1-GPIO12)': [('A1', '16'), ('J5', '16')],
    'Net-(A1-GPIO13)': [('A1', '17'), ('J5', '17')],
    'Net-(A1-GPIO14)': [('A1', '19'), ('J5', '19')],
    'Net-(A1-GPIO15)': [('A1', '20'), ('J5', '20')],
    'Net-(A1-GPIO16)': [('A1', '21'), ('J6', '20')],
    'Net-(A1-GPIO17)': [('A1', '22'), ('J6', '19')],
    'Net-(A1-GPIO18)': [('A1', '24'), ('J6', '17')],
    'Net-(A1-GPIO19)': [('A1', '25'), ('J6', '16')],
    'Net-(A1-GPIO2)': [('A1', '4'), ('J2', '3'), ('J5', '4')],
    'Net-(A1-GPIO20)': [('A1', '26'), ('J6', '15')],
    'Net-(A1-GPIO21)': [('A1', '27'), ('J6', '14')],
    'Net-(A1-GPIO22)': [('A1', '29'), ('J6', '12')],
    'Net-(A1-GPIO26_ADC0)': [('A1', '31'), ('J6', '10')],
    'Net-(A1-GPIO27_ADC1)': [('A1', '32'), ('J6', '9')],
    'Net-(A1-GPIO28_ADC2)': [('A1', '34'), ('J6', '7')],
    'Net-(A1-GPIO3)': [('A1', '5'), ('J2', '4'), ('J5', '5')],
    'Net-(A1-GPIO4)': [('A1', '6'), ('J2', '5'), ('J5', '6')],
    'Net-(A1-GPIO5)': [('A1', '7'), ('J5', '7')],
    'Net-(A1-GPIO6)': [('A1', '9'), ('J5', '9')],
    'Net-(A1-GPIO7)': [('A1', '10'), ('J5', '10')],
    'Net-(A1-GPIO8)': [('A1', '11'), ('J5', '11')],
    'Net-(A1-GPIO9)': [('A1', '12'), ('J5', '12')],
    'Net-(A1-RUN)': [('A1', '30'), ('J6', '11'), ('SW1', '2')],
    'Net-(A1-SWCLK)': [('A1', 'D1'), ('J3', '1')],
    'Net-(A1-SWDIO)': [('A1', 'D3'), ('J3', '3')],
    'Net-(A1-VBUS)': [('A1', '40'), ('J6', '1')],
    'Net-(A1-VSYS)': [('A1', '39'), ('D2', '1'), ('J6', '2')],
    'Net-(D1-A)': [('D1', '2'), ('J1', '1')],
    'Net-(D1-K)': [('C1', '1'), ('D1', '1'), ('U1', '1')],
    'Net-(D2-A)': [('C2', '1'), ('D2', '2'), ('U1', '3')],
    'Net-(J1-CANH)': [('J1', '3'), ('J2', '6')],
    'Net-(J1-CANL)': [('J1', '2'), ('J2', '7')],
}


def build():
    face = Pos(W / 2, H / 2, 0) * RectangleRounded(W, H, 2).faces()[0]
    b = Board(face, thickness=1.6, name="stepper-playground", z=0)
    for ref, (lib, name), at, rot, value in PARTS:
        b.place(kicad_footprint(lib, name), ref, at, rot=rot, value=value, center_pads=False,
                symbol=SYMBOLS.get(f"{lib}:{name}"))
    for net, pins in NETS.items():
        b.net(net, *pins)
    b.pour("GND", "B.Cu")
    return b


if __name__ == "__main__":
    from openworkshop import show
    b = build()
    out = Path("out/stepper-board")
    out.mkdir(parents=True, exist_ok=True)
    b.write_kicad(str(out), "stepper-playground", schematic=False)   # .kicad_pcb / .kicad_pro / .net
    b.write_jlc(str(out))                                               # bom.csv / cpl.csv / bom_full.csv
    print("wrote", sorted(p.name for p in out.iterdir()))
    show(b.solid(), names=["stepper playground"], title="12 V stepper playground (Pico)")
