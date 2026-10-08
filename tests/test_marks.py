"""openworkshop.marks: engrave() cuts text into the top face (volume drops, bbox stays),
raised=True adds it, arrow() points the way it is told (needs build123d; skipped without)."""
import unittest

try:
    import build123d  # noqa: F401
except ImportError:          # pragma: no cover
    build123d = None


@unittest.skipIf(build123d is None, "build123d not installed")
class MarksTest(unittest.TestCase):
    def setUp(self):
        from build123d import Box
        self.box = Box(40, 20, 5)
        self.box.label, self.box.color = "plate", (1, 0, 0)

    def test_engrave_cuts_the_top_and_keeps_the_label(self):
        from openworkshop.marks import engrave, top_face
        top = top_face(self.box)
        self.assertAlmostEqual(top.center().Z, 2.5, places=4)
        out = engrave(self.box, "P1", depth=0.4)
        self.assertLess(out.volume, self.box.volume)
        self.assertGreater(out.volume, self.box.volume - 40 * 20 * 0.4)        # a cut, not a slab
        bb = out.bounding_box()
        self.assertAlmostEqual(bb.max.Z, 2.5, places=4)                        # nothing sticks out
        self.assertEqual(out.label, "plate")

    def test_raised_adds_and_other_faces_work(self):
        from openworkshop.marks import engrave
        up = engrave(self.box, "P1", raised=True, depth=0.6)
        self.assertGreater(up.volume, self.box.volume)
        self.assertAlmostEqual(up.bounding_box().max.Z, 3.1, places=4)
        side = engrave(self.box, "A", normal=(0, -1, 0), depth=0.3)             # the -Y face
        self.assertLess(side.volume, self.box.volume)
        self.assertAlmostEqual(side.bounding_box().min.Y, -10, places=4)

    def test_arrow_points_along_the_direction(self):
        from openworkshop.marks import arrow
        out = arrow(self.box, (1, 0, 0), size=6, depth=0.4, at=(10, 0))
        # the triangle's tip is +3 past its centre along +X: the removed material lies in x 7..13
        cut = self.box - out
        bb = cut.bounding_box()
        self.assertAlmostEqual(bb.min.X, 7, places=3)
        self.assertAlmostEqual(bb.max.X, 13, places=3)
        self.assertAlmostEqual(bb.max.Z, 2.5, places=3)
        self.assertAlmostEqual(bb.min.Z, 2.1, places=3)
        labelled = arrow(self.box, (0, 1, 0), text="WALL")
        self.assertLess(labelled.volume, out.volume)                            # the word removed more


if __name__ == "__main__":
    unittest.main()
