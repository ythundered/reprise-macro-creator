import json
import os
import sys
import tempfile
import time
import unittest

_tmp = tempfile.mkdtemp(prefix="reprise-test-")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ["APPDATA"] = _tmp

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from reprise import paths, window as win
from reprise.dialogs import ActionDialog, HelpDialog, SettingsDialog
from reprise.model import TYPES, new_action

from .fake import FakeBackend

app = QApplication.instance() or QApplication([])


def spin(seconds=0.1):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


class UiCase(unittest.TestCase):
    def setUp(self):
        for p in (paths.SESSION_PATH, paths.SETTINGS_PATH):
            if os.path.exists(p):
                os.remove(p)
        self.b = FakeBackend()
        self.w = win.MainWindow(backend=self.b)
        self.w.show()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        spin(0.01)

    def add(self, *acts):
        self.w.insert_actions(list(acts), len(self.w.macro["actions"]))

    def rows(self):
        return [a["type"] for a in self.w.macro["actions"]]


class ButtonStateTests(UiCase):
    def test_empty_state(self):
        w = self.w
        self.assertIn("reprise macro creator", w.windowTitle())
        self.assertTrue(w.welcome.isVisible())
        self.assertFalse(w.a_play.isEnabled())
        self.assertFalse(w.a_stop.isEnabled())
        self.assertFalse(w.a_pause.isEnabled())
        self.assertFalse(w.a_del.isEnabled())
        self.assertFalse(w.a_undo.isEnabled())
        self.assertTrue(w.a_record.isEnabled())

    def test_with_rows_and_selection(self):
        w = self.w
        self.add(new_action("sleep"))
        self.assertFalse(w.welcome.isVisible())
        self.assertTrue(w.a_play.isEnabled())
        self.assertTrue(w.a_undo.isEnabled())
        w.select_rows([0])
        self.assertTrue(w.a_del.isEnabled())
        self.assertTrue(w.a_playsel.isEnabled())
        w.table.selectionModel().clearSelection()
        self.assertFalse(w.a_del.isEnabled())

    def test_recording_locks_editing(self):
        w = self.w
        self.add(new_action("sleep"))
        w.select_rows([0])
        w.toggle_record()
        self.assertTrue(w.banner.isVisible())
        self.assertFalse(w.a_play.isEnabled())
        self.assertFalse(w.a_del.isEnabled())
        self.assertFalse(w.commands.isEnabled())
        self.assertTrue(w.a_stop.isEnabled())
        w.delete_rows()
        self.assertEqual(self.rows(), ["sleep"])
        w.stop_all()
        self.assertFalse(w.banner.isVisible())
        self.assertTrue(w.commands.isEnabled())

    def test_every_toolbar_action_has_a_tooltip_and_lowercase_text(self):
        from PySide6.QtGui import QAction
        for a in self.w.findChildren(QAction):
            self.assertEqual(a.text(), a.text().lower(), a.text())
        for b in self.w.commands.findChildren(QPushButton):
            self.assertEqual(b.text(), b.text().lower())
            self.assertTrue(b.toolTip())


class EditingTests(UiCase):
    def test_undo_redo(self):
        w = self.w
        self.add(new_action("sleep"))
        self.add(new_action("stop"))
        w.do_undo()
        self.assertEqual(self.rows(), ["sleep"])
        w.do_redo()
        self.assertEqual(self.rows(), ["sleep", "stop"])
        self.assertTrue(w.a_undo.isEnabled())

    def test_delete_takes_block_partner(self):
        w = self.w
        self.add(new_action("loop"), new_action("sleep"), new_action("endloop"))
        w.select_rows([0])
        w.delete_rows()
        self.assertEqual(self.rows(), ["sleep"])
        self.assertEqual(w.model.info["errors"], [])

    def test_move_keeps_gaps(self):
        w = self.w
        self.add(*[new_action("text", text=c) for c in "abcd"])
        w.select_rows([1, 3])
        w.move_rows(-1)
        self.assertEqual([a["p"]["text"] for a in w.macro["actions"]], list("badc"))
        self.assertEqual(w.selected_rows(), [0, 2])

    def test_wrap_selection(self):
        w = self.w
        self.add(new_action("sleep"), new_action("stop"))
        w.select_rows([0, 1])
        orig = win.ActionDialog
        class Auto:
            def __init__(self, parent, a):
                self.action = a
            def exec(self):
                return True
        win.ActionDialog = Auto
        try:
            w.insert_type("loop", wrap=True)
        finally:
            win.ActionDialog = orig
        self.assertEqual(self.rows(), ["loop", "sleep", "stop", "endloop"])

    def test_inline_edit_rules(self):
        w = self.w
        self.add(new_action("label"), new_action("sleep"))
        m = w.model
        self.assertFalse(m.flags(m.index(0, 3)) & Qt.ItemIsEditable)
        self.assertFalse(m.flags(m.index(0, 4)) & Qt.ItemIsEditable)
        self.assertTrue(m.flags(m.index(1, 4)) & Qt.ItemIsEditable)
        undo_before = len(w.undo[id(w.macro)])
        self.assertTrue(m.setData(m.index(1, 4), 250))
        self.assertEqual(w.macro["actions"][1]["delay"], 250)
        self.assertEqual(len(w.undo[id(w.macro)]), undo_before + 1)
        self.assertFalse(m.setData(m.index(1, 4), 250))
        self.assertEqual(len(w.undo[id(w.macro)]), undo_before + 1)

    def test_filter_survives_edits(self):
        w = self.w
        self.add(new_action("sleep"), new_action("text", text="find me"))
        w.filter.setText("find")
        self.assertTrue(w.table.isRowHidden(0))
        self.assertFalse(w.table.isRowHidden(1))
        self.add(new_action("stop"))
        self.assertTrue(w.table.isRowHidden(0))
        self.assertTrue(w.table.isRowHidden(2))

    def test_copy_paste_rows(self):
        w = self.w
        self.add(new_action("text", text="x"))
        w.select_rows([0])
        w.copy_rows()
        w.paste_rows()
        self.assertEqual(self.rows(), ["text", "text"])

    def test_tabs(self):
        w = self.w
        w.add_macro()
        self.assertEqual(w.tabs.count(), 2)
        self.add(new_action("sleep"))
        w.settings["confirm_delete"] = False
        w.delete_macro(1)
        self.assertEqual(w.tabs.count(), 1)
        w.delete_macro(0)
        self.assertEqual(w.tabs.count(), 1)


class DialogTests(UiCase):
    def test_every_action_dialog_opens_and_round_trips(self):
        for t in TYPES:
            a = new_action(t)
            d = ActionDialog(self.w, a)
            d.show()
            d._refresh_visibility()
            self.assertEqual(d.collect()["type"], t)
            d.reject()

    def test_bad_input_is_refused_with_a_message(self):
        d = ActionDialog(self.w, new_action("label"))
        d.fields["name"].w.setText("not valid")
        d._accept()
        self.assertFalse(d.result())
        self.assertIn("label", d.result_label.text())

        d = ActionDialog(self.w, new_action("key"))
        d.fields["key"].w.setCurrentText("nosuchkey")
        d._accept()
        self.assertIn("unknown key", d.result_label.text())

    def test_conditional_fields(self):
        d = ActionDialog(self.w, new_action("if"))
        d.show()
        self.assertTrue(d._vis["expr"])
        self.assertFalse(d._vis["window"])
        d.fields["kind"].w.setCurrentText("window active")
        self.assertFalse(d._vis["expr"])
        self.assertTrue(d._vis["window"])
        d.reject()

    def test_typing_does_not_resize_the_dialog(self):
        d = ActionDialog(self.w, new_action("text"))
        d.show()
        d.resize(900, 700)
        d.fields["text"].w.setPlainText("hello")
        spin(0.02)
        self.assertEqual(d.width(), 900)
        d.reject()

    def test_settings_refuses_clashing_hotkeys(self):
        d = SettingsDialog(self.w, self.w.settings)
        d.hk["play"].setText("f9")
        d._accept()
        self.assertFalse(d.result())
        self.assertIn("f9", d.error.text())
        d.hk["play"].setText("nosuchkey")
        d._accept()
        self.assertIn("nosuchkey", d.error.text())
        d.reject()

    def test_help_mentions_the_real_hotkeys(self):
        from PySide6.QtWidgets import QTextBrowser
        d = HelpDialog(self.w, {"record": "f6", "play": "f7", "pause": "", "stop": "f1"})
        text = " ".join(v.toPlainText() for v in d.findChildren(QTextBrowser))
        self.assertIn("f6", text)
        self.assertIn("(no hotkey)", text)
        d.reject()


class StartupTests(UiCase):
    def test_permission_prompt_then_fix(self):
        calls = []
        self.b.missing_permissions = lambda: True
        self.b.fix_permissions = lambda: calls.append("fix") or True
        orig = win.ask
        win.ask = lambda *a, **k: "yes"
        try:
            self.w._startup_problems()
        finally:
            win.ask = orig
        self.assertEqual(calls, ["fix"])

    def test_declining_does_not_touch_anything(self):
        calls = []
        self.b.missing_permissions = lambda: True
        self.b.fix_permissions = lambda: calls.append("fix") or True
        orig = win.ask
        win.ask = lambda *a, **k: "no"
        try:
            self.w._startup_problems()
        finally:
            win.ask = orig
        self.assertEqual(calls, [])


class CaptureTests(UiCase):
    def key(self, name, down=True):
        self.w._on_input({"kind": "key", "name": name, "down": down, "repeat": False, "t": 0})
        spin(0.01)

    def test_detect_key(self):
        got = []
        self.w.capture_next_key(lambda n, m: got.append(n))
        self.key("q")
        self.assertEqual(got, ["q"])
        self.key("q", False)

    def test_timeout_gives_the_keyboard_back(self):
        got = []
        self.w.capture_next_key(lambda n, m: got.append(n))
        self.w.cancel_capture()
        self.assertEqual(got, [None])
        self.assertIsNone(self.w._capture)

    def test_closing_a_dialog_cancels_capture(self):
        d = ActionDialog(self.w, new_action("key"))
        d.show()
        self.w.capture_next_key(lambda n, m: None)
        d.reject()
        self.assertIsNone(self.w._capture)


class HotkeyTests(UiCase):
    def press(self, name):
        self.w._on_input({"kind": "key", "name": name, "down": True, "repeat": False, "t": 0})
        self.w._on_input({"kind": "key", "name": name, "down": False, "repeat": False, "t": 0})
        spin(0.03)

    def test_record_toggle_and_hotkey_not_recorded(self):
        w = self.w
        self.b.focused_self = False
        self.press("f9")
        self.assertTrue(w.recorder.active)
        self.press("a")
        self.press("b")
        self.press("f9")
        self.assertFalse(w.recorder.active)
        self.assertEqual(self.rows(), ["text"])
        self.assertEqual(w.macro["actions"][0]["p"]["text"], "ab")

    def test_macro_hotkey_field(self):
        w = self.w
        w.hotkey_edit.setText("f5")
        w._on_macro_hotkey()
        self.assertEqual(w.macro["hotkey"], "f5")
        self.assertIn("f5", w.tabs.tabText(0))
        self.assertIn("f5", self.b.blocked)
        w.hotkey_edit.setText("f9")
        w._on_macro_hotkey()
        self.assertEqual(w.macro["hotkey"], "f5")


class PlaybackTests(UiCase):
    def wait_done(self):
        end = time.monotonic() + 5
        while self.w.busy and time.monotonic() < end:
            spin(0.01)
        spin(0.05)

    def test_play_flow(self):
        w = self.w
        self.add(new_action("text", text="hi"))
        w.play()
        self.assertTrue(w.banner.isVisible() or not w.player.running)
        self.wait_done()
        self.assertFalse(w.banner.isVisible())
        self.assertEqual("".join(e[1] for e in self.b.log if e[0] == "char"), "hi")
        self.assertEqual(w.state_label.text(), "finished")
        self.assertTrue(w.a_play.isEnabled())

    def test_pause_and_stop_buttons(self):
        w = self.w
        self.add(new_action("sleep", ms=60000))
        w.play()
        spin(0.05)
        self.assertTrue(w.a_stop.isEnabled())
        self.assertFalse(w.commands.isEnabled())
        w.toggle_pause()
        spin(0.05)
        self.assertEqual(w.state_label.text(), "paused")
        self.assertEqual(w.a_pause.text(), "resume")
        w.stop_all()
        self.wait_done()
        self.assertEqual(w.state_label.text(), "stopped")
        self.assertEqual(w.a_pause.text(), "pause")

    def test_structure_error_points_at_the_row(self):
        w = self.w
        self.add(new_action("sleep"), new_action("loop"))
        w.play()
        self.assertFalse(w.player.running)
        self.assertIn("row 2", w.state_label.text())
        self.assertEqual(w.selected_rows(), [1])

    def test_only_selected_includes_block_partner(self):
        w = self.w
        self.add(new_action("text", text="a"), new_action("loop", count=2), new_action("text", text="b"), new_action("endloop"))
        w.select_rows([1, 2])
        w.play(only_selected=True)
        self.wait_done()
        self.assertEqual("".join(e[1] for e in self.b.log if e[0] == "char"), "bb")

    def test_message_box_closes_on_stop(self):
        w = self.w
        self.add(new_action("msgbox", text="hello"))
        QTimer.singleShot(150, w.stop_all)
        w.play()
        self.wait_done()
        self.assertIsNone(w._msgbox)
        self.assertEqual(w.state_label.text(), "stopped")


class ProjectTests(UiCase):
    def path(self, name="p.reprise"):
        return os.path.join(_tmp, name)

    def test_save_and_open(self):
        w = self.w
        self.add(new_action("text", text="persist"))
        w.path = self.path()
        self.assertTrue(w.save_project())
        self.assertFalse(w.modified)
        w.macro["actions"].clear()
        self.assertTrue(w._open_path(self.path()))
        self.assertEqual(w.macro["actions"][0]["p"]["text"], "persist")

    def test_open_rejects_garbage(self):
        p = self.path("bad.reprise")
        with open(p, "w") as f:
            f.write('{"nope": 1}')
        orig = win.message
        seen = []
        win.message = lambda *a, **k: seen.append(a[2])
        try:
            self.assertFalse(self.w._open_path(p))
        finally:
            win.message = orig
        self.assertTrue(seen)

    def test_unsaved_untitled_work_prompts(self):
        w = self.w
        self.add(new_action("sleep"))
        asked = []
        orig = win.ask
        win.ask = lambda *a, **k: asked.append(a[2]) or "cancel"
        try:
            self.assertFalse(w._confirm_discard())
            w.new_project()
        finally:
            win.ask = orig
        self.assertTrue(asked)
        self.assertEqual(self.rows(), ["sleep"])

    def test_example_is_valid_and_not_bound_to_a_path(self):
        w = self.w
        self.assertTrue(w.open_example() is None)
        self.assertEqual(w.path, "")
        self.assertEqual(w.model.info["errors"], [])
        self.assertTrue(w.macro["actions"])

    def test_session_restores(self):
        w = self.w
        self.add(new_action("text", text="session"))
        w._save_session()
        if sys.platform != "win32":
            self.assertEqual(os.stat(paths.SESSION_PATH).st_mode & 0o777, 0o600)
        w2 = win.MainWindow(backend=FakeBackend())
        try:
            self.assertEqual(w2.macro["actions"][0]["p"]["text"], "session")
        finally:
            w2.close()

    def test_export_file_is_crlf_with_bom(self):
        import unittest.mock as um
        w = self.w
        self.add(new_action("sleep"))
        out = self.path("out.ahk")
        with um.patch.object(win.QFileDialog, "getSaveFileName", return_value=(out, "")):
            w.export_ahk()
        with open(out, "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)

    def test_saved_file_is_json(self):
        w = self.w
        self.add(new_action("sleep"))
        w.path = self.path("j.reprise")
        w.save_project()
        with open(w.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["app"], "reprise macro creator")


if __name__ == "__main__":
    unittest.main()
