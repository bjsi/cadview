"""openworkshop.guide without a server: steps from a clip's chapters, selector resolution,
counting, routes and the kit (incl. a binary STL from the scene mesh)."""
import base64
import json
import struct
import tempfile
import unittest
from pathlib import Path

from openworkshop import guide


def _buf(values, dtype="float32", code="f"):
    return {"shape": [len(values)], "dtype": dtype, "buffer": base64.b64encode(struct.pack("<%d%s" % (len(values), code), *values)).decode()}


def scene():
    tri = {"vertices": _buf([0, 0, 0, 10, 0, 0, 0, 10, 0]), "triangles": _buf([0, 1, 2], "int32", "i")}
    leaf = lambda i, n: {"id": i, "name": n, "shape": {"ref": 0}}
    return {"type": "data", "meta": {"project": "t"},
            "data": {"instances": [tri], "shapes": {"id": "/kit", "name": "kit", "parts": [
                {"id": "/kit/desk", "name": "desk", "parts": [leaf("/kit/desk/leg", "leg"), leaf("/kit/desk/leg(2)", "leg(2)"),
                                                              leaf("/kit/desk/top", "top")]},
                {"id": "/kit/hw", "name": "hw", "parts": [leaf("/kit/hw/M6×12 socket screw", "M6×12 socket screw"),
                                                          leaf("/kit/hw/M6 T-nut (3030)", "M6 T-nut (3030)")]},
                leaf("/kit/wall", "wall")]}},
            "routes": {"top": ["cnc", "buy"], "leg": "cut"},
            "animations": [{"name": "assembly", "chapters": [{"t": 0, "name": "legs"}, {"t": 2, "name": "top", "camera": {"view": "top"}}, {"t": 4, "name": "hardware"}],
                            "tracks": [["leg", "vis", [0, 0.299, 0.3], [0, 0, 1]], ["leg", "tz", [0, 0, 0.3, 1.1], [0, 400, 400, 0]],
                                       ["leg(2)", "vis", [0, 0.549, 0.55], [0, 0, 1]], ["leg(2)", "tz", [0, 0, 0.55, 1.35], [0, 400, 400, 0]],
                                       ["top", "tz", [0, 0, 2.3, 3.1], [0, 400, 400, 0]],
                                       ["hw", "vis", [0, 4.299, 4.3], [0, 0, 1]]]}]}


class GuideTest(unittest.TestCase):
    def test_steps_and_arrivals(self):
        clip, steps, static, names = guide.steps_of(scene())
        self.assertEqual(clip, "assembly")
        self.assertEqual([s["name"] for s in steps], ["legs", "top", "hardware"])
        self.assertEqual(steps[0]["parts"], ["/kit/desk/leg", "/kit/desk/leg(2)"])        # vis turns on inside the step
        self.assertEqual(steps[1]["parts"], ["/kit/desk/top"])                            # the t=0 park is not a move
        self.assertEqual(steps[2]["parts"], ["/kit/hw/M6×12 socket screw", "/kit/hw/M6 T-nut (3030)"])   # a group's leaves
        self.assertEqual(static, ["/kit/wall"])
        self.assertEqual(steps[1]["camera"], {"view": "top"})

    def test_counting_strips_the_duplicate_suffix_only(self):
        names = {"a": "leg", "b": "leg(2)", "c": "M6 T-nut (3030)"}
        self.assertEqual(guide.counted(["a", "b", "c"], names), [(2, "leg"), (1, "M6 T-nut (3030)")])

    def test_routes_and_kit(self):
        self.assertEqual(guide.route_for("top", {"top": ["cnc", "buy"]}), ["cnc", "buy"])
        self.assertEqual(guide.route_for("gridfinity bin 2x2", {"gridfinity bin *": ["print"]}), ["print"])
        self.assertEqual(guide.route_for("M6×12 socket screw", {}), ["buy"])                 # hardware default
        self.assertEqual(guide.route_for("M6×12 socket screw", {"M6×12 socket screw": ["print"]}), ["print"])
        self.assertIsNone(guide.route_for("mystery", {}))
        msg = scene()
        _, steps, _, names = guide.steps_of(msg)
        routes = dict(msg["routes"])
        rows = guide.kit(steps, names, routes)
        self.assertEqual([(r["route"], r["label"], r["count"], r["also"]) for r in rows],
                         [("cnc", "top", 1, ["buy"]), ("cut", "leg", 2, []), ("buy", "M6×12 socket screw", 1, []), ("buy", "M6 T-nut (3030)", 1, [])])

    def test_kit_writes_stl_from_the_mesh(self):
        msg = scene()
        _, steps, _, names = guide.steps_of(msg)
        with tempfile.TemporaryDirectory() as d:
            rows = guide.write_kit(d, msg, steps, names, msg["routes"])
            kit = json.loads((Path(d) / "kit.json").read_text())
            self.assertEqual(kit["parts"][0]["file"], "cnc/top.stl")
            stl = (Path(d) / "cnc" / "top.stl").read_bytes()
            self.assertEqual(struct.unpack("<I", stl[80:84])[0], 1)                       # one triangle
            self.assertEqual(len(stl), 84 + 50)
            nx, ny, nz = struct.unpack("<3f", stl[84:96])
            self.assertAlmostEqual(nz, 1.0, places=5)                                      # normal from the winding
            self.assertFalse((Path(d) / "buy").exists())                                   # nothing to make for bought parts
            self.assertEqual([r["route"] for r in rows if "file" in r], ["cnc", "cut"])

    def test_build_html_groups_the_kit_by_route(self):
        msg = scene()
        clip, steps, static, names = guide.steps_of(msg)
        images = {s["name"]: "" for s in steps}; images["kit"] = ""
        page = guide.build_html("T", None, clip, steps, static, names, images, {"steps": {"top": {"tools": ["router"]}}}, None, msg["routes"])
        self.assertIn("<tr class=route><td></td><td>cnc</td></tr>", page)
        self.assertIn("2×</td><td>leg</td>", page)
        self.assertIn("<small>or buy</small>", page)
        self.assertIn("Step 2 of 3", page)
        self.assertIn("router", page)


if __name__ == "__main__":
    unittest.main()
