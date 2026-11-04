import sys
import time
import unittest

import numpy as np


@unittest.skipUnless(sys.platform == "win32", "windows only")
class WindowsBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from reprise.backend_win import Backend
        cls.b = Backend()
        cls.b.start_listener()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.b.shutdown()

    def test_screen(self):
        w, h = self.b.screen_size()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        a = self.b.grab(0, 0, 9, 4)
        self.assertIsInstance(a, np.ndarray)
        self.assertEqual(a.shape, (5, 10, 3))
        self.assertEqual(len(self.b.pixel(1, 1)), 3)

    def test_cursor_moves(self):
        self.b.move(40, 50)
        self.assertEqual(self.b.cursor_pos(), (40, 50))

    def test_windows_can_be_listed(self):
        self.assertIsInstance(self.b.windows(), list)
        self.assertIsNone(self.b.find_window("no window is called this 123"))
        self.assertFalse(self.b.activate_window("no window is called this 123"))
        self.assertFalse(self.b.close_window("no window is called this 123"))

    def test_input_injection_does_not_raise(self):
        self.b.key("f24", True)
        self.b.key("f24", False)
        self.assertTrue(self.b.type_char("a"))
        self.assertTrue(self.b.type_char("\n"))
        self.b.button("xbutton2", True)
        self.b.button("xbutton2", False)
        self.b.wheel("down", 1)
        with self.assertRaises(ValueError):
            self.b.key("nonsense", True)

    def test_run_returns_a_process(self):
        p = self.b.run("exit 3")
        self.assertEqual(p.wait(10), 3)

    def test_hook_ignores_its_own_injected_keys(self):
        seen = []
        self.b.subscribe(seen.append)
        self.b.key("f24", True)
        self.b.key("f24", False)
        time.sleep(0.2)
        self.assertEqual(seen, [])
        self.b.subscribers.remove(seen.append)


if __name__ == "__main__":
    unittest.main()
