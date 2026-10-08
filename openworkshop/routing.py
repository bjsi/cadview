"""Cable routing — a cable runs in channels (extrusion slots, trunking, clips), never through the air.

    from openworkshop.routing import Channel, Port, slots, route

    chans = slots("X rail", center=(0, 0, 535), size=(1000, 20, 40), axis="x")        # its four slot lines
    chans += slots("Y rail left", ...) + [Channel("rear beam", (-480, 230, 30), (480, 230, 30))]
    motor = Port("X motor", (-541, 0, 535), (-1, 0, 0))                                  # the connector, cable leaves -X
    box = Port("controller", (0, 240, 60), (0, 1, 0))
    r = route("X motor cable", motor, box, chans, d=6, bend_r=30,
              flex={frozenset({"Y carriage left", "Y rail left"}): 420})                # a loop where the Y stage moves

A channel is a straight run on a part (rest-pose world mm). The router builds a
graph: channel ends, the places channels pass within `jump` of each other
(a corner, a rail meeting a beam, a carriage over its rail), each port's
lead point tied to the nearest channels, and finds the cheapest path
(Dijkstra: length, ×1 in a slot, a cost for every jump through the air and
every corner). Where the path hops between two parts listed in `flex` —
parts that move relative to each other — that hop is a LOOP of fixed length
(given, else 1.5× the rest distance): a hanging catenary the viewer re-solves
every frame as the parts move, while the slot runs ride their parts rigidly.

Route.solid() sweeps the rest-pose centreline in build123d (slot runs as a
polyline filleted at bend_r, loops as the catenary) for the exported model;
Route.descriptor() is what show(cables=[...]) sends the viewer.
"""
from __future__ import annotations

import heapq
import math

GRAVITY_DOWN = (0.0, 0.0, -1.0)


def _v(p):
    return tuple(float(x) for x in p)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _len(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _len(a) or 1.0
    return _mul(a, 1 / n)


def _lerp(a, b, t):
    return _add(a, _mul(_sub(b, a), t))


class Channel:
    """A straight run a cable may follow, on `part`: from a to b (rest-pose world mm).
    kind: 'slot' (cost 1 per mm), 'open' (a bare surface, cost 2), 'chain' (a drag chain, cost 1)."""
    COST = {"slot": 1.0, "open": 2.0, "chain": 1.0, "clip": 1.0}

    def __init__(self, part, a, b, kind="slot"):
        self.part, self.a, self.b, self.kind = str(part), _v(a), _v(b), kind
        self.length = _len(_sub(self.b, self.a))
        if self.length < 1e-6:
            raise ValueError(f"channel on {part!r} has no length")

    def at(self, t):
        return _lerp(self.a, self.b, t)

    def __repr__(self):
        return f"Channel({self.part!r}, {self.a}, {self.b}, {self.kind!r})"


class Port:
    """Where a cable plugs in: a point on `part` and the direction the cable leaves it."""

    def __init__(self, part, at, direction):
        self.part, self.at, self.dir = str(part), _v(at), _unit(_v(direction))


class Chain:
    """A drag chain (cable carrier): a fixed end on `part` and a moving end on `moving_part`, both
    rest-pose world mm, runs parallel to `axis` (the direction the bend lies in), bend radius `r`
    (the two runs sit 2r apart), total length `length` — long enough that the bend stays beyond
    the moving end at full travel: length >= pi*r + 2r + max travel. Pure geometry: the bend sits
    halfway along the carriage's travel, as on a real chain."""

    def __init__(self, part, fixed_end, moving_part, moving_end, axis, r=30.0, length=None):
        self.part, self.fixed, self.moving_part, self.moving = str(part), _v(fixed_end), str(moving_part), _v(moving_end)
        self.axis, self.r = _unit(_v(axis)), float(r)
        rest = abs(_dot(_sub(self.moving, self.fixed), self.axis))
        self.length = float(length if length is not None else math.pi * self.r + 2 * self.r + 2 * rest + 100)

    def params(self):
        return {"axis": list(self.axis), "r": self.r, "length": self.length}


def chain_points(fixed, moving, axis, r, length, n=14):
    """The chain's centreline from its fixed end to its moving end: fixed run, 180-degree bend,
    moving run. Same rule in the viewer. The bend's axial position x_b = (L - pi*r + x_f + x_m) / 2."""
    a = _unit(_v(axis))
    xf, xm = _dot(fixed, a), _dot(moving, a)
    xb = (length - math.pi * r + xf + xm) / 2
    xb = max(xb, max(xf, xm) + r * 0.05)
    perp = _sub(_sub(moving, fixed), _mul(a, xm - xf))          # the offset between the runs
    span = _len(perp)
    nrm = _unit(perp) if span > 1e-6 else (0.0, 0.0, 1.0)
    f_end = _add(fixed, _mul(a, xb - xf))
    m_end = _add(moving, _mul(a, xb - xm))
    centre = _lerp(f_end, m_end, 0.5)
    rad = span / 2
    pts = [fixed, f_end]
    for i in range(1, n):
        th = math.pi * i / n                                   # from the fixed run (-nrm) over the bend (+axis) to the moving run
        pts.append(_add(_add(centre, _mul(nrm, -rad * math.cos(th))), _mul(a, rad * math.sin(th))))
    pts += [m_end, moving]
    return pts


def slots(part, center, size, axis="x", lift=4.0, kind="slot"):
    """The four slot lines of a box-shaped extrusion: one along the middle of each long face,
    `lift` mm outside the face (where a cable's centre sits). axis = the extrusion's length."""
    k = "xyz".index(axis)
    c, s = _v(center), _v(size)
    out = []
    for j in range(3):
        if j == k:
            continue
        for sign in (-1, 1):
            off = [0.0, 0.0, 0.0]
            off[j] = sign * (s[j] / 2 + lift)
            a, b = list(_add(c, tuple(off))), list(_add(c, tuple(off)))
            a[k] -= s[k] / 2
            b[k] += s[k] / 2
            out.append(Channel(part, a, b, kind))
    return out


def _closest(c1, c2):
    """(t1, t2, distance) of the closest points of two segments."""
    p1, d1 = c1.a, _sub(c1.b, c1.a)
    p2, d2 = c2.a, _sub(c2.b, c2.a)
    r = _sub(p1, p2)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    c, b = _dot(d1, r), _dot(d1, d2)
    denom = a * e - b * b
    s = max(0.0, min(1.0, (b * f - c * e) / denom)) if denom > 1e-9 else 0.0
    t = (b * s + f) / e
    if t < 0:
        t = 0.0
        s = max(0.0, min(1.0, -c / a))
    elif t > 1:
        t = 1.0
        s = max(0.0, min(1.0, (b - c) / a))
    return s, t, _len(_sub(c1.at(s), c2.at(t)))


def _project(c, p):
    d = _sub(c.b, c.a)
    t = max(0.0, min(1.0, _dot(_sub(p, c.a), d) / _dot(d, d)))
    return t, _len(_sub(c.at(t), p))


def catenary(p, q, length, n=24, r=30.0):
    """Points along a cable of `length` hanging from p to q (gravity -Z): the catenary through
    both ends with that arc length, or the straight line when it is taut; ends on one vertical
    hang as a U of radius `r` (the bend radius). Same rule in the viewer."""
    p, q = _v(p), _v(q)
    flat = (q[0] - p[0], q[1] - p[1], 0.0)
    dx, dz = _len(flat), q[2] - p[2]
    straight = math.sqrt(dx * dx + dz * dz)
    if length <= straight * 1.001 or straight < 1e-9:
        return [p, q]
    u = _unit(flat) if dx > 1e-6 else (1.0, 0.0, 0.0)
    if dx < 2 * r:                                   # (nearly) one above the other: a U, 2r wide, hanging to the length
        zl = min((p[2] + q[2] + (math.pi + 2) * r - length) / 2, min(p[2], q[2]) - r)
        c = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        pts = [p, (c[0] - r, c[1], p[2] - r), (c[0] - r, c[1], zl + r)]
        for i in range(1, 6):
            th = math.pi + math.pi * i / 6
            pts.append((c[0] + r * math.cos(th), c[1], zl + r + r * math.sin(th)))
        pts += [(c[0] + r, c[1], zl + r), (c[0] + r, c[1], q[2] - r), q]
        return pts
    target = math.sqrt(length * length - dz * dz)   # = 2a sinh(dx/2a)
    lo, hi = dx * 1e-4, dx * 1e4
    for _ in range(80):
        a = (lo + hi) / 2
        if 2 * a * math.sinh(dx / (2 * a)) > target:
            lo = a
        else:
            hi = a
    a = (lo + hi) / 2
    x0 = dx / 2 - a * math.asinh(dz / (2 * a * math.sinh(dx / (2 * a))))
    c = -a * math.cosh(-x0 / a)
    pts = []
    for i in range(n + 1):
        x = dx * i / n
        y = a * math.cosh((x - x0) / a) + c
        pts.append(_add(_add(p, _mul(u, x)), (0.0, 0.0, y)))
    return pts


class Route:
    """A routed cable: waypoints on parts, which spans are loops, the geometry rules."""

    def __init__(self, name, waypoints, flex, *, d, bend_r, color=(0.12, 0.12, 0.14), plug=None, chains=None):
        self.name, self.waypoints, self.flex = str(name), waypoints, flex     # [(part, point)], {index: loop length}
        self.chains = chains or {}                                             # {index: Chain params}
        self.d, self.bend_r, self.color, self.plug = float(d), float(bend_r), tuple(color), plug

    def descriptor(self):
        return {"name": self.name, "d": self.d, "bend_r": self.bend_r, "color": list(self.color), "plug": self.plug,
                "waypoints": [{"part": p, "at": list(pt)} for p, pt in self.waypoints],
                "flex": [{"i": i, "loop": L} for i, L in sorted(self.flex.items())],
                "chains": [dict(i=i, **c) for i, c in sorted(self.chains.items())]}

    def span_points(self, i, samples=24):
        """The rest-pose points of span i -> i+1: a loop's catenary, a chain's runs and bend, else the two ends."""
        a, b = self.waypoints[i][1], self.waypoints[i + 1][1]
        if i in self.chains:
            c = self.chains[i]
            return chain_points(a, b, c["axis"], c["r"], c["length"])
        if i in self.flex:
            return catenary(a, b, self.flex[i], samples, r=self.bend_r)
        return [a, b]

    def span_edges(self, i):
        """build123d edges for a loop or chain span: lines and true arcs where the geometry is lines and
        arcs (a chain's runs and bend, a U loop's legs and bottom), a spline only for a real catenary —
        sweeps of lines and arcs never fail, sweeps of free splines sometimes do."""
        from build123d import Line, Spline, ThreePointArc
        a, b = self.waypoints[i][1], self.waypoints[i + 1][1]
        if i in self.chains:
            c = self.chains[i]
            fixed, moving = (b, a) if c.get("reverse") else (a, b)
            ax = _unit(_v(c["axis"]))
            r, L = c["r"], c["length"]
            xf, xm = _dot(fixed, ax), _dot(moving, ax)
            xb = max((L - math.pi * r + xf + xm) / 2, max(xf, xm) + r * 0.05)
            f_end, m_end = _add(fixed, _mul(ax, xb - xf)), _add(moving, _mul(ax, xb - xm))
            centre = _lerp(f_end, m_end, 0.5)
            apex = _add(centre, _mul(ax, _len(_sub(m_end, f_end)) / 2))
            edges = [Line(fixed, f_end), ThreePointArc(f_end, apex, m_end), Line(m_end, moving)]
            return edges[::-1] if c.get("reverse") else edges
        L, r = self.flex[i], self.bend_r
        p, q = a, b
        flat = (q[0] - p[0], q[1] - p[1], 0.0)
        dx, dz = _len(flat), q[2] - p[2]
        straight = math.sqrt(dx * dx + dz * dz)
        if L <= straight * 1.001 or straight < 1e-9:
            return [Line(p, q)]
        if dx < 2 * r:                                           # the U: legs and a semicircle at the bottom
            zl = min((p[2] + q[2] + (math.pi + 2) * r - L) / 2, min(p[2], q[2]) - r)
            cx, cy = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
            p1, b1 = (cx - r, cy, p[2] - r), (cx - r, cy, zl + r)
            b2, q1 = (cx + r, cy, zl + r), (cx + r, cy, q[2] - r)
            edges = [Line(p, p1)] if _len(_sub(p1, p)) > 1e-6 else []
            if _len(_sub(b1, p1)) > 1e-6:
                edges.append(Line(p1, b1))
            edges.append(ThreePointArc(b1, (cx, cy, zl), b2))
            if _len(_sub(q1, b2)) > 1e-6:
                edges.append(Line(b2, q1))
            if _len(_sub(q, q1)) > 1e-6:
                edges.append(Line(q1, q))
            return edges
        pts = catenary(p, q, L, 24, r=r)
        return [Spline(*pts)]

    def centreline(self, samples=24):
        """Rest-pose points: slot runs as their waypoints, loops as sampled catenaries, chains as their geometry."""
        pts = [self.waypoints[0][1]]
        for i in range(len(self.waypoints) - 1):
            pts += self.span_points(i, samples)[1:]
        return pts

    def length(self):
        pts = self.centreline()
        return sum(_len(_sub(b, a)) for a, b in zip(pts, pts[1:]))

    def path(self):
        """The rest-pose centreline as a build123d Wire: straight runs with every corner rounded at bend_r
        (less where a leg is too short), loops and chains as splines."""
        from build123d import Line, Spline, ThreePointArc, Wire
        edges = []
        run = [self.waypoints[0][1]]

        def flush():
            pts = [p for i, p in enumerate(run) if i == 0 or _len(_sub(p, run[i - 1])) > 1e-6]
            if len(pts) < 2:
                return
            cursor = pts[0]
            for k in range(1, len(pts)):
                if k == len(pts) - 1:
                    if _len(_sub(pts[k], cursor)) > 1e-6:
                        edges.append(Line(cursor, pts[k]))
                    break
                corner, prev, nxt = pts[k], cursor, pts[k + 1]
                u1, u2 = _unit(_sub(prev, corner)), _unit(_sub(nxt, corner))
                cos_t = max(-1.0, min(1.0, _dot(u1, u2)))
                theta = math.acos(cos_t)                                 # the angle between the legs
                if theta > math.pi - 1e-3 or theta < 1e-3:               # straight on, or a hairpin: no fillet
                    edges.append(Line(cursor, corner))
                    cursor = corner
                    continue
                cut = min(self.bend_r / math.tan(theta / 2), 0.45 * _len(_sub(prev, corner)), 0.45 * _len(_sub(nxt, corner)))
                r = cut * math.tan(theta / 2)
                p1, p2 = _add(corner, _mul(u1, cut)), _add(corner, _mul(u2, cut))
                b = _unit(_add(u1, u2))
                centre = _add(corner, _mul(b, r / math.sin(theta / 2)))
                mid = _sub(centre, _mul(b, r))
                if _len(_sub(p1, cursor)) > 1e-6:
                    edges.append(Line(cursor, p1))
                edges.append(ThreePointArc(p1, mid, p2))
                cursor = p2

        for i in range(1, len(self.waypoints)):
            b = self.waypoints[i][1]
            if (i - 1) in self.flex or (i - 1) in self.chains:
                flush()
                edges.extend(self.span_edges(i - 1))
                run[:] = [b]
            else:
                run.append(b)
        flush()
        return Wire(edges) if len(edges) > 1 else Wire([edges[0]])

    def solid(self):
        # one sweep per edge (a line, an arc, a loop's or chain's spline) joined as a Compound: OCC's
        # single sweep along a long mixed wire is fragile (it has crashed on a hanging loop); the
        # pieces meet end to end, and the viewer, STL and STEP treat the compound as one part
        from build123d import Circle, Compound, Plane, Vector, sweep
        pieces = []
        for e in self.path().edges():
            section = Plane(origin=e.position_at(0), z_dir=Vector(e.tangent_at(0))) * Circle(self.d / 2)
            pieces.append(sweep(section, path=e))
        body = pieces[0] if len(pieces) == 1 else Compound(pieces)       # one shape, not an assembly of pieces
        body.label, body.color = self.name, self.color
        return body


def _min_half_leg(run):
    legs = [_len(_sub(b, a)) for a, b in zip(run, run[1:])]
    return min(legs) / 2 if legs else 1.0


def route(name, start, end, channels, *, d=6.0, bend_r=None, stages=None, flex=None, chains=(), jump=60.0, reach=250.0,
          color=(0.12, 0.12, 0.14), plug=None, offset=(0.0, 0.0, 0.0), jump_cost=3.0, corner_cost=40.0, flex_cost=150.0):
    """Route a cable from Port `start` to Port `end` through `channels` (and `chains`).

    stages = {part: stage} says which parts move together (anything unlisted is the fixed "frame");
    a cable may only cross from one stage to another through a Chain or a loop — flex =
    {frozenset({stageA, stageB}): loop length or None} (None = 1.5× the rest distance) — so the
    router can never run a cable straight across a moving joint. Part pairs work in flex too."""
    bend_r = float(bend_r if bend_r is not None else 5 * d)
    stages = {str(k): str(v) for k, v in (stages or {}).items()}
    stage_of = lambda part: stages.get(part, "frame")
    flex = {frozenset(k): v for k, v in (flex or {}).items()}

    def loop_for(part_a, part_b):
        """The loop length (or None) that lets a cable cross between these two parts; False = no crossing."""
        if stage_of(part_a) == stage_of(part_b):
            return False if frozenset({part_a, part_b}) not in flex else flex[frozenset({part_a, part_b})] or 0.0
        for key in (frozenset({part_a, part_b}), frozenset({stage_of(part_a), stage_of(part_b)})):
            if key in flex:
                return flex[key] or 0.0
        return False

    chains = list(chains)
    nodes = []                  # (part, point)
    on = {}                     # channel index -> [(t, node)]
    adj = {}                    # node -> [(node, cost, kind)]

    def node(part, pt):
        nodes.append((str(part), _v(pt)))
        return len(nodes) - 1

    def link(u, v, cost, kind="run"):
        adj.setdefault(u, []).append((v, cost, kind))
        adj.setdefault(v, []).append((u, cost, kind))

    def on_channel(i, t):
        n = node(channels[i].part, channels[i].at(t))
        on.setdefault(i, []).append((t, n))
        return n

    for i, c in enumerate(channels):
        on_channel(i, 0.0)
        on_channel(i, 1.0)
    for i in range(len(channels)):
        for j in range(i + 1, len(channels)):
            s, t, dist = _closest(channels[i], channels[j])
            if dist > jump:
                continue
            pa, pb = channels[i].part, channels[j].part
            crossing = pa != pb and stage_of(pa) != stage_of(pb)
            loop = loop_for(pa, pb) if pa != pb else False
            if loop is not False and (crossing or frozenset({pa, pb}) in flex):
                u, v = on_channel(i, s), on_channel(j, t)
                link(u, v, dist + flex_cost, "flex")
            elif not crossing:
                u, v = on_channel(i, s), on_channel(j, t)
                link(u, v, dist * jump_cost + corner_cost, "jump")
    chain_nodes = []            # (fixed node, moving node, Chain)
    for ch in chains:
        u, v = node(ch.part, ch.fixed), node(ch.moving_part, ch.moving)
        link(u, v, ch.length, "chain")
        chain_nodes.append((u, v, ch))
        # a chain end is a place a cable can get to from a channel passing within reach of it
        for i, c in enumerate(channels):
            for n in (u, v):
                if stage_of(c.part) != stage_of(nodes[n][0]):
                    continue
                t, dist = _project(c, nodes[n][1])
                if dist <= jump * 1.5:
                    link(n, on_channel(i, t), dist * jump_cost + corner_cost, "jump")
    ports = {}
    for which, p in (("start", start), ("end", end)):
        lead = _add(p.at, _mul(p.dir, bend_r))
        n = node(p.part, lead)
        ports[which] = n
        near = sorted(((_project(c, lead), i) for i, c in enumerate(channels) if stage_of(c.part) == stage_of(p.part)),
                      key=lambda x: x[0][1])[:4]
        for (t, dist), i in near:
            if dist <= reach:
                link(n, on_channel(i, t), dist * jump_cost + corner_cost, "jump")
        for u, v, ch in chain_nodes:
            for m in (u, v):
                if stage_of(nodes[m][0]) != stage_of(p.part):
                    continue
                dist = _len(_sub(nodes[m][1], lead))
                if dist <= reach:
                    link(n, m, dist * jump_cost + corner_cost, "jump")
    for i, lst in on.items():
        lst.sort()
        cost = Channel.COST.get(channels[i].kind, 1.0)
        for (t0, u), (t1, v) in zip(lst, lst[1:]):
            if u != v:
                link(u, v, (t1 - t0) * channels[i].length * cost, "run")

    # Dijkstra start -> end
    src, dst = ports["start"], ports["end"]
    dist = {src: 0.0}
    prev = {}
    heap = [(0.0, src)]
    while heap:
        dcur, u = heapq.heappop(heap)
        if u == dst:
            break
        if dcur > dist.get(u, float("inf")):
            continue
        for v, w, kind in adj.get(u, []):
            nd = dcur + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = (u, kind)
                heapq.heappush(heap, (nd, v))
    if dst not in dist:
        raise ValueError(f"no route for {name!r}: the ports reach no connected channels (reach={reach}, jump={jump}); "
                         "a crossing between stages needs a Chain or a flex loop")
    chain = [dst]
    kinds = []
    while chain[-1] != src:
        u, kind = prev[chain[-1]]
        chain.append(u)
        kinds.append(kind)
    chain.reverse()
    kinds.reverse()
    waypoints = [(start.part, start.at)] + [nodes[n] for n in chain] + [(end.part, end.at)]
    span_kinds = ["lead"] + kinds + ["lead"]
    # drop repeated / collinear points inside one part's run, keeping the loop spans' ends
    out, out_kinds = [waypoints[0]], []
    for i in range(1, len(waypoints)):
        k = span_kinds[i - 1]
        p = waypoints[i]
        if _len(_sub(p[1], out[-1][1])) < 1e-6 and k not in ("flex", "chain"):
            continue
        if (len(out) >= 2 and k == "run" and out_kinds[-1] == "run" and out[-1][0] == p[0]
                and _len(_sub(_unit(_sub(out[-1][1], out[-2][1])), _unit(_sub(p[1], out[-1][1])))) < 1e-6):
            out[-1] = p                        # extend the straight run
            continue
        out.append(p)
        out_kinds.append(k)
    # offset: cables sharing a slot sit side by side instead of on top of each other — every
    # waypoint but the two plugs is shifted by it (the chain ends included, so the chain shifts too)
    off = _v(offset)
    if any(off):
        out = [(p, pt if i in (0, len(out) - 1) else _add(pt, off)) for i, (p, pt) in enumerate(out)]
    loops, chain_spans = {}, {}
    for i, k in enumerate(out_kinds):
        if k == "flex":
            a, b = out[i][1], out[i + 1][1]
            L = loop_for(out[i][0], out[i + 1][0])
            loops[i] = float(L) if L else 1.5 * _len(_sub(b, a))
        elif k == "chain":
            ch = next(c for c in chains if {c.part, c.moving_part} == {out[i][0], out[i + 1][0]})
            if out[i][0] != ch.part:                       # the path runs the chain moving end first: flip it
                params = ch.params()
                params["axis"] = params["axis"]            # geometry is symmetric in the two ends
                chain_spans[i] = dict(params, reverse=True)
            else:
                chain_spans[i] = dict(ch.params(), reverse=False)
    return Route(name, out, loops, d=d, bend_r=bend_r, color=color, plug=plug, chains=chain_spans)


__all__ = ["Channel", "Port", "Chain", "slots", "route", "Route", "catenary", "chain_points"]
