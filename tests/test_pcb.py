"""cadview.pcb without a CAD kernel: the KiCad reader/writer and pad maths."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cadview import pcb

MOD = '''(footprint "Test_1x02" (version 20240108) (generator "pcbnew")
  (layer "F.Cu")
  (property "Reference" "REF**" (at 0 -3 0) (layer "F.SilkS") (uuid "a") (effects (font (size 1 1) (thickness 0.15))))
  (pad "1" thru_hole rect (at 0 0) (size 1.7 1.7) (drill 0.9) (layers "*.Cu" "*.Mask") (uuid "b"))
  (pad "2" thru_hole oval (at 2.54 0 90) (size 1.7 2.2) (drill 0.9) (layers "*.Cu" "*.Mask") (uuid "c"))
  (pad "3" smd roundrect (at 0 -2.5) (size 1 0.5) (layers "F.Cu" "F.Paste" "F.Mask") (uuid "d"))
  (model "${KICAD9_3DMODEL_DIR}/Test.3dshapes/Test_1x02.step" (offset (xyz 0 0 0)))
)
'''


class PcbTests(unittest.TestCase):
    def test_sexp_roundtrips_quoted_strings_symbols_and_numbers(self):
        tree = pcb._sexp('(a "quoted \\"x\\"" sym 1.5 2 (b -0.25))')
        self.assertEqual(tree[0], "a")
        self.assertIsInstance(tree[1], pcb.Q)
        self.assertEqual(tree[1], 'quoted "x"')
        self.assertEqual(tree[3:5], [1.5, 2.0])
        self.assertEqual(pcb._ser(tree), '(a "quoted \\"x\\"" sym 1.5 2\n  (b -0.25))')   # one node per line, like KiCad
        self.assertEqual(pcb._num(2.0), "2")
        self.assertEqual(pcb._num(0.1234567), "0.123457")

    def test_kicad_footprint_reads_pads_y_up_with_rotation_and_model_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "Test.pretty"
            lib.mkdir()
            (lib / "Test_1x02.kicad_mod").write_text(MOD)
            with patch.object(pcb, "KICAD_FP", tmp), patch.object(pcb, "KICAD_3D", "/models"):
                fp = pcb.kicad_footprint("Test", "Test_1x02")
        self.assertEqual([p.number for p in fp.pads], ["1", "2", "3"])
        p1, p2, p3 = fp.pads
        self.assertEqual((p1.kind, p1.shape, p1.drill, p1.layers), ("thru_hole", "rect", 0.9, ("top", "bottom")))
        self.assertEqual((p2.w, p2.h), (2.2, 1.7))             # the pad's own 90° turns its size
        self.assertEqual((p3.x, p3.y, p3.kind, p3.layers), (0.0, 2.5, "smd", ("top",)))   # y flipped to y-up
        self.assertEqual(fp.model, "/models/Test.3dshapes/Test_1x02.step")
        self.assertEqual(fp.pad(2).number, "2")
        with self.assertRaises(KeyError):
            fp.pad(9)

    def test_kicad_symbol_flattens_a_derived_symbol_onto_its_parent(self):
        lib = '''(kicad_symbol_lib (version 20241209) (generator "x")
  (symbol "R_Base" (pin_numbers (hide yes)) (in_bom yes) (on_board yes)
    (property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "R_Base" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "R_Base_1_1"
      (pin passive line (at 0 3.81 270) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -3.81 90) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "R_Small" (extends "R_Base")
    (property "Value" "R_Small" (at 0 0 0) (effects (font (size 1.27 1.27)))))
)
'''
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Device.kicad_sym").write_text(lib)
            with patch.object(pcb, "KICAD_SYM", tmp), patch.dict(pcb._SYM_LIBS, {}, clear=True):
                sym = pcb.kicad_symbol("Device", "R_Small")
        self.assertEqual((sym.lib, sym.name), ("Device", "R_Small"))
        self.assertEqual(sym.tree[1], "Device:R_Small")                  # named for lib_symbols
        self.assertIsNone(pcb._kv(sym.tree, "extends"))                 # flattened: no extends left
        self.assertEqual([n[1] for n in sym.tree if isinstance(n, list) and n[0] == "symbol"], ["R_Small_1_1"])
        self.assertEqual(sorted(p[0] for p in sym.pins), ["1", "2"])

    def test_placed_part_rotates_its_pads_about_its_origin(self):
        fp = pcb.Footprint("f", [pcb.Pad("1", "smd", "rect", 2.0, 0.0, 1, 1)], None)
        self.assertEqual(pcb.Placed("U1", fp, 10.0, 5.0, 0.0).pad_xy(fp.pads[0]), (12.0, 5.0))
        self.assertEqual(pcb.Placed("U1", fp, 10.0, 5.0, 90.0).pad_xy(fp.pads[0]), (10.0, 7.0))
        self.assertEqual(pcb.Placed("U1", fp, 10.0, 5.0, 180.0).pad_xy(fp.pads[0]), (8.0, 5.0))


if __name__ == "__main__":
    unittest.main()
