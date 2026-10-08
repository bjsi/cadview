"""A sensor board laid out from the CAD: the enclosure's floor gives the
outline and the four standoff holes, KiCad's own libraries give the
footprints, and the populated board goes back into the assembly — plus a
.kicad_pcb / schematic / JLCPCB files in out/board/.

    python examples/board.py            -> http://127.0.0.1:3941/board

Needs `pip install cadview[pcb]` and KiCad's footprint + 3D libraries on
disk (KICAD_FOOTPRINTS / KICAD_3DMODELS, defaults are the Linux paths).
"""
import os
from pathlib import Path

from build123d import Align, Box, Circle, Color, Compound, Cylinder, Pos, RectangleRounded

from cadview.pcb import Board, kicad_footprint

os.environ.setdefault("CADVIEW_SCENE", "board")
UP = (Align.CENTER, Align.CENTER, Align.MIN)

# ---- the enclosure (from examples/parts.py): 90 x 60 x 30, 4 mm walls, 3 mm floor
FLOOR_Z, WALL = 3.0, 4.0
STANDOFFS = [(-34, -19), (34, -19), (-34, 19), (34, 19)]


def enclosure():
    body = Box(90, 60, 30, align=UP) - Pos(0, 0, FLOOR_Z) * Box(82, 52, 30, align=UP)
    for x, y in STANDOFFS:
        body += Pos(x, y, FLOOR_Z) * Cylinder(3.2, 5, align=UP)       # M2.5 standoffs, 5 tall
    body.label, body.color = "enclosure", Color(0.4, 0.55, 0.7)
    return body


# ---- the board: a Face in the floor's plane, 2 mm inside the walls, holes over the standoffs
def board_face():
    sk = RectangleRounded(82 - 4, 52 - 4, 3)
    for x, y in STANDOFFS:
        sk -= Pos(x, y) * Circle(1.35)                                   # 2.7 mm holes for M2.5
    return Pos(0, 0, FLOOR_Z + 5) * sk.faces()[0]


def board():
    b = Board(board_face(), thickness=1.6, name="sensor", z=FLOOR_Z + 5)
    b.hole_keepout(6.0)                                                  # screw heads stay copper-free
    u1 = b.place(kicad_footprint("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm"), "U1", (0, 0), value="MCP9808", lcsc="C64240",
                 symbol=("Sensor_Temperature", "MCP9808_MSOP"))
    r1 = b.place(kicad_footprint("Resistor_SMD", "R_0603_1608Metric"), "R1", (-8, 7), rot=90, value="4k7", lcsc="C23162", symbol=("Device", "R"))
    r2 = b.place(kicad_footprint("Resistor_SMD", "R_0603_1608Metric"), "R2", (8, 7), rot=90, value="4k7", lcsc="C23162", symbol=("Device", "R"))
    j1 = b.place(kicad_footprint("Connector_JST", "JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical"), "J1", (-24, -14), rot=90, value="I2C",
                 symbol=("Connector_Generic", "Conn_01x04"))
    b.net("GND", ("U1", 4), ("J1", 1))
    b.net("3V3", ("U1", 8), ("J1", 2), ("R1", 2), ("R2", 2))
    b.net("SDA", ("U1", 1), ("J1", 3), ("R1", 1))
    b.net("SCL", ("U1", 2), ("J1", 4), ("R2", 1))
    b.pour("GND", "B.Cu")
    b.label("sensor v1", (0, -17), size=1.2)
    return b


if __name__ == "__main__":
    from cadview import show
    b = board()
    out = Path("out/board")
    out.mkdir(parents=True, exist_ok=True)
    b.write_kicad(str(out), "sensor")                 # sensor.kicad_pcb / .kicad_sch / .kicad_pro / .net
    b.write_jlc(str(out))                             # bom.csv / cpl.csv / bom_full.csv
    print("wrote", sorted(p.name for p in out.iterdir()))
    show(Compound(children=[enclosure()] + b.solid(), label="sensor in its box"), title="Sensor board in its enclosure")
