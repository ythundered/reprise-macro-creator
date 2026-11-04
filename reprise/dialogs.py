import copy
import os
import time

from PySide6.QtCore import QEventLoop, QRect, QRegularExpression, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QPixmap, QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from . import APP_NAME
from .engine import hex_color, parse_color
from .keys import BUTTON_TABLE, format_hotkey, key_names
from .model import TYPES, UNTIMED, check_action
from .paths import IMAGES_DIR

TAG_COLORS = {"": "none", "#e5484d": "red", "#f08c2e": "orange", "#e5c246": "yellow", "#3fb950": "green",
              "#4c8dff": "blue", "#a371f7": "purple", "#8b8f9a": "gray"}


def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)


def lower_buttons(box):
    for b in box.buttons():
        b.setText(b.text().replace("&", "").lower())


def ok_cancel(dialog, on_ok=None):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    lower_buttons(bb)
    bb.accepted.connect(on_ok or dialog.accept)
    bb.rejected.connect(dialog.reject)
    return bb


def message(parent, title, text, icon=QMessageBox.Information):
    box = QMessageBox(icon, title, text, QMessageBox.NoButton, parent)
    box.addButton("ok", QMessageBox.AcceptRole)
    box.exec()


def ask(parent, title, text, choices):
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.NoButton, parent)
    made = {box.addButton(label, role): key for label, role, key in choices}
    box.exec()
    return made.get(box.clickedButton())


class ScreenPicker(QWidget):
    done = Signal(object)

    def __init__(self, region):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.region = region
        geo = QRect()
        for s in QGuiApplication.screens():
            geo = geo.united(s.geometry())
        self.origin = geo.topLeft()
        screen = QGuiApplication.primaryScreen()
        self.shot = screen.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height())
        self.setGeometry(geo)
        self.start = None
        self.cur = None
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.result = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self.start and self.cur:
            r = QRect(self.start, self.cur).normalized()
            p.drawPixmap(r, self.shot, r)
            p.setPen(QPen(QColor("#5b9dff"), 2))
            p.drawRect(r)
        if self.cur:
            p.setPen(QPen(QColor("#5b9dff"), 1))
            p.drawLine(self.cur.x(), 0, self.cur.x(), self.height())
            p.drawLine(0, self.cur.y(), self.width(), self.cur.y())

    def mouseMoveEvent(self, e):
        self.cur = e.position().toPoint()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.finish(None)
            return
        self.start = e.position().toPoint()
        self.cur = self.start
        if not self.region:
            g = self.start + self.origin
            self.finish((g.x(), g.y()))

    def mouseReleaseEvent(self, e):
        if self.region and self.start:
            r = QRect(self.start, e.position().toPoint()).normalized().translated(self.origin)
            self.finish((r.left(), r.top(), r.right(), r.bottom()))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.finish(None)

    def finish(self, r):
        self.result = r
        self.close()
        self.done.emit(r)


def qt_pick(region):
    w = ScreenPicker(region)
    loop = QEventLoop()
    w.done.connect(lambda _r: loop.quit())
    w.showFullScreen()
    loop.exec()
    return w.result


class Picker:
    def __init__(self, app):
        self.app = app

    def _hidden(self, work):
        b = self.app.backend
        tops = [w for w in QGuiApplication.topLevelWindows() if w.isVisible()]
        hidden = b.hide_self()
        if not hidden:
            for w in tops:
                w.setOpacity(0.0)
            QGuiApplication.processEvents()
            time.sleep(0.15)
        try:
            return work()
        except (OSError, RuntimeError, ValueError) as e:
            message(self.app, APP_NAME, f"could not read the screen:\n{e}", QMessageBox.Warning)
            return None
        finally:
            if hidden:
                b.show_self()
            else:
                for w in tops:
                    w.setOpacity(1.0)

    def _pick(self, region):
        b = self.app.backend
        r = b.pick_region() if region else b.pick_point()
        return qt_pick(region) if r is NotImplemented else r

    def point(self):
        return self._hidden(lambda: self._pick(False))

    def region(self):
        return self._hidden(lambda: self._pick(True))

    def color(self):
        # sample before our windows come back or we may read our own pixels
        def work():
            pt = self._pick(False)
            return (pt, self.app.backend.pixel(*pt)) if pt else None
        return self._hidden(work)

    def capture(self, path):
        def work():
            r = self._pick(True)
            if not r:
                return False
            self.app.backend.save_region(*r, path)
            return True
        return self._hidden(work)


def swatch_pixmap(color, size=14):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QPen(QColor("#00000080"), 1))
    p.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    p.end()
    return pm


class CaptureButton(QPushButton):
    def __init__(self, app, on_key, idle="detect", with_mods=False, buttons=False):
        super().__init__(idle)
        self.app = app
        self.idle = idle
        self.on_key = on_key
        self.with_mods = with_mods
        self.buttons = buttons
        self.clicked.connect(self.begin)
        self.setToolTip("press the key you want" + (" or a mouse button" if buttons else ""))

    def begin(self):
        self.setText("press...")
        self.setEnabled(False)
        self.app.capture_next_key(self.got, self.with_mods, self.buttons)

    def got(self, name, mods):
        self.setText(self.idle)
        self.setEnabled(True)
        if name:
            self.on_key(name, mods)


class HotkeyEdit(QWidget):
    edited = Signal()

    def __init__(self, app, value=""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.line = QLineEdit(value)
        self.line.setPlaceholderText("none")
        self.line.setToolTip("press set, then press the key. prefixes: ^ ctrl, ! alt, + shift, # win")
        self.line.editingFinished.connect(self.edited)
        self.btn = CaptureButton(app, self._set, "set", with_mods=True)
        lay.addWidget(self.line, 1)
        lay.addWidget(self.btn)

    def _set(self, name, mods):
        self.line.setText(format_hotkey(name, mods))
        self.edited.emit()

    def text(self):
        return self.line.text().strip().lower()

    def setText(self, v):
        self.line.setText(v)


class FieldWidget(QWidget):
    changed = Signal()

    def __init__(self, dlg, spec, params):
        super().__init__()
        self.dlg = dlg
        self.spec = spec
        self.kind = spec["kind"]
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        getattr(self, "_make_" + self.kind)(params)

    def _make_int(self, params):
        self.w = QSpinBox()
        lo, hi = self.spec["opts"] or (0, 1000000)
        self.w.setRange(lo, hi)
        self.w.setValue(int(params.get(self.spec["key"], 0) or 0))
        self.w.setAccelerated(True)
        self.w.valueChanged.connect(self.changed)
        self.lay.addWidget(self.w)
        self.lay.addStretch()

    def _make_str(self, params):
        self.w = QLineEdit(str(params.get(self.spec["key"], "")))
        self.w.textChanged.connect(self.changed)
        self.lay.addWidget(self.w)

    def _make_expr(self, params):
        self._make_str(params)
        self.w.setFont(self.dlg.mono)
        self.w.setPlaceholderText('count < 10 && foundx > 0')

    def _make_text(self, params):
        self.w = QPlainTextEdit(str(params.get(self.spec["key"], "")))
        self.w.setFont(self.dlg.mono)
        self.w.setMinimumHeight(90)
        self.w.textChanged.connect(self.changed)
        self.lay.addWidget(self.w)

    def _make_choice(self, params):
        self.w = QComboBox()
        opts = self.spec["opts"]
        self.w.addItems(opts)
        v = str(params.get(self.spec["key"], opts[0]))
        if v in opts:
            self.w.setCurrentText(v)
        self.w.currentTextChanged.connect(self.changed)
        self.lay.addWidget(self.w)
        self.lay.addStretch()

    def _make_bool(self, params):
        self.w = QCheckBox()
        self.w.setChecked(bool(params.get(self.spec["key"], False)))
        self.w.toggled.connect(self.changed)
        self.lay.addWidget(self.w)
        self.lay.addStretch()

    def _make_key(self, params):
        self.w = QComboBox()
        self.w.setEditable(True)
        buttons = bool(self.spec["opts"] and "buttons" in self.spec["opts"])
        names = key_names()
        if buttons:
            names = [n for n, _e, _v in BUTTON_TABLE] + names
        self.w.addItems(names)
        self.w.setCurrentText(str(params.get(self.spec["key"], "")))
        self.w.setMaxVisibleItems(20)
        self.w.currentTextChanged.connect(self.changed)
        self.lay.addWidget(self.w, 1)
        self.lay.addWidget(CaptureButton(self.dlg.app, lambda n, _m: self.w.setCurrentText(n), buttons=buttons))

    def _make_window(self, params):
        self.w = QComboBox()
        self.w.setEditable(True)
        self.w.setInsertPolicy(QComboBox.NoInsert)
        seen = set()
        for win in self.dlg.app.backend.windows():
            if win["pid"] == os.getpid():
                continue
            for s in (win["title"], f"ahk_class {win['class']}"):
                if s and s not in seen:
                    seen.add(s)
                    self.w.addItem(s)
        self.w.setCurrentText(str(params.get(self.spec["key"], "")))
        self.w.currentTextChanged.connect(self.changed)
        self.w.lineEdit().setPlaceholderText("part of the title, or ahk_class firefox")
        self.lay.addWidget(self.w, 1)

    def _make_color(self, params):
        self.w = QLineEdit(str(params.get(self.spec["key"], "ffffff")).lower())
        self.w.setFont(self.dlg.mono)
        self.w.setValidator(QRegularExpressionValidator(QRegularExpression("#?(0[xX])?[0-9a-fA-F]{0,6}")))
        self.w.setFixedWidth(90)
        self.sw = QPushButton()
        self.sw.setFixedSize(30, 26)
        self.sw.setToolTip("open the color chooser")
        self.sw.clicked.connect(self._color_dialog)
        self.w.textChanged.connect(self._update_swatch)
        self.w.textChanged.connect(self.changed)
        pick = QPushButton("pick on screen")
        pick.clicked.connect(self._pick_color)
        self.lay.addWidget(self.sw)
        self.lay.addWidget(self.w)
        self.lay.addWidget(pick)
        self.lay.addStretch()
        self._update_swatch()

    def _make_point(self, params):
        self.x = QLineEdit(str(params.get("x", "0")))
        self.y = QLineEdit(str(params.get("y", "0")))
        for e in (self.x, self.y):
            e.setFont(self.dlg.mono)
            e.setFixedWidth(110)
            e.setToolTip("a number, a variable or an expression like foundx + 10")
            e.textChanged.connect(self.changed)
        pick = QPushButton("pick on screen")
        pick.clicked.connect(self._pick_point)
        self.lay.addWidget(QLabel("x"))
        self.lay.addWidget(self.x)
        self.lay.addSpacing(4)
        self.lay.addWidget(QLabel("y"))
        self.lay.addWidget(self.y)
        self.lay.addWidget(pick)
        self.lay.addStretch()

    def _make_region(self, params):
        self.r = [QLineEdit(str(params.get(n, "0"))) for n in ("x1", "y1", "x2", "y2")]
        col = QVBoxLayout()
        col.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(5)
        for i, (lbl, e) in enumerate(zip(("x1", "y1", "x2", "y2"), self.r)):
            e.setFont(self.dlg.mono)
            e.setFixedWidth(78)
            e.setToolTip("a number, a variable or an expression")
            e.textChanged.connect(self.changed)
            row.addSpacing(10 if i == 2 else (4 if i else 0))
            row.addWidget(QLabel(lbl))
            row.addWidget(e)
        row.addStretch()
        btns = QHBoxLayout()
        sel = QPushButton("select area on screen")
        sel.clicked.connect(self._pick_region)
        full = QPushButton("whole screen")
        full.clicked.connect(self._full)
        btns.addWidget(sel)
        btns.addWidget(full)
        btns.addStretch()
        col.addLayout(row)
        col.addLayout(btns)
        self.lay.addLayout(col, 1)

    def _make_image(self, params):
        col = QVBoxLayout()
        row = QHBoxLayout()
        self.w = QLineEdit(str(params.get(self.spec["key"], "")))
        self.w.textChanged.connect(self._update_preview)
        self.w.textChanged.connect(self.changed)
        cap = QPushButton("capture from screen")
        cap.clicked.connect(self._capture)
        br = QPushButton("browse...")
        br.clicked.connect(self._browse)
        row.addWidget(self.w, 1)
        row.addWidget(cap)
        row.addWidget(br)
        self.preview = QLabel()
        self.preview.setObjectName("preview")
        self.preview.setMinimumHeight(70)
        self.preview.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        col.addLayout(row)
        col.addWidget(self.preview)
        self.lay.addLayout(col, 1)
        self._update_preview()

    def value(self):
        k = self.kind
        key = self.spec["key"]
        if k == "int":
            return {key: self.w.value()}
        if k in ("str", "expr"):
            return {key: self.w.text()}
        if k == "color":
            return {key: hex_color(parse_color(self.w.text() or "0"))}
        if k == "text":
            return {key: self.w.toPlainText()}
        if k in ("choice", "window"):
            return {key: self.w.currentText()}
        if k == "key":
            return {key: self.w.currentText().strip().lower()}
        if k == "bool":
            return {key: self.w.isChecked()}
        if k == "point":
            return {"x": self.x.text().strip() or "0", "y": self.y.text().strip() or "0"}
        if k == "region":
            return {n: e.text().strip() or "0" for n, e in zip(("x1", "y1", "x2", "y2"), self.r)}
        if k == "image":
            return {key: self.w.text().strip()}
        return {}

    def raw(self):
        if self.kind == "bool":
            return self.w.isChecked()
        if self.kind in ("choice", "key", "window"):
            return self.w.currentText()
        return None

    def _update_swatch(self):
        try:
            c = "#" + hex_color(parse_color(self.w.text() or "0"))
        except ValueError:
            c = "#000000"
        self.sw.setStyleSheet(f"background:{c}; border:1px solid #555a66; border-radius:4px;")

    def _color_dialog(self):
        try:
            cur = QColor("#" + hex_color(parse_color(self.w.text() or "0")))
        except ValueError:
            cur = QColor("white")
        c = QColorDialog.getColor(cur, self, "color")
        if c.isValid():
            self.w.setText(c.name()[1:].lower())

    def _pick_color(self):
        got = self.dlg.picker.color()
        if not got:
            return
        pt, rgb = got
        self.w.setText(hex_color(rgb))
        for f in self.dlg.fields.values():
            if f.kind == "point" and f.isVisibleTo(self.dlg):
                f.x.setText(str(pt[0]))
                f.y.setText(str(pt[1]))

    def _pick_point(self):
        pt = self.dlg.picker.point()
        if pt:
            self.x.setText(str(pt[0]))
            self.y.setText(str(pt[1]))

    def _pick_region(self):
        r = self.dlg.picker.region()
        if r:
            for e, v in zip(self.r, r):
                e.setText(str(v))

    def _full(self):
        w, h = self.dlg.app.backend.screen_size()
        for e, v in zip(self.r, (0, 0, w - 1, h - 1)):
            e.setText(str(v))

    def _capture(self):
        os.makedirs(IMAGES_DIR, exist_ok=True)
        stamp = time.strftime("img_%Y%m%d_%H%M%S")
        path = os.path.join(IMAGES_DIR, stamp + ".png")
        n = 1
        while os.path.exists(path):
            path = os.path.join(IMAGES_DIR, f"{stamp}_{n}.png")
            n += 1
        if self.dlg.picker.capture(path):
            self.w.setText(path)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "image", os.path.dirname(self.w.text()) or IMAGES_DIR,
                                           "images (*.png *.bmp *.jpg *.jpeg *.gif)")
        if p:
            self.w.setText(p)

    def _update_preview(self):
        p = os.path.expanduser(self.w.text().strip())
        if not p or not os.path.exists(p):
            self.preview.setText("no image yet")
            return
        pm = QPixmap(p)
        if pm.isNull():
            self.preview.setText("cannot read this image")
            return
        self.preview.setToolTip(f"{pm.width()} x {pm.height()}")
        if pm.height() > 120 or pm.width() > 360:
            pm = pm.scaled(360, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(pm)


class ActionDialog(QDialog):
    def __init__(self, app, action):
        super().__init__(app)
        self.app = app
        self.action = copy.deepcopy(action)
        self.picker = Picker(app)
        self.mono = QFont(app.mono_family)
        self.mono.setPointSize(10)
        t = action["type"]
        spec = TYPES[t]
        self.setWindowTitle(spec["label"])
        self.setMinimumWidth(600)
        root = QVBoxLayout(self)
        root.setSpacing(8)
        head = QLabel(spec["label"])
        head.setObjectName("dlgHead")
        root.addWidget(head)
        hint = QLabel(spec["hint"])
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(7)
        self.fields = {}
        p = self.action["p"]
        deps = {f["show"][0] for f in spec["fields"] if f["show"]}
        for f in spec["fields"]:
            w = FieldWidget(self, f, p)
            if f["key"] in deps:
                w.changed.connect(self._refresh_visibility)
            self.fields[f["key"]] = w
            self.form.addRow(f["label"], w)
        if spec["fields"]:
            box = QFrame()
            box.setObjectName("card")
            box.setLayout(self.form)
            root.addWidget(box)
        common = QFormLayout()
        common.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        common.setHorizontalSpacing(12)
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 1000000)
        self.repeat.setValue(int(action.get("repeat", 1)))
        self.delay = QSpinBox()
        self.delay.setRange(0, 86400000)
        self.delay.setSuffix(" ms")
        self.delay.setValue(int(action.get("delay", 0)))
        self.comment = QLineEdit(action.get("comment", ""))
        self.tag = QComboBox()
        for c, n in TAG_COLORS.items():
            if c:
                self.tag.addItem(swatch_pixmap(c), n, c)
            else:
                self.tag.addItem(n, c)
        self.tag.setCurrentIndex(max(0, self.tag.findData(action.get("color", ""))))
        rd = QHBoxLayout()
        rd.setSpacing(6)
        if t not in UNTIMED:
            rd.addWidget(QLabel("repeat"))
            rd.addWidget(self.repeat)
            rd.addSpacing(10)
            rd.addWidget(QLabel("then wait"))
            rd.addWidget(self.delay)
            rd.addSpacing(10)
        rd.addWidget(QLabel("row color"))
        rd.addWidget(self.tag)
        rd.addStretch()
        common.addRow(rd)
        common.addRow("comment", self.comment)
        root.addLayout(common)
        self.result_label = QLabel("")
        self.result_label.setObjectName("result")
        self.result_label.setWordWrap(True)
        root.addWidget(self.result_label)
        bb = ok_cancel(self, self._accept)
        if t in ("pixelgetcolor", "pixelsearch", "imagesearch", "if", "setvar", "winactivate", "winwait", "winclose", "loop"):
            test = bb.addButton("try it", QDialogButtonBox.ActionRole)
            test.setToolTip("runs just this check now and shows the result, nothing is clicked or typed")
            test.clicked.connect(self._test)
        root.addWidget(bb)
        self._vis = {}
        self._refresh_visibility()

    def _refresh_visibility(self):
        vis = {}
        for key, w in self.fields.items():
            show = w.spec["show"]
            on = True
            if show:
                dep = self.fields.get(show[0])
                on = dep is not None and dep.raw() in show[1]
            vis[key] = on
            self.form.setRowVisible(w, on)
        # only when rows came or went, or typing would undo the user's resize
        if vis != self._vis:
            self._vis = vis
            self.adjustSize()

    def collect(self):
        a = copy.deepcopy(self.action)
        for w in self.fields.values():
            a["p"].update(w.value())
        a["repeat"] = self.repeat.value()
        a["delay"] = self.delay.value() if a["type"] not in UNTIMED else 0
        a["comment"] = self.comment.text()
        a["color"] = self.tag.currentData() or ""
        return a

    def _show_result(self, text, bad=False):
        self.result_label.setText(text)
        self.result_label.setProperty("bad", bad)
        repolish(self.result_label)

    def _test(self):
        try:
            self._show_result(self.app.player.test(self.collect()) or "")
        except Exception as e:
            self._show_result(str(e), True)

    def _accept(self):
        try:
            a = self.collect()
        except ValueError:
            self._show_result("that color is not valid hex, use something like ff8800.", True)
            return
        problem = check_action(a)
        if problem is None:
            for key, w in self.fields.items():
                if w.kind == "key" and self._vis.get(key) and not self.app.backend.keymap.knows(a["p"][key]):
                    problem = f"unknown key: {a['p'][key]}"
        if problem:
            self._show_result(problem, True)
            return
        self.action = a
        self.accept()

    def done(self, r):
        self.app.cancel_capture()
        super().done(r)


class SettingsDialog(QDialog):
    def __init__(self, app, settings):
        super().__init__(app)
        self.app = app
        self.setWindowTitle("settings")
        self.setMinimumWidth(480)
        self.s = copy.deepcopy(settings)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        hk = QWidget()
        hf = QFormLayout(hk)
        self.hk = {}
        for k, label in (("record", "record / stop recording"), ("play", "play"), ("pause", "pause / resume"), ("stop", "stop")):
            e = HotkeyEdit(app, self.s["hotkeys"].get(k, ""))
            hf.addRow(label, e)
            self.hk[k] = e
        self.cb = {}
        self.cb["block_hotkeys"] = QCheckBox("keep these keys from reaching other apps")
        self.cb["block_hotkeys"].setChecked(bool(self.s.get("block_hotkeys", True)))
        hf.addRow(self.cb["block_hotkeys"])
        note = QLabel("these work from any window. keys you already bound in your compositor are left alone.")
        note.setWordWrap(True)
        note.setObjectName("dim")
        hf.addRow(note)
        self.error = QLabel("")
        self.error.setObjectName("result")
        self.error.setProperty("bad", True)
        self.error.setWordWrap(True)
        hf.addRow(self.error)
        tabs.addTab(hk, "hotkeys")

        rec = QWidget()
        rf = QFormLayout(rec)
        for k, label in (("merge_text", "turn typed letters into one text step"),
                         ("merge_double", "turn two quick clicks into a double click"),
                         ("ignore_self", "ignore input inside this window")):
            c = QCheckBox(label)
            c.setChecked(bool(self.s.get(k)))
            rf.addRow(c)
            self.cb[k] = c
        self.move_interval = QSpinBox()
        self.move_interval.setRange(5, 2000)
        self.move_interval.setSuffix(" ms")
        self.move_interval.setValue(int(self.s.get("move_interval", 40)))
        rf.addRow("mouse move sample rate", self.move_interval)
        self.default_delay = QSpinBox()
        self.default_delay.setRange(0, 60000)
        self.default_delay.setSuffix(" ms")
        self.default_delay.setValue(int(self.s.get("default_delay", 10)))
        rf.addRow("wait between steps when delays are off", self.default_delay)
        tabs.addTab(rec, "recording")

        pb = QWidget()
        pf = QFormLayout(pb)
        for k, label in (("follow", "scroll to the running row"),
                         ("confirm_delete", "ask before deleting a macro tab")):
            c = QCheckBox(label)
            c.setChecked(bool(self.s.get(k)))
            pf.addRow(c)
            self.cb[k] = c
        tabs.addTab(pb, "playback")
        root.addWidget(ok_cancel(self, self._accept))

    def _accept(self):
        problem = self.app.hotkey_problems({k: e.text() for k, e in self.hk.items()})
        if problem:
            self.error.setText(problem)
            repolish(self.error)
            return
        self.accept()

    def values(self):
        s = self.s
        for k, e in self.hk.items():
            s["hotkeys"][k] = e.text()
        for k, c in self.cb.items():
            s[k] = c.isChecked()
        s["move_interval"] = self.move_interval.value()
        s["default_delay"] = self.default_delay.value()
        return s

    def done(self, r):
        self.app.cancel_capture()
        super().done(r)


HELP_START = """
<h3>the short version</h3>
<p><b>1. record.</b> press record (or {record}), go to the window you want to automate and do the task. press {record} again to stop.
each thing you did becomes a row in the list.</p>
<p><b>2. tidy up.</b> double-click a row to change it. drag rows to reorder them. untick a row to skip it without deleting it.</p>
<p><b>3. play.</b> press play (or {play}). <b>{stop} stops it at any time</b>, and {pause} pauses it. any keys the macro was holding get let go.</p>
<h3>building by hand</h3>
<p>click anything in the commands list on the left. it opens a small form, and when you press ok the new row goes under the selected one.
loop and if add their closing row for you. select some rows and press wrap in loop to repeat just those.</p>
<h3>finding a spot on screen</h3>
<p>in any form, press pick on screen and click where you mean. the app hides itself while you pick.</p>
<h3>the script pane</h3>
<p>the pane on the right shows the macro as an autohotkey v1 script and follows your selection. file, export saves it as a .ahk file for windows.</p>
"""

HELP_KEYS = """
<table cellspacing="6">
<tr><td><b>{record}</b></td><td>record / stop recording</td></tr>
<tr><td><b>{play}</b></td><td>play the current macro</td></tr>
<tr><td><b>{pause}</b></td><td>pause / resume</td></tr>
<tr><td><b>{stop}</b></td><td>stop</td></tr>
<tr><td>&nbsp;</td><td></td></tr>
<tr><td><b>enter</b></td><td>edit the selected row</td></tr>
<tr><td><b>space</b></td><td>turn the selected rows on or off</td></tr>
<tr><td><b>delete</b></td><td>delete the selected rows</td></tr>
<tr><td><b>ctrl+d</b></td><td>duplicate</td></tr>
<tr><td><b>ctrl+up / down</b></td><td>move rows</td></tr>
<tr><td><b>ctrl+l / ctrl+i</b></td><td>wrap the selection in a loop / an if</td></tr>
<tr><td><b>ctrl+z / ctrl+y</b></td><td>undo / redo</td></tr>
<tr><td><b>ctrl+t</b></td><td>new macro tab</td></tr>
<tr><td><b>f2</b></td><td>rename the macro</td></tr>
<tr><td><b>ctrl+f5</b></td><td>play from the selected row</td></tr>
<tr><td><b>ctrl+shift+f5</b></td><td>play only the selected rows</td></tr>
</table>
<p>the top four work from any window and can be changed in settings.</p>
"""

HELP_EXPR = """
<p>expressions follow autohotkey syntax. you can use them in if, loop, variable steps, and x / y fields.</p>
<pre>count &lt; 10 &amp;&amp; foundx &gt; 0
name = "abc"
"hello " . name
foundx + 10</pre>
<p>inside text, write <code>%name%</code> to insert a variable.</p>
<h3>built-in values</h3>
<p><code>a_index</code> the current loop run, <code>foundx</code> / <code>foundy</code> where the last search hit, <code>errorlevel</code> 0 after a success and 1 after a failure,
<code>a_tickcount</code>, <code>a_now</code>, <code>a_screenwidth</code>, <code>a_screenheight</code>.</p>
<h3>functions</h3>
<p><code>abs round floor ceil mod min max sqrt strlen substr instr strreplace getkeystate winactive winexist</code></p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent, hotkeys):
        super().__init__(parent)
        self.setWindowTitle(f"how to use {APP_NAME}")
        self.resize(640, 560)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        names = {k: (hotkeys.get(k) or "(no hotkey)") for k in ("record", "play", "pause", "stop")}
        for title, html in (("start here", HELP_START.format(**names)), ("keys", HELP_KEYS.format(**names)),
                            ("expressions", HELP_EXPR)):
            view = QTextBrowser()
            view.setHtml(html)
            tabs.addTab(view, title)
        root.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        lower_buttons(bb)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
