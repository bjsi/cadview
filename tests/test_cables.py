"""openworkshop.cables: the route rule (end leads, sag), the descriptor show() sends, and the
build123d sweep (that part needs build123d; skipped without)."""
import math
import unittest

from openworkshop.cables import Cable, route_points, sag_depth

try:
    import build123d  # noqa: F401
except ImportError:          # pragma: no cover
    build123d = None


class RouteTest(unittest.TestCase):
    def test_end_leads_and_no_sag_without_slack(self):
        pts = route_points([((0, 0, 0), (0, 0, 1)), ((100, 0, 0), (0, 0, 1))], bend_r=10, slack=1.0)
        self.assertEqual(pts, [(0, 0, 0), (0, 0, 10), (100, 0, 10), (100, 0, 0)])

    def test_slack_hangs_the_free_span(self):
        pts = route_points([((0, 0, 0), (0, 0, 1)), ((400, 0, 0), (0, 0, 1))], bend_r=10, slack=1.05)
        self.assertEqual(len(pts), 5)                                   # a mid point in the long span only
        mid = pts[2]
        self.assertEqual((mid[0], mid[1]), (200, 0))
        self.assertAlmostEqual(mid[2], 10 - sag_depth(400, 1.05), places=6)
        self.assertLess(mid[2], 0)                                      # hangs below the ends
        self.assertAlmostEqual(sag_depth(400, 1.05), math.sqrt(20 * 620), places=6)
        self.assertEqual(sag_depth(400, 1.0), 0)

    def test_via_points_and_descriptor(self):
        c = Cable("c", d=6, bend_r=20, slack=1.0, color=(0, 0, 0), plug="wire up",
                  ends=[("a", (0, 0, 0), (0, 0, 1)), ("b", (0, 300, 0), (0, 0, 1))], via=[("clip", (0, 150, 40))])
        d = c.descriptor()
        self.assertEqual([a["kind"] for a in d["anchors"]], ["end", "via", "end"])
        self.assertEqual(d["anchors"][1], {"part": "clip", "at": [0.0, 150.0, 40.0], "dir": None, "kind": "via"})
        self.assertEqual(d["anchors"][0]["dir"], [0.0, 0.0, 1.0])
        self.assertEqual((d["name"], d["d"], d["bend_r"], d["plug"]), ("c", 6.0, 20.0, "wire up"))
        self.assertEqual(c.points(), [(0, 0, 0), (0, 0, 20), (0, 150, 40), (0, 300, 20), (0, 300, 0)])
        with self.assertRaises(ValueError):
            Cable("x", ends=[("a", (0, 0, 0))])

    def test_default_bend_radius(self):
        c = Cable("c", d=4, ends=[("a", (0, 0, 0)), ("b", (50, 0, 0))])
        self.assertEqual(c.bend_r, 20)


@unittest.skipIf(build123d is None, "build123d not installed")
class SolidTest(unittest.TestCase):
    def test_sweep_is_a_labelled_tube_of_about_the_right_length(self):
        c = Cable("loom", d=6, bend_r=20, slack=1.0, ends=[("a", (0, 0, 0), (0, 0, 1)), ("b", (200, 0, 0), (0, 0, 1))])
        s = c.solid()
        self.assertEqual(s.label, "loom")
        L = c.length()
        self.assertGreater(L, 200)                                       # it leads up and comes back down
        self.assertLess(L, 300)
        self.assertAlmostEqual(s.volume / (math.pi * 9), L, delta=L * 0.15)   # area x length, within what the bends cost
        bb = s.bounding_box()
        self.assertAlmostEqual(bb.min.X, -3, delta=1.0)                  # the spline overshoots its lead a touch
        self.assertAlmostEqual(bb.max.X, 203, delta=1.0)


if __name__ == "__main__":
    unittest.main()
