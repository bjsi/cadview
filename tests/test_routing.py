"""openworkshop.routing: slots of an extrusion, the channel router (stages, loops, chains),
catenary and chain geometry, the descriptor the viewer gets. The build123d sweep needs build123d."""
import math
import unittest

from openworkshop.routing import Chain, Channel, Port, catenary, chain_points, route, slots

try:
    import build123d  # noqa: F401
except ImportError:          # pragma: no cover
    build123d = None


def rig():
    """A rail along X on a carriage that moves in Y, over a fixed beam along Y; a motor on the rail, a box on the beam."""
    chans = slots("rail", (0, 0, 100), (1000, 20, 40), "x") + slots("beam", (-490, 0, 20), (40, 500, 20), "y")
    motor = Port("motor", (-540, 0, 100), (-1, 0, 0))
    box = Port("box", (-490, 300, 60), (0, 1, 0))
    return chans, motor, box


class RoutingTest(unittest.TestCase):
    def test_slots_are_the_four_faces(self):
        s = slots("rail", (0, 0, 100), (1000, 20, 40), "x", lift=4)
        self.assertEqual(len(s), 4)
        self.assertEqual({c.a[1:] for c in s}, {(-14.0, 100.0), (14.0, 100.0), (0.0, 76.0), (0.0, 124.0)})
        self.assertTrue(all(c.a[0] == -500 and c.b[0] == 500 for c in s))
        with self.assertRaises(ValueError):
            Channel("x", (0, 0, 0), (0, 0, 0))

    def test_route_runs_in_slots_and_loops_at_the_moving_joint(self):
        chans, motor, box = rig()
        r = route("m", motor, box, chans, d=6, bend_r=30, stages={"rail": "carriage", "motor": "carriage"},
                  flex={frozenset({"carriage", "frame"}): 300}, reach=120)
        parts = [p for p, _ in r.waypoints]
        self.assertEqual(parts[:2], ["motor", "motor"])                       # the port and its lead
        self.assertIn("rail", parts)
        self.assertIn("beam", parts)
        self.assertEqual(parts[-2:], ["box", "box"])
        self.assertEqual(len(r.flex), 1)                                        # exactly one loop, where rail meets beam
        i = next(iter(r.flex))
        self.assertEqual((r.waypoints[i][0], r.waypoints[i + 1][0]), ("rail", "beam"))
        self.assertEqual(r.flex[i], 300)
        d = r.descriptor()
        self.assertEqual(d["flex"], [{"i": i, "loop": 300.0}])
        self.assertEqual(len(d["waypoints"]), len(r.waypoints))
        self.assertGreater(r.length(), 650)

    def test_no_crossing_without_a_loop_or_chain(self):
        chans, motor, box = rig()
        with self.assertRaises(ValueError):
            route("m", motor, box, chans, stages={"rail": "carriage", "motor": "carriage"}, reach=120)

    def test_chain_is_taken_and_its_geometry_holds_length(self):
        chans, motor, box = rig()
        chain = Chain("beam", (-490, -200, 40), "rail", (-490, 0, 80), axis=(0, 1, 0), r=20, length=700)
        r = route("m", motor, box, chans, stages={"rail": "carriage", "motor": "carriage"}, chains=[chain], reach=120)
        self.assertEqual(len(r.chains), 1)
        self.assertEqual(len(r.flex), 0)
        pts = chain_points((-490, -200, 40), (-490, 0, 80), (0, 1, 0), 20, 700)
        L = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        self.assertAlmostEqual(L, 700, delta=700 * 0.02)                       # runs + bend add up to the chain
        self.assertEqual(pts[0], (-490.0, -200.0, 40.0))
        self.assertEqual(pts[-1], (-490.0, 0.0, 80.0))
        yb = max(p[1] for p in pts)
        self.assertAlmostEqual(yb, (700 - math.pi * 20 - 200 + 0) / 2 + 20, delta=1)   # bend beyond both ends

    def test_catenary(self):
        pts = catenary((0, 0, 0), (100, 0, 0), 150, 8)
        self.assertEqual(len(pts), 9)
        L = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        self.assertAlmostEqual(L, 150, delta=3)
        self.assertLess(min(p[2] for p in pts), -40)
        self.assertEqual(catenary((0, 0, 0), (100, 0, 0), 100), [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)])   # taut
        pts = catenary((0, 0, 50), (100, 0, 0), 130, 10)                       # ends at different heights
        self.assertAlmostEqual(pts[-1][2], 0, places=6)
        self.assertAlmostEqual(pts[0][2], 50, places=6)


@unittest.skipIf(build123d is None, "build123d not installed")
class SolidTest(unittest.TestCase):
    def test_sweep(self):
        chans, motor, box = rig()
        r = route("m", motor, box, chans, d=6, bend_r=30, stages={"rail": "carriage", "motor": "carriage"},
                  flex={frozenset({"carriage", "frame"}): 300}, reach=120)
        s = r.solid()
        self.assertEqual(s.label, "m")
        self.assertAlmostEqual(s.volume / (math.pi * 9), r.length(), delta=r.length() * 0.2)


if __name__ == "__main__":
    unittest.main()
