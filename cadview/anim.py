"""Timeline — compiles phase-style motion into cadview animation tracks.

Raw tracks ((selector, action, times, values)) stay the base format; this
just removes the parallel-array bookkeeping when building or retiming:

    tl = Timeline()
    tl.move("drawer (slides)", "tx", 85, start=0.6, dur=1.4)   # out
    tl.move("drawer (slides)", "tx", 0, start=3.4, dur=1.2)    # back
    tl.show("lamp (lit)", start=1.0, until=2.1)
    tl.spin("turntable", "rz", 360, start=0, dur=6.0)
    show(model, animation=[{"name": "cycle", "tracks": tl.tracks()}])

Between segments a value HOLDS at its last target; overlapping segments on
the same (selector, action) raise. Values are relative to the node's base
transform, like every track.
"""

_ACTIONS = {"t", "tx", "ty", "tz", "rx", "ry", "rz", "vis"}
_EPS = 1e-3


class Timeline:
    def __init__(self):
        self._segs = {}      # (selector, action) -> [(start, end, target)]

    def _add(self, selector, action, start, end, target):
        if action not in _ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        if end < start:
            raise ValueError("segment ends before it starts")
        segs = self._segs.setdefault((str(selector), action), [])
        for s, e, _ in segs:
            if start < e - _EPS and s < end - _EPS:
                raise ValueError(
                    f"overlapping segments for {selector}/{action} at t={start}")
        segs.append((float(start), float(end), float(target)))
        return self

    def move(self, selector, action, to, *, start, dur):
        """Ramp to `to` (mm or degrees) over start..start+dur, then hold."""
        return self._add(selector, action, start, start + dur, to)

    def spin(self, selector, action, degrees, *, start, dur):
        """Alias of move for rotations — reads better at call sites."""
        return self.move(selector, action, degrees, start=start, dur=dur)

    def show(self, selector, *, start, until):
        """Visible for start..until (vis tracks default the node to hidden
        outside their 1-spans only if you begin with show(..., start=0)."""
        self._add(selector, "vis", start, start, 1.0)
        return self._add(selector, "vis", until, until, 0.0)

    def hide(self, selector, *, start, until):
        self._add(selector, "vis", start, start, 0.0)
        return self._add(selector, "vis", until, until, 1.0)

    def chapter(self, name, start, camera=None):
        """Name the phase that begins at `start` — a tick on the viewer's scrub
        bar, the name next to the time while it plays, click to jump,
        snapshot(chapter=name). `camera` = {"focus": part, "view": "iso",
        "zoom": 1.2, "yaw": 15}: the viewer poses it when the chapter starts."""
        self._chapters = getattr(self, "_chapters", [])
        entry = {"t": float(start), "name": str(name)}
        if camera:
            entry["camera"] = dict(camera)
        self._chapters.append(entry)
        return self

    def chapters(self):
        return sorted(getattr(self, "_chapters", []), key=lambda c: c["t"])

    def clip(self, name, speed=1.0, end=None):
        """One entry for show(animation=[...]): tracks plus the chapters."""
        out = {"name": name, "tracks": self.tracks(end), "speed": speed}
        if self.chapters():
            out["chapters"] = self.chapters()
        return out

    def end_time(self):
        return max((e for segs in self._segs.values() for _, e, _ in segs),
                   default=0.0)

    def tracks(self, end=None):
        """Compile to (selector, action, times, values) tracks."""
        end = float(end) if end is not None else self.end_time()
        out = []
        for (selector, action), segs in self._segs.items():
            segs = sorted(segs)
            times, values = [], []
            if action == "vis":
                current = segs[0][2]
                times, values = [0.0], [1.0 - current] if segs[0][0] > _EPS else [current]
                for s, _, target in segs:
                    prev = values[-1]
                    if s > times[-1] + _EPS:
                        times.append(round(s - _EPS, 4)); values.append(prev)
                    times.append(round(s, 4)); values.append(target)
            else:
                current = 0.0
                times, values = [0.0], [0.0]
                for s, e, target in segs:
                    if s > times[-1] + _EPS:
                        times.append(round(s, 4)); values.append(current)
                    times.append(round(e, 4)); values.append(target)
                    current = target
            if end > times[-1] + _EPS:
                times.append(round(end, 4)); values.append(values[-1])
            out.append([selector, action, times, values])
        return out
