import unittest
from cadview.anim import Timeline


class TimelineTests(unittest.TestCase):
    def test_move_holds_between_segments(self):
        tl = Timeline()
        tl.move("drawer", "tx", 85, start=0.6, dur=1.4)
        tl.move("drawer", "tx", 0, start=3.4, dur=1.2)
        [(sel, action, times, values)] = tl.tracks(end=5.2)
        self.assertEqual((sel, action), ("drawer", "tx"))
        self.assertEqual(times, [0.0, 0.6, 2.0, 3.4, 4.6, 5.2])
        self.assertEqual(values, [0.0, 0.0, 85.0, 85.0, 0.0, 0.0])

    def test_vis_window_starts_hidden(self):
        tl = Timeline()
        tl.show("lamp", start=1.0, until=2.0)
        [(_, action, times, values)] = tl.tracks(end=3.0)
        self.assertEqual(action, "vis")
        # hidden until 1.0, visible to 2.0, hidden after
        def sample(t):
            for i in range(len(times) - 1, -1, -1):
                if t >= times[i]:
                    return values[i]
        self.assertEqual(sample(0.5), 0.0)
        self.assertEqual(sample(1.5), 1.0)
        self.assertEqual(sample(2.5), 0.0)

    def test_overlap_raises(self):
        tl = Timeline()
        tl.move("a", "tx", 10, start=0, dur=2)
        with self.assertRaises(ValueError):
            tl.move("a", "tx", 20, start=1, dur=2)

    def test_chapters_ride_along_in_the_clip(self):
        tl = Timeline()
        tl.move("lid", "tz", 30, start=0, dur=1).chapter("open the lid", 0)
        tl.move("tray", "tx", 80, start=1, dur=2).chapter("slide the tray", 1)
        clip = tl.clip("assembly", speed=1.5)
        self.assertEqual(clip["name"], "assembly")
        self.assertEqual(clip["speed"], 1.5)
        self.assertEqual(clip["chapters"], [{"t": 0.0, "name": "open the lid"}, {"t": 1.0, "name": "slide the tray"}])
        self.assertEqual(len(clip["tracks"]), 2)
        self.assertNotIn("chapters", Timeline().move("a", "tx", 1, start=0, dur=1).clip("plain"))

    def test_end_time_and_multiple_tracks(self):
        tl = Timeline()
        tl.spin("disc", "rz", 360, start=0, dur=6)
        tl.move("jaw", "ty", -18, start=1, dur=1)
        self.assertEqual(tl.end_time(), 6.0)
        self.assertEqual(len(tl.tracks()), 2)


if __name__ == "__main__":
    unittest.main()
