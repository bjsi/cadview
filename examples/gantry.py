"""Gantry — a 1000 x 500 belt-driven XY stage on a 20-series frame with a
stacked two-axis Z and a gripper over a bed of samples (a lab robot,
condensed). Nested groups ride on each other — Y stage > X carriage > Z1 >
Z2 > gripper — so one clip with tracks on five nodes is a full pick-and-
place, and the ⚠ clearance check has real work to do.

    python examples/gantry.py           -> http://127.0.0.1:3941/gantry
"""
import os

from build123d import Align, Box, Color, Compound, Cylinder, Pos, Rot

os.environ.setdefault("CADVIEW_SCENE", "gantry")

X_RAIL, Y_RAIL = 1000.0, 500.0           # actuator rail lengths
DECK_H = 450.0                           # base top -> deck
BEAM_W, BEAM_H = 40.0, 20.0              # 2040 lying flat
POST = 40.0
RAIL_W, RAIL_H = 20.0, 40.0              # actuator rail section (carriage rides the narrow face)
PLATE, PLATE_T, LIFT = 65.5, 3.0, 2.5    # gantry plate, its thickness, gap over the rail
TRAVEL_LOSS = 154.0                      # plate + end-stops
BED_Z = 26.0
UP = (Align.CENTER, Align.CENTER, Align.MIN)

ALU = Color(0.78, 0.80, 0.83)
RAIL = Color(0.62, 0.64, 0.68)
PLATE_C = Color(0.16, 0.16, 0.18)
MOTOR = Color(0.22, 0.22, 0.24)
BED = Color(0.85, 0.83, 0.78)
GRIP = Color(0.85, 0.45, 0.15)
LID = Color(0.85, 0.88, 1.0, 0.25)
SAMPLES = [Color(0.85, 0.3, 0.3), Color(0.3, 0.6, 0.9), Color(0.95, 0.75, 0.2), Color(0.4, 0.75, 0.4)]


def part(shape, label, color):
    shape.label, shape.color = label, color
    return shape


def nema17(label):
    body = Box(42.3, 42.3, 40, align=UP) + Pos(0, 0, 40) * Cylinder(2.5, 22, align=UP)
    return part(body, label, MOTOR)


def frame():
    parts = []
    base_z = BEAM_H / 2
    for sy, name in ((-1, "front beam (2060 arm rail)"), (1, "rear beam")):
        w = 60 if sy < 0 else BEAM_W
        parts.append(part(Pos(0, sy * (Y_RAIL / 2 - w / 2), base_z) * Box(X_RAIL, w, BEAM_H), name, ALU))
    for sx in (-1, 1):
        parts.append(part(Pos(sx * (X_RAIL / 2 - BEAM_W / 2), 0, base_z) * Box(BEAM_W, Y_RAIL - 100, BEAM_H),
                          f"side beam {'left' if sx < 0 else 'right'}", ALU))
        for sy in (-1, 1):
            parts.append(part(Pos(sx * (X_RAIL / 2 - POST / 2), sy * (Y_RAIL / 2 - BEAM_H / 2), BEAM_H) * Box(POST, BEAM_H, DECK_H, align=UP),
                              f"post {'front' if sy < 0 else 'rear'} {'left' if sx < 0 else 'right'}", ALU))
    parts.append(part(Pos(0, 0, BED_Z) * Box(X_RAIL - 2 * POST, Y_RAIL - 60, 6), "bed", BED))
    for i, (x, y) in enumerate(((-120, -40), (0, 40), (120, -30), (240, 50))):
        parts.append(part(Pos(x, y, BED_Z + 3) * Cylinder(22, 14, align=UP), f"sample {'ABCD'[i]}", SAMPLES[i]))
    parts.append(part(Pos(0, 0, BEAM_H + DECK_H + RAIL_H + 60) * Box(X_RAIL, Y_RAIL, 8), "LED lightbox lid", LID))
    return Compound(children=parts, label="frame")


def gantry(cx=0.5, cy=0.5, cz=0.3):
    deck_z = BEAM_H + DECK_H                              # top of the posts
    y_travel, x_travel = Y_RAIL - TRAVEL_LOSS, X_RAIL - TRAVEL_LOSS
    y0 = -y_travel / 2 + cy * y_travel
    x0 = -x_travel / 2 + cx * x_travel
    rails = []
    for sx in (-1, 1):
        x = sx * (X_RAIL / 2 - POST / 2)
        rails.append(part(Pos(x, 0, deck_z) * Box(RAIL_W, Y_RAIL, RAIL_H, align=UP), f"Y rail {'left' if sx < 0 else 'right'}", RAIL))
        rails.append(Pos(x, Y_RAIL / 2 + 20, deck_z + RAIL_H - 40) * Rot(90, 0, 0) * nema17(f"Y motor {'left' if sx < 0 else 'right'}"))
    plate_z = deck_z + RAIL_H + LIFT                      # underside of the Y carriage plates
    y_parts = []
    for sx in (-1, 1):
        x = sx * (X_RAIL / 2 - POST / 2)
        y_parts.append(part(Pos(x, 0, plate_z) * Box(PLATE, PLATE, PLATE_T, align=UP), f"Y carriage {'left' if sx < 0 else 'right'}", PLATE_C))
    x_rail_z = plate_z + PLATE_T
    y_parts.append(part(Pos(0, 0, x_rail_z) * Box(X_RAIL, RAIL_W, RAIL_H, align=UP), "X rail", RAIL))
    y_parts.append(Pos(-X_RAIL / 2 - 20, 0, x_rail_z) * Rot(0, -90, 0) * nema17("X motor"))
    xplate_z = x_rail_z + RAIL_H + LIFT
    x_parts = [part(Pos(0, 0, xplate_z) * Box(PLATE, PLATE, PLATE_T, align=UP), "X carriage plate", PLATE_C)]
    # stacked Z hangs off the X plate's rear face: Z1 rail fixed, Z1 carriage
    # carries the Z2 rail, Z2 carriage carries the gripper bar
    z1_len, z2_len = 300.0, 200.0
    z1_top = xplate_z + PLATE_T
    x_parts.append(part(Pos(0, PLATE / 2 + RAIL_W / 2, z1_top - z1_len) * Box(RAIL_H, RAIL_W, z1_len, align=UP), "Z1 rail", RAIL))
    x_parts.append(Pos(0, PLATE / 2 + RAIL_W / 2, z1_top) * nema17("Z1 motor"))
    z1_y = PLATE / 2 + RAIL_W + LIFT
    z1_c = z1_top - 90 - cz * (z1_len - 110)              # Z1 carriage plate centre height
    z1_parts = [part(Pos(0, z1_y, z1_c) * Box(PLATE, PLATE_T, PLATE, align=(Align.CENTER, Align.MIN, Align.CENTER)), "Z1 carriage plate", PLATE_C)]
    z2_y = z1_y + PLATE_T + RAIL_W / 2
    z1_parts.append(part(Pos(0, z2_y, z1_c + 60 - z2_len) * Box(RAIL_H, RAIL_W, z2_len, align=UP), "Z2 rail", RAIL))
    z1_parts.append(Pos(0, z2_y, z1_c + 60) * nema17("Z2 motor"))
    z2_yp = z2_y + RAIL_W / 2 + LIFT
    z2_c = z1_c + 60 - z2_len + 70
    z2_parts = [part(Pos(0, z2_yp, z2_c) * Box(PLATE, PLATE_T, PLATE, align=(Align.CENTER, Align.MIN, Align.CENTER)), "Z2 carriage plate", PLATE_C)]
    bar_z = z2_c - PLATE / 2 - 10
    z2_parts.append(part(Pos(0, z2_yp + 14, bar_z) * Box(120, 24, 12), "gripper bar", GRIP))
    for sx, name in ((-1, "finger left"), (1, "finger right")):
        z2_parts.append(part(Pos(sx * 40, z2_yp + 14, bar_z - 6 - 60) * Box(10, 20, 60, align=UP), name, GRIP))
    z1_parts.append(Compound(children=z2_parts, label="Z2 stage"))
    x_parts.append(Compound(children=z1_parts, label="Z1 stage"))
    y_parts.append(Pos(x0, 0, 0) * Compound(children=x_parts, label="X carriage"))
    stage = Pos(0, y0, 0) * Compound(children=y_parts, label="Y stage")
    return Compound(children=rails + [stage], label="XY stage")


def build(cx=0.5, cy=0.5, cz=0.3):
    return Compound(children=[frame(), gantry(cx, cy, cz)], label="gantry")


# pick-and-place: the stage drives over sample C, both Z axes drop, the
# fingers close, everything lifts and carries it to the right — tracks on
# nested nodes compose (the gripper moves with Z2, Z2 with Z1, Z1 with X)
PICK = [
    ("Y stage", "ty", [0, 0.5, 2.0, 5.5, 7.0, 8.5], [0, 0, -125, -125, -35, -35]),
    ("X carriage", "tx", [0, 0.5, 2.0, 5.5, 7.0, 8.5], [0, 0, 120, 120, 300, 300]),
    ("Z1 stage", "tz", [0, 2.0, 3.0, 4.5, 5.5, 7.0, 8.0], [0, 0, -150, -150, 0, 0, -150]),
    ("Z2 stage", "tz", [0, 3.0, 3.6, 4.4, 5.0, 7.3, 8.0], [0, 0, -50, -50, 0, 0, -50]),
    ("finger left", "tx", [0, 3.8, 4.2, 8.0, 8.4], [0, 0, 12, 12, 0]),
    ("finger right", "tx", [0, 3.8, 4.2, 8.0, 8.4], [0, 0, -12, -12, 0]),
    # the sample is not a child of the gripper, so it gets the ride spelled out
    ("sample C", "tz", [0, 4.4, 5.0, 5.5, 7.0, 7.3, 8.0], [0, 0, 50, 200, 200, 150, 0]),
    ("sample C", "tx", [0, 5.5, 7.0], [0, 0, 180]),
    ("sample C", "ty", [0, 5.5, 7.0], [0, 0, 90]),
]
JOG = [
    ("Y stage", "ty", [0, 1.5, 3.0], [-150, 150, -150]),
    ("X carriage", "tx", [0, 0.75, 1.5, 2.25, 3.0], [-380, 380, -380, 380, -380]),
]

# chapters: ticks on the scrub bar, named next to the time, click to jump,
# cadview_snapshot(chapter="grip") for an agent; a chapter can bring its
# own camera, posed when it starts (the grip gets a close-up on the gripper)
CHAPTERS = [(0, "approach"), (3.0, "descend"), (3.8, "grip", {"focus": "Z2 stage", "zoom": 1.6}),
            (4.5, "lift & carry", {"view": "iso"}), (7.0, "place"), (8.0, "release")]

if __name__ == "__main__":
    from cadview import show
    show(build(), title="Gantry",
         animation=[{"name": "pick & place", "tracks": PICK, "chapters": CHAPTERS},
                    {"name": "jog", "tracks": JOG, "speed": 1}])
