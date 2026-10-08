"""Mega desk — a 2000 x 800 workbench on 3030 extrusion with shelving under a
sloping ceiling (a real desk, condensed). ~50 parts in nested groups, a
translucent ceiling, pegboard, and a shelf that is height-adjustable — so
the part tree, hide/show and a one-track animation all have something to do.

    python examples/mega_desk.py        -> http://127.0.0.1:3941/mega-desk
"""
import os

from build123d import (Align, Box, Circle, Color, Compound, Cylinder, Pos,
                       PolarLocations, Rectangle, RectangleRounded, Rot, extrude)

os.environ.setdefault("OPENWORKSHOP_SCENE", "mega-desk")

# ---- desk ------------------------------------------------------------------
DESK_L, DESK_W, TOP_T = 2000.0, 800.0, 18.0
PROF = 30.0                              # 3030 extrusion
LEG_LEN = 690.0
LEG_X, LEG_Y = DESK_L / 2 - 300, DESK_W / 2 - PROF / 2      # ±700, ±385
CROSS_LEN = DESK_W - 2 * PROF
TOP_FRAME_Z = LEG_LEN + PROF / 2
TOP_Z = LEG_LEN + PROF                   # underside of the MDF
BACK_LEG_LEN = LEG_LEN + TOP_T           # back legs one MDF thickness longer:
BACK_RAIL_TOP = BACK_LEG_LEN + PROF      # the back rail tops out flush with the MDF
DESK_TOP = TOP_Z + TOP_T

ALU = Color(0.75, 0.77, 0.80)
MDF = Color(0.55, 0.62, 0.45)
GREY = Color(0.35, 0.35, 0.38)
PRINTED = Color(0.85, 0.45, 0.15)
PEGBOARD = Color(0.72, 0.60, 0.42)
BIN = Color(0.55, 0.65, 0.85)
CEILING = Color(0.6, 0.6, 0.65, 0.35)
UP = (Align.CENTER, Align.CENTER, Align.MIN)


def part(shape, label, color):
    shape.label, shape.color = label, color
    return shape


def profile_3030():
    """A generic 3030 T-slot section — looks right, not vendor-exact."""
    sk = RectangleRounded(PROF, PROF, 2)
    slot = Pos(0, PROF / 2 - 1.6) * Rectangle(8.2, 3.2) + Pos(0, PROF / 2 - 5.5) * Rectangle(16.5, 5)
    for loc in PolarLocations(0, 4):
        sk -= loc * slot
    return sk - Circle(3.4)


PROFILE = profile_3030()


def rail(length):
    return extrude(PROFILE, amount=length)      # along +Z from z=0


def brackets_and_hardware():
    """A 3030 corner bracket inside each leg under its long rail, each held by two
    M6×12 socket screws into T-nuts — real parts from openworkshop.hardware, so the
    build guide counts them ("8 × M6×12 socket screw") without a note."""
    from openworkshop.hardware import corner_bracket, fasten, screw, t_nut
    T, P = 3.0, PROF
    brackets, hardware = [], []
    for sx in (-1, 1):
        for sy in (-1, 1):
            face = sx * (LEG_X - P / 2)                              # the leg's inner face
            under = TOP_FRAME_Z - P / 2 + (TOP_T if sy > 0 else 0)   # the long rail's underside
            flip = Rot(180, 0, 0) if sx < 0 else Rot(0, 180, 0)      # legs along +X/+Z -> into the corner
            brackets.append(part(Pos(face, sy * LEG_Y, under) * flip * corner_bracket("3030", T), "3030 corner bracket", GREY))
            hardware.append(fasten(screw("M6", 12), t_nut("M6", "3030"), grip=T,
                                   at=(face + sx * 0.6 * P, sy * LEG_Y, under - T), axis=(0, 0, 1)))        # up into the rail
            hardware.append(fasten(screw("M6", 12), t_nut("M6", "3030"), grip=T,
                                   at=(face + sx * T, sy * LEG_Y, under - 0.6 * P), axis=(-sx, 0, 0)))     # into the leg
    return brackets, Compound(children=hardware, label="frame hardware")


def desk():
    parts = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts.append(part(Pos(sx * LEG_X, sy * LEG_Y, 0) * rail(BACK_LEG_LEN if sy > 0 else LEG_LEN),
                              f"leg {'back' if sy > 0 else 'front'} {'left' if sx < 0 else 'right'}", ALU))
    for sy in (-1, 1):
        parts.append(part(Pos(-DESK_L / 2, sy * LEG_Y, TOP_FRAME_Z + (TOP_T if sy > 0 else 0)) * Rot(0, 90, 0) * rail(DESK_L),
                          f"long rail {'back' if sy > 0 else 'front'}", ALU))
    for x, name in ((-LEG_X, "cross rail left"), (0.0, "cross rail centre"), (LEG_X, "cross rail right")):
        parts.append(part(Pos(x, -CROSS_LEN / 2, TOP_FRAME_Z) * Rot(-90, 0, 0) * rail(CROSS_LEN), name, ALU))
    for sx in (-1, 1):
        parts.append(part(Pos(sx * LEG_X, -CROSS_LEN / 2, PROF / 2) * Rot(-90, 0, 0) * rail(CROSS_LEN),
                          f"foot rail {'left' if sx < 0 else 'right'}", ALU))
    brackets, hardware = brackets_and_hardware()
    parts += brackets + [hardware]
    parts.append(part(Pos(0, -PROF / 2, TOP_Z + TOP_T / 2) * Box(DESK_L, DESK_W - PROF, TOP_T), "MDF top", MDF))
    return Compound(children=parts, label="desk")


# ---- shelving under the sloping ceiling ---------------------------------------
UPRIGHT_X = (-950.0, 0.0, 950.0)
CEIL_RIGHT, CEIL_HIGH, CEIL_RUN = 900.0, 1500.0, 850.0   # above the desk top: 900 at the right end, 1500 850 mm in
SHELF_H, SHELF_D, SHELF_T = 740.0, 300.0, 16.0           # shelf top above the desk top


def ceil_h(x):
    """Ceiling height above the desk top at x (flat 1500, sloping down to 900 at the right end)."""
    run = max(0.0, x - (DESK_L / 2 - CEIL_RUN))
    return CEIL_HIGH - (CEIL_HIGH - CEIL_RIGHT) * run / CEIL_RUN


def pegboard(w, h):
    """6 mm board, 7 mm holes on a 50 mm grid (the real board is 25 mm;
    coarser keeps the example quick to build)."""
    board = Box(w, 6, h, align=UP)
    nx, nz = int((w - 90) // 50) + 1, int((h - 90) // 50) + 1
    hole = Rot(90, 0, 0) * Cylinder(3.5, 10)
    holes = Compound(children=[Pos((i - (nx - 1) / 2) * 50, 0, 45 + k * 50) * hole
                               for i in range(nx) for k in range(nz)])
    return board - holes


def shelving():
    parts = []
    for x in UPRIGHT_X:
        length = min(DESK_TOP + ceil_h(x) - 20, DESK_TOP + 1400) - BACK_RAIL_TOP
        parts.append(part(Pos(x, LEG_Y, BACK_RAIL_TOP) * rail(length), f"upright x={x:+.0f}", ALU))
    for i, (x0, x1) in enumerate(zip(UPRIGHT_X, UPRIGHT_X[1:])):
        full = i == 0                                    # right bay stops at the shelf under the slope
        h = (min(ceil_h(x1), 1400) - 60) if full else SHELF_H - SHELF_T
        parts.append(part(Pos((x0 + x1) / 2, LEG_Y, BACK_RAIL_TOP) * pegboard(x1 - x0 - PROF - 20, h),
                          f"pegboard {'left' if full else 'right'}", PEGBOARD))
    shelf_z = DESK_TOP + SHELF_H
    shelf_parts = [part(Pos(0, LEG_Y - PROF / 2 - SHELF_D / 2, shelf_z - SHELF_T / 2) * Box(DESK_L - 70, SHELF_D, SHELF_T),
                        "shelf board (MFC)", MDF)]
    from openworkshop.marks import arrow, engrave
    arm = Box(28, 220, 12, align=(Align.CENTER, Align.MAX, Align.MAX)) + Box(28, 12, 100, align=(Align.CENTER, Align.MAX, Align.MAX))
    # the printed part says what it is (its kit ID, P1 = the first printed part type) and which
    # way it goes (the arrow points at the upright): cut 0.4 mm into the arm's top, under the board
    arm = arrow(engrave(arm, "P1", size=12, at=(0, 70), rotation=90), (0, 1, 0), size=10, text="WALL", at=(0, 40))
    for x in UPRIGHT_X:
        shelf_parts.append(part(Pos(x, LEG_Y - PROF / 2, shelf_z - SHELF_T) * arm, "shelf bracket (printed)", PRINTED))
    for i, x in enumerate((-800, -700, -560, -300, 100, 350)):
        n = 2 if i % 2 else 3
        shelf_parts.append(part(Pos(x, LEG_Y - PROF / 2 - 150, shelf_z) * Box(n * 42 - 0.5, 83.5, 42, align=UP),
                                f"gridfinity bin {n}x2", BIN))
    parts.append(Compound(children=shelf_parts, label="shelf (adjustable)"))
    flat_x0, flat_x1 = -DESK_L / 2, DESK_L / 2 - CEIL_RUN
    parts.append(part(Pos((flat_x0 + flat_x1) / 2, 50, DESK_TOP + CEIL_HIGH + 20) * Box(flat_x1 - flat_x0, 900, 40),
                      "ceiling (flat)", CEILING))
    import math
    drop = CEIL_HIGH - CEIL_RIGHT
    slope_len = math.hypot(CEIL_RUN, drop)
    ang = math.degrees(math.atan2(drop, CEIL_RUN))
    parts.append(part(Pos(flat_x1 + CEIL_RUN / 2, 50, DESK_TOP + CEIL_HIGH + 20 - drop / 2) * Rot(0, ang, 0) * Box(slope_len, 900, 40),
                      "ceiling (slope)", CEILING))
    return Compound(children=parts, label="shelving")


def build():
    return Compound(children=[desk(), shelving()], label="mega desk")


# the shelf sits on T-nutted brackets: one track lifts the whole shelf group
# (board, brackets, bins) by one 180 mm pitch and back
SHELF_PITCH = [("shelf (adjustable)", "tz", [0, 0.8, 2.2, 3.2, 4.6], [0, 0, 180, 180, 0])]


def assembly():
    """The build order as a clip: each phase is a chapter, its parts start
    hidden and drop into place from 400 mm up (chapter cameras frame the work)."""
    from openworkshop import Timeline
    tl = Timeline()
    phases = [
        ("legs", ["leg front left", "leg front right", "leg back left", "leg back right",
                  "foot rail left", "foot rail right"], {"view": "iso", "zoom": 1.0}),
        ("frame", ["long rail front", "long rail back", "cross rail left", "cross rail centre", "cross rail right",
                   "3030 corner bracket", "3030 corner bracket(2)", "3030 corner bracket(3)", "3030 corner bracket(4)",
                   "frame hardware"], None),
        ("top", ["MDF top"], None),
        ("uprights", ["upright x=-950", "upright x=+0", "upright x=+950", "pegboard left", "pegboard right"],
         {"view": "front", "zoom": 1.1}),
        ("shelf", ["shelf (adjustable)"], {"focus": "shelf (adjustable)", "view": "iso", "zoom": 1.5}),
        ("ceiling", ["ceiling (flat)", "ceiling (slope)"], {"view": "iso", "zoom": 1.0}),
    ]
    t = 0.0
    for name, parts, camera in phases:
        tl.chapter(name, t, camera)
        for i, sel in enumerate(parts):
            start = t + 0.3 + 0.25 * i                         # one after another within the phase
            tl.hide(sel, start=0, until=start)
            tl.move(sel, "tz", 400, start=0, dur=0)            # parked above its place ...
            tl.move(sel, "tz", 0, start=start, dur=0.8)        # ... and lowered in
        t += 0.25 * len(parts) + 1.0
    return tl.clip("assembly", end=t)


if __name__ == "__main__":
    from openworkshop import show
    # how each part type gets made (several routes allowed, the first is the default);
    # the hardware library's parts are "buy" by themselves
    ROUTES = {"leg *": ["cut"], "* rail *": ["cut"], "upright *": ["cut"],       # extrusion cut to length
              "MDF top": ["cnc"], "shelf board (MFC)": ["cnc"], "pegboard *": ["cnc", "buy"],
              "shelf bracket (printed)": ["print"], "gridfinity bin *": ["print", "buy"],
              "ceiling (*)": ["context"]}
    show(build(), title="Mega desk", routes=ROUTES,
         animation=[assembly(), {"name": "shelf: one pitch up", "tracks": SHELF_PITCH}])
