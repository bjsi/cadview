"""Cables — a cable is declared by what it connects; the viewer routes it live.

    from openworkshop.cables import Cable

    motor = Cable("X motor", d=6, bend_r=30, slack=1.15,
                  ends=[("frame", (-300, -200, 40), (0, 0, 1)),        # part, rest-pose point (world mm), exit direction
                        ("X carriage", (0, 60, 120), (0, 1, 0))],
                  via=[("Y stage", (-100, 180, 200), None)])            # clips: points that ride a part
    show(build() + motor.solid(), cables=[motor], animation=...)

Anchors are points on parts, given where they are in the rest pose; the
viewer re-reads them from each part's current transform every frame, so a
cable follows the carriage it is plugged into without any track of its own.
The centreline is a Catmull-Rom spline through the anchors, leaving each end
along its exit direction (a lead of `bend_r`), with a free span's slack hung
as a sag below the straight line (gravity -Z, the same rule here and in the
viewer). `solid()` sweeps a circle of diameter `d` along that rest-pose path
in build123d — the real part for the exported model, labelled by the cable's
name, which the viewer hides while it draws the live tube in its place.

`length()` is the rest-pose path length (slack included): what to cut, and
what the build guide's kit lists. A `plug` chapter name makes the assembly
clip draw the cable only from that chapter on.
"""
from __future__ import annotations

import math

GRAVITY = (0.0, 0.0, -1.0)


def _v(p):
    return tuple(float(x) for x in p)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _len(a):
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def _unit(a):
    n = _len(a) or 1.0
    return _mul(a, 1 / n)


def sag_depth(span, slack):
    """How far a cable of length span*slack hangs below a span's straight line (mm):
    the catenary's sag to first order, g² = (s - x)(s + x/2), s = x*slack (John D. Cook)."""
    s = span * slack
    return math.sqrt(max(0.0, (s - span) * (s + span / 2)))


def route_points(anchors, bend_r, slack):
    """The control points the viewer and solid() share: each end leads out along its direction by
    bend_r, each free span with slack gets a mid point hung by its sag. anchors = [(point, dir|None)]."""
    pts = []
    n = len(anchors)
    for i, (p, d) in enumerate(anchors):
        p = _v(p)
        if i == 0 and d:
            pts += [p, _add(p, _mul(_unit(d), bend_r))]
        elif i == n - 1 and d:
            pts += [_add(p, _mul(_unit(d), bend_r)), p]
        else:
            pts.append(p)
    if slack > 1.0:
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            span = _len(_sub(b, a))
            g = sag_depth(span, slack)
            if g > 0.5 and span > 4 * bend_r:          # only real spans hang, not the end leads
                out.append(_add(_mul(_add(a, b), 0.5), _mul(GRAVITY, g)))
            out.append(b)
        pts = out
    return pts


class Cable:
    def __init__(self, name, ends, via=(), *, d=6.0, bend_r=None, slack=1.1, color=(0.12, 0.12, 0.14), plug=None):
        if len(ends) != 2:
            raise ValueError("ends: exactly two (part, point, direction)")
        self.name = str(name)
        self.d = float(d)
        self.bend_r = float(bend_r if bend_r is not None else 5 * d)
        self.slack = float(slack)
        self.color = tuple(color)
        self.plug = plug
        a, b = ends
        self.anchors = [self._anchor(a, "end")] + [self._anchor(v, "via") for v in via] + [self._anchor(b, "end")]

    @staticmethod
    def _anchor(spec, kind):
        part, point = spec[0], spec[1]
        direction = spec[2] if len(spec) > 2 else None
        return {"part": str(part), "at": list(_v(point)), "dir": list(_unit(_v(direction))) if direction else None, "kind": kind}

    def points(self):
        return route_points([(a["at"], a["dir"]) for a in self.anchors], self.bend_r, self.slack)

    def descriptor(self):
        """What show(cables=[...]) sends: the viewer re-solves the route from its parts every frame."""
        return {"name": self.name, "d": self.d, "bend_r": self.bend_r, "slack": self.slack, "color": list(self.color),
                "plug": self.plug, "anchors": self.anchors}

    def path(self):
        """The rest-pose centreline as a build123d Wire (a Spline through the route points, tangent to the end directions)."""
        from build123d import Spline, Vector
        pts = self.points()
        d0, d1 = self.anchors[0]["dir"], self.anchors[-1]["dir"]
        tangents = [Vector(*d0) if d0 else None, Vector(*_mul(d1, -1)) if d1 else None]
        if all(t is not None for t in tangents):
            return Spline(*pts, tangents=tangents)
        return Spline(*pts)

    def length(self):
        return float(self.path().length)

    def solid(self):
        """The cable as a build123d Part: a circle of diameter d swept along the rest-pose path."""
        from build123d import Circle, Plane, Vector, sweep
        path = self.path()
        start = path.position_at(0)
        tangent = path.tangent_at(0)
        section = Plane(origin=start, z_dir=Vector(tangent)) * Circle(self.d / 2)
        body = sweep(section, path=path)
        body.label, body.color = self.name, self.color
        return body


__all__ = ["Cable", "route_points", "sag_depth", "GRAVITY"]
