"""openworkshop.hardware: every part builds to its table size, labels carry the spec,
fasten() points the screw along the axis and parks the mate `grip` further on,
and the guide's counting reads the labels back (needs build123d; skipped without)."""
import math
import unittest

try:
    import build123d  # noqa: F401
except ImportError:          # pragma: no cover
    build123d = None


@unittest.skipIf(build123d is None, "build123d not installed")
class HardwareTest(unittest.TestCase):
    def test_sizes_and_labels(self):
        from openworkshop.hardware import corner_bracket, heat_set_insert, nut, screw, t_nut, washer
        s = screw("M6", 12)
        bb = s.bounding_box()
        self.assertEqual(s.label, "M6×12 socket screw")
        self.assertAlmostEqual(bb.min.Z, -12, places=3)          # shank down -Z from the head's underside
        self.assertAlmostEqual(bb.max.Z, 6, places=3)            # ISO 4762 k for M6
        self.assertAlmostEqual(bb.size.X, 10, places=3)          # d_k
        self.assertEqual(screw("M4", 10, "button").label, "M4×10 button screw")
        self.assertEqual(screw("M5", 16, "countersunk").label, "M5×16 countersunk screw")
        n = nut("M6")
        self.assertAlmostEqual(n.bounding_box().size.Z, 5.2, places=3)
        self.assertAlmostEqual(washer("M6").bounding_box().size.X, 12, places=3)
        t = t_nut("M6", "3030")
        self.assertEqual(t.label, "M6 T-nut (3030)")
        self.assertAlmostEqual(t.bounding_box().max.Z, 0, places=3)   # top face at the origin, body below
        self.assertEqual(heat_set_insert("M3").label, "M3 heat-set insert")
        b = corner_bracket("3030")
        self.assertEqual(b.label, "3030 corner bracket")
        self.assertAlmostEqual(b.bounding_box().size.X, 30, places=3)
        self.assertAlmostEqual(b.bounding_box().size.Z, 30, places=3)
        with self.assertRaises(ValueError):
            screw("M6", 12, "hex")

    def test_fasten_orients_and_parks_the_mate(self):
        from openworkshop.hardware import fasten, screw, t_nut
        f = fasten(screw("M6", 12), t_nut("M6", "3030"), at=(10, 20, 30), axis=(0, -1, 0), grip=3)
        self.assertEqual(f.label, "M6×12 socket screw")
        sc, tn = f.children
        sb, tb = sc.bounding_box(), tn.bounding_box()
        self.assertAlmostEqual(sb.max.Y, 26, places=3)     # head (6 mm) behind the origin plane y=20
        self.assertAlmostEqual(sb.min.Y, 8, places=3)      # shank 12 mm along -Y
        self.assertAlmostEqual(tb.max.Y, 17, places=3)     # mate's top face grip=3 along the axis
        self.assertAlmostEqual(tb.min.Y, 11.5, places=3)
        up = fasten(screw("M6", 12), at=(0, 0, 0), axis=(0, 0, 1))
        self.assertAlmostEqual(up.children[0].bounding_box().max.Z, 12, places=3)

    def test_bom_counts_leaves_by_label(self):
        from build123d import Compound, Pos
        from openworkshop.hardware import bom, corner_bracket, fasten, screw, t_nut
        f = fasten(screw("M6", 12), t_nut("M6", "3030"))
        counts = bom(Compound(children=[f, Pos(50, 0, 0) * f, corner_bracket()]))
        self.assertEqual(counts, {"M6×12 socket screw": 2, "M6 T-nut (3030)": 2, "3030 corner bracket": 1})

    def test_guide_counts_strip_only_duplicate_suffixes(self):
        from openworkshop.guide import counted
        names = {"a": "3030 corner bracket", "b": "3030 corner bracket(2)", "c": "M6 T-nut (3030)", "d": "M6 T-nut (3030)"}
        self.assertEqual(counted(["a", "b", "c", "d"], names), [(2, "3030 corner bracket"), (2, "M6 T-nut (3030)")])


if __name__ == "__main__":
    unittest.main()
