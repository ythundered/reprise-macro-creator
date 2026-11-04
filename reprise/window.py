import copy
import json
import os
import shutil
import threading

from PySide6.QtCore import QByteArray, QEvent, QItemSelection, QItemSelectionModel, QMimeData, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QFontDatabase, QGuiApplication, QIcon, QImageReader, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTabBar, QTableView, QToolBar,
                               QToolButton, QVBoxLayout, QWidget)

from . import APP_NAME, __version__, ahk, icons
from .backend import create as create_backend
from .dialogs import (TAG_COLORS, ActionDialog, HelpDialog, HotkeyEdit, Picker, SettingsDialog, ask, message, repolish,
                      swatch_pixmap)
from .engine import MacroError, Player, hex_color
from .keys import MODIFIERS, hotkey_matches, parse_hotkey
from .model import (CATEGORY_COLORS, LOCKED_ON, TYPES, new_action, new_macro, normalize, normalize_macro, with_partners)
from .paths import EXAMPLE_PATH, ICON_PATH, SESSION_PATH, SETTINGS_PATH, write_atomic
from .recorder import Recorder
from .theme import C, stylesheet
from .widgets import MIME, ActionDelegate, CodeView, MacroModel

UNDO_LIMIT = 100
CAPTURE_TIMEOUT_MS = 8000

DEFAULT_SETTINGS = {
    "hotkeys": {"record": "f9", "play": "f10", "stop": "f12", "pause": "f8"},
    "rec_keys": True, "rec_mouse": True, "rec_wheel": True, "rec_moves": False, "rec_delays": True,
    "merge_text": True, "merge_double": True, "ignore_self": True, "move_interval": 40, "default_delay": 10,
    "follow": True, "confirm_delete": True, "block_hotkeys": True, "spy": False, "script": True, "last_path": "",
}

COMMANDS = [
    ("mouse", [("click", "click", {}), ("move", "mousemove", {}), ("scroll", "wheel", {})]),
    ("keyboard", [("press key", "key", {}), ("type text", "text", {}), ("wait for key", "keywait", {})]),
    ("timing and logic", [("pause", "sleep", {}), ("loop", "loop", {}), ("if", "if", {}), ("else", "else", {}),
                          ("break", "break", {}), ("label", "label", {}), ("goto", "goto", {}), ("stop", "stop", {})]),
    ("screen", [("find pixel", "pixelsearch", {}), ("find image", "imagesearch", {}), ("read pixel", "pixelgetcolor", {})]),
    ("windows", [("focus window", "winactivate", {}), ("wait for window", "winwait", {}), ("close window", "winclose", {})]),
    ("other", [("variable", "setvar", {}), ("run program", "run", {}), ("message", "msgbox", {}), ("note", "comment", {})]),
]
MENU_ONLY = [("double click", "click", {"clicks": 2}), ("continue", "continue", {}), ("read title", "wingettitle", {}),
             ("end loop", "endloop", {}), ("end if", "endif", {})]
NO_DIALOG = {"else", "endif", "endloop", "break", "continue", "stop"}


class Bridge(QObject):
    step = Signal(int)
    finished = Signal(str)
    log = Signal(str)
    iteration = Signal(int, int)
    msgbox = Signal(str, str, object)
    hotkey = Signal(str)
    rec_count = Signal(int)
    key_captured = Signal(str, object)
    spy = Signal(int, int, str, str)


class KeySwallower(QObject):
    def eventFilter(self, obj, e):
        return e.type() in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride)


class MacroTable(QTableView):
    overlay = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.overlay is not None:
            self.overlay.setGeometry(self.viewport().rect())


class MainWindow(QMainWindow):
    def __init__(self, open_path=None, backend=None):
        super().__init__()
        self.mono_family = self._pick_mono()
        self.mono_small = QFont(self.mono_family)
        self.mono_small.setPointSize(9)
        self.settings = self._load_settings()
        self.backend = backend or create_backend()
        self.bridge = Bridge()
        self.player = Player(self.backend, {
            "step": self._cb_step, "finished": self.bridge.finished.emit, "log": self.bridge.log.emit,
            "iteration": self.bridge.iteration.emit, "msgbox": self._cb_msgbox})
        self.recorder = Recorder(self.backend)
        self.picker = Picker(self)
        self.project = {"macros": [new_macro()]}
        self.path = ""
        self.modified = False
        self.undo = {}
        self.redo = {}
        self.maps = []
        self._step_value = None
        self._row_now = -1
        self._run_text = ""
        self._capture = None
        self._swallow = set()
        self._hotkeys = []
        self._swallower = KeySwallower()
        self._msgbox = None
        self._quit = threading.Event()
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1360, 880)
        self.setMinimumSize(980, 560)
        self._build()
        self._connect()
        self._load_session()
        if open_path:
            self._open_path(open_path)
        self._update_hotkeys()
        self.backend.subscribe(self._on_input)
        self.backend.start_listener()
        threading.Thread(target=self._spy_loop, daemon=True).start()
        self.table.setFocus()
        self._sync_actions()
        probs = self.backend.problems()
        if probs:
            QTimer.singleShot(400, lambda: message(self, APP_NAME, "\n\n".join(probs), QMessageBox.Warning))

    @property
    def busy(self):
        return self.recorder.active or self.player.running

    def _pick_mono(self):
        fams = set(QFontDatabase.families())
        for f in ("JetBrains Mono", "JetBrainsMono Nerd Font", "Cascadia Code", "Fira Code", "Source Code Pro",
                  "DejaVu Sans Mono", "Consolas", "Noto Sans Mono", "Monospace"):
            if f in fams:
                return f
        return QFontDatabase.systemFont(QFontDatabase.FixedFont).family()

    def _build(self):
        self.setStyleSheet(stylesheet(self.mono_family))
        self._build_actions()
        self._build_menu()
        self._build_toolbar()

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_bar())
        root.addWidget(self._build_banner())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.commands = self._build_commands()
        body.addWidget(self.commands)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setHandleWidth(1)
        self.split.addWidget(self._build_center())
        self.code_panel = self._build_code()
        self.split.addWidget(self.code_panel)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([830, 360])
        body.addWidget(self.split, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        sb = self.statusBar()
        self.state_label = QLabel("ready")
        self.state_label.setObjectName("state")
        self.spy_label = QLabel("")
        self.spy_label.setTextFormat(Qt.RichText)
        self.hint_label = QLabel("")
        sb.addWidget(self.state_label)
        sb.addPermanentWidget(self.spy_label)
        sb.addPermanentWidget(self.hint_label)

        self.step_timer = QTimer(self)
        self.step_timer.setInterval(40)
        self.step_timer.timeout.connect(self._apply_step)
        self.regen_timer = QTimer(self)
        self.regen_timer.setSingleShot(True)
        self.regen_timer.timeout.connect(self.regen_code)
        self.session_timer = QTimer(self)
        self.session_timer.setSingleShot(True)
        self.session_timer.timeout.connect(self._save_session)
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(self.cancel_capture)

    def _act(self, text, slot, shortcut=None, icon=None, table=False, checkable=False, tip=None):
        a = QAction(text, self)
        if icon:
            a.setIcon(icons.icon(*icon) if isinstance(icon, tuple) else icons.icon(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if table:
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        a.setCheckable(checkable)
        tip = tip or text.rstrip(".")
        a.setToolTip(f"{tip} ({shortcut.lower()})" if shortcut else tip)
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        self.a_new = self._act("new", self.new_project, "Ctrl+N", "new", tip="new project")
        self.a_open = self._act("open", self.open_project, "Ctrl+O", "open", tip="open a project")
        self.a_example = self._act("open example", self.open_example, tip="load a small example that only shows messages")
        self.a_save = self._act("save", self.save_project, "Ctrl+S", "save", tip="save the project")
        self.a_saveas = self._act("save as...", self.save_project_as, "Ctrl+Shift+S")
        self.a_export = self._act("export", self.export_ahk, "Ctrl+E", "export", tip="export as an autohotkey script")
        self.a_quit = self._act("quit", self.close, "Ctrl+Q")
        self.a_undo = self._act("undo", self.do_undo, "Ctrl+Z", "undo")
        self.a_redo = self._act("redo", self.do_redo, "Ctrl+Y", "redo")
        self.a_edit = self._act("edit", self.edit_current, "Return", "edit", table=True, tip="edit the selected row")
        self.a_cut = self._act("cut", self.cut_rows, "Ctrl+X", table=True)
        self.a_copy = self._act("copy", self.copy_rows, "Ctrl+C", table=True)
        self.a_paste = self._act("paste", self.paste_rows, "Ctrl+V", table=True)
        self.a_dup = self._act("duplicate", self.duplicate_rows, "Ctrl+D", "copy", table=True)
        self.a_del = self._act("delete", self.delete_rows, "Delete", "delete", table=True)
        self.a_toggle = self._act("on / off", self.toggle_rows, "Space", "toggle", table=True,
                                  tip="skip the selected rows without deleting them")
        self.a_up = self._act("up", lambda: self.move_rows(-1), "Ctrl+Up", "up", table=True, tip="move up")
        self.a_down = self._act("down", lambda: self.move_rows(1), "Ctrl+Down", "down", table=True, tip="move down")
        self.a_selall = self._act("select all", lambda: self.table.selectAll(), "Ctrl+A", table=True)
        self.a_wrap_loop = self._act("wrap in loop", lambda: self.insert_type("loop", wrap=True), "Ctrl+L", "wraploop",
                                     table=True, tip="repeat the selected rows")
        self.a_wrap_if = self._act("wrap in if", lambda: self.insert_type("if", wrap=True), "Ctrl+I", "wrapif",
                                   table=True, tip="only run the selected rows when a condition is true")
        self.a_record = self._act("record", self.toggle_record, icon=("record", C["rec"], 22))
        self.a_play = self._act("play", lambda: self.play(), icon=("play", C["ok"], 22))
        self.a_playsel = self._act("from row", lambda: self.play(from_selected=True), "Ctrl+F5", "playfrom",
                                   tip="play once, starting at the selected row")
        self.a_playonly = self._act("play selected rows only", lambda: self.play(only_selected=True), "Ctrl+Shift+F5", "playonly")
        self.a_pause = self._act("pause", self.toggle_pause, icon=("pause", C["warn"], 22))
        self.a_stop = self._act("stop", self.stop_all, icon=("halt", C["text"], 22))
        self.a_newmacro = self._act("new macro tab", self.add_macro, "Ctrl+T", "plus")
        self.a_rename = self._act("rename macro...", self.rename_macro, "F2")
        self.a_delmacro = self._act("delete macro tab", lambda: self.delete_macro(self.tabs.currentIndex()))
        self.a_settings = self._act("settings", self.open_settings, "Ctrl+,", "settings")
        self.a_help = self._act("help", self.show_help, "F1", "help", tip=f"how to use {APP_NAME}")
        self.a_pickcolor = self._act("pick color from screen", self.pick_color_tool, "Ctrl+Shift+C")
        self.a_pickpoint = self._act("pick point from screen", self.pick_point_tool, "Ctrl+Shift+P")
        self.a_spy = self._act("show color and window under cursor", self.toggle_spy, "Ctrl+Shift+W", checkable=True)
        self.a_spy.setChecked(bool(self.settings.get("spy")))
        self.a_script = self._act("script", self.toggle_script, icon="script", checkable=True,
                                  tip="show the autohotkey script next to the list")
        self.a_script.setChecked(bool(self.settings.get("script", True)))
        self.a_copycode = self._act("copy script", self.copy_code, icon=("copy", C["text"], 16))
        self.edit_actions = [self.a_edit, self.a_cut, self.a_copy, self.a_dup, self.a_del, self.a_toggle, self.a_up,
                             self.a_down, self.a_wrap_loop, self.a_wrap_if]

    def _fill_insert_menu(self, m):
        for head, entries in COMMANDS:
            m.addSection(head)
            for label, t, params in entries:
                m.addAction(icons.icon(t, CATEGORY_COLORS[TYPES[t]["cat"]], 16), label,
                            lambda t=t, params=params: self.insert_type(t, params))
        m.addSection("more")
        for label, t, params in MENU_ONLY:
            m.addAction(icons.icon(t, CATEGORY_COLORS[TYPES[t]["cat"]], 16), label,
                        lambda t=t, params=params: self.insert_type(t, params))

    def _build_menu(self):
        mb = self.menuBar()

        def fill(title, items):
            m = mb.addMenu(title)
            for a in items:
                m.addSeparator() if a is None else m.addAction(a)
            return m
        fill("file", (self.a_new, self.a_open, self.a_example, None, self.a_save, self.a_saveas, None, self.a_export,
                      None, self.a_quit))
        fill("edit", (self.a_undo, self.a_redo, None, self.a_edit, None, self.a_cut, self.a_copy, self.a_paste, self.a_dup,
                      self.a_del, None, self.a_toggle, self.a_up, self.a_down, None, self.a_wrap_loop, self.a_wrap_if,
                      None, self.a_selall))
        self._insert_menu = mb.addMenu("insert")
        self._fill_insert_menu(self._insert_menu)
        fill("macro", (self.a_record, self.a_play, self.a_playsel, self.a_playonly, self.a_pause, self.a_stop, None,
                       self.a_newmacro, self.a_rename, self.a_delmacro))
        fill("tools", (self.a_pickcolor, self.a_pickpoint, self.a_spy, None, self.a_script, self.a_copycode, None, self.a_settings))
        m = fill("help", (self.a_help,))
        m.addAction("about", self.show_about)

    def _build_toolbar(self):
        tb = QToolBar("main")
        tb.setObjectName("main")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setContextMenuPolicy(Qt.PreventContextMenu)
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.addToolBar(tb)
        for group in ((self.a_new, self.a_open, self.a_save, self.a_export), (self.a_undo, self.a_redo),
                      (self.a_record, self.a_play, self.a_pause, self.a_stop, self.a_playsel)):
            for a in group:
                tb.addAction(a)
            tb.addSeparator()
        self.rec_btn = tb.widgetForAction(self.a_record)
        self.rec_btn.setObjectName("recBtn")
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        for a in (self.a_script, self.a_settings, self.a_help):
            tb.addAction(a)

    def _bar_label(self, text):
        lab = QLabel(text)
        lab.setObjectName("barLabel")
        return lab

    def _bar_sep(self):
        sep = QFrame()
        sep.setObjectName("barSep")
        sep.setFixedWidth(1)
        return sep

    def _build_bar(self):
        bar = QFrame()
        bar.setObjectName("bar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 5, 10, 5)
        h.setSpacing(6)
        h.addWidget(self._bar_label("repeat"))
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(0, 100000000)
        self.repeat_spin.setSpecialValueText("forever")
        self.repeat_spin.setFixedWidth(88)
        self.repeat_spin.setToolTip("how many times the whole macro runs. 0 means forever")
        h.addWidget(self.repeat_spin)
        h.addSpacing(6)
        h.addWidget(self._bar_label("speed"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.05, 50)
        self.speed_spin.setSingleStep(0.25)
        self.speed_spin.setPrefix("x ")
        self.speed_spin.setFixedWidth(84)
        self.speed_spin.setToolTip("2 runs every wait twice as fast, 0.5 twice as slow")
        h.addWidget(self.speed_spin)
        h.addSpacing(6)
        h.addWidget(self._bar_label("hotkey"))
        self.hotkey_edit = HotkeyEdit(self)
        self.hotkey_edit.setFixedWidth(130)
        self.hotkey_edit.setToolTip("plays this macro from any window")
        h.addWidget(self.hotkey_edit)
        h.addSpacing(6)
        h.addWidget(self._bar_sep())
        h.addSpacing(6)
        h.addWidget(self._bar_label("record"))
        self.rec_boxes = {}
        for key, label, tip in (("rec_keys", "keys", "record the keyboard"), ("rec_mouse", "clicks", "record mouse buttons"),
                                ("rec_wheel", "scroll", "record the mouse wheel"),
                                ("rec_moves", "moves", "record the path the cursor takes. makes long macros"),
                                ("rec_delays", "timing", "keep the real waits between actions")):
            c = QCheckBox(label)
            c.setToolTip(tip)
            c.setChecked(bool(self.settings.get(key)))
            c.toggled.connect(lambda on, key=key: self._set_rec_option(key, on))
            self.rec_boxes[key] = c
            h.addWidget(c)
        h.addStretch()
        return bar

    def _build_banner(self):
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        h = QHBoxLayout(self.banner)
        h.setContentsMargins(12, 5, 8, 5)
        self.banner_icon = QLabel()
        self.banner_label = QLabel()
        self.banner_pause = QPushButton("pause")
        self.banner_pause.clicked.connect(self.toggle_pause)
        self.banner_stop = QPushButton("stop")
        self.banner_stop.clicked.connect(self.stop_all)
        h.addWidget(self.banner_icon)
        h.addWidget(self.banner_label, 1)
        h.addWidget(self.banner_pause)
        h.addWidget(self.banner_stop)
        self.banner.hide()
        return self.banner

    def _build_commands(self):
        frame = QFrame()
        frame.setObjectName("commands")
        frame.setFixedWidth(166)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(0)
        for head, entries in COMMANDS:
            h = QLabel(head)
            h.setObjectName("cmdHead")
            lay.addWidget(h)
            for label, t, params in entries:
                b = QPushButton(label)
                b.setObjectName("cmd")
                b.setIcon(icons.icon(t, CATEGORY_COLORS[TYPES[t]["cat"]], 16))
                b.setIconSize(QSize(16, 16))
                b.setFocusPolicy(Qt.NoFocus)
                b.setToolTip(TYPES[t]["hint"])
                b.clicked.connect(lambda _=False, t=t, params=params: self.insert_type(t, params))
                lay.addWidget(b)
        lay.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return frame

    def _build_welcome(self, parent):
        w = QFrame(parent)
        w.setObjectName("welcome")
        center = QGridLayout(w)
        box = QWidget()
        center.addWidget(box, 0, 0, Qt.AlignCenter)
        outer = QVBoxLayout(box)
        head = QLabel("make your first macro")
        head.setObjectName("welcomeHead")
        outer.addWidget(head)
        outer.addSpacing(10)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.welcome_steps = []
        for i in range(3):
            n = QLabel(str(i + 1))
            n.setObjectName("stepNum")
            n.setFixedSize(24, 24)
            n.setAlignment(Qt.AlignCenter)
            t = QLabel()
            t.setObjectName("stepText")
            grid.addWidget(n, i, 0)
            grid.addWidget(t, i, 1)
            self.welcome_steps.append(t)
        outer.addLayout(grid)
        outer.addSpacing(14)
        btns = QHBoxLayout()
        self.welcome_record = QPushButton(icons.icon("record", C["rec"], 16), "record")
        self.welcome_record.setObjectName("recordBig")
        self.welcome_record.clicked.connect(self.toggle_record)
        example = QPushButton("open example")
        example.clicked.connect(self.open_example)
        guide = QPushButton("how it works")
        guide.clicked.connect(self.show_help)
        for b in (self.welcome_record, example, guide):
            btns.addWidget(b)
        btns.addStretch()
        outer.addLayout(btns)
        return w

    def _build_center(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top = QFrame()
        top.setObjectName("tabRow")
        th = QHBoxLayout(top)
        th.setContentsMargins(6, 0, 8, 0)
        th.setSpacing(4)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setDrawBase(False)
        th.addWidget(self.tabs)
        add = QToolButton()
        add.setDefaultAction(self.a_newmacro)
        add.setToolButtonStyle(Qt.ToolButtonIconOnly)
        add.setIconSize(QSize(16, 16))
        th.addWidget(add)
        th.addStretch()
        self.count_label = QLabel("")
        self.count_label.setObjectName("dim")
        th.addWidget(self.count_label)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filter rows")
        self.filter.setClearButtonEnabled(True)
        self.filter.setFixedWidth(170)
        th.addWidget(self.filter)
        v.addWidget(top)

        rows = QToolBar("rows")
        rows.setObjectName("rows")
        rows.setMovable(False)
        rows.setFloatable(False)
        rows.setContextMenuPolicy(Qt.PreventContextMenu)
        rows.setIconSize(QSize(16, 16))
        rows.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for a in (self.a_edit, self.a_dup, self.a_del, None, self.a_up, self.a_down, None, self.a_toggle, self.a_wrap_loop,
                  self.a_wrap_if):
            rows.addSeparator() if a is None else rows.addAction(a)
        v.addWidget(rows)

        self.model = MacroModel(self)
        self.table = MacroTable()
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(1, ActionDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setDragDropMode(QAbstractItemView.InternalMove)
        self.table.setDefaultDropAction(Qt.MoveAction)
        self.table.setDragDropOverwriteMode(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        for i, wdt in enumerate((64, 150, 340, 54, 66, 140)):
            self.table.setColumnWidth(i, wdt)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        for a in (self.a_edit, self.a_cut, self.a_copy, self.a_paste, self.a_dup, self.a_del, self.a_toggle,
                  self.a_up, self.a_down, self.a_selall, self.a_wrap_loop, self.a_wrap_if):
            self.table.addAction(a)
        v.addWidget(self.table, 1)
        self.welcome = self._build_welcome(self.table.viewport())
        self.table.overlay = self.welcome
        return w

    def _build_code(self):
        f = QFrame()
        f.setObjectName("codePanel")
        f.setVisible(self.a_script.isChecked())
        v = QVBoxLayout(f)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QFrame()
        head.setObjectName("codeHead")
        hh = QHBoxLayout(head)
        hh.setContentsMargins(10, 3, 6, 3)
        t = QLabel("autohotkey script (read only)")
        t.setObjectName("paneTitle")
        hh.addWidget(t)
        hh.addStretch()
        b = QToolButton()
        b.setDefaultAction(self.a_copycode)
        b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        b.setIconSize(QSize(16, 16))
        hh.addWidget(b)
        v.addWidget(head)
        self.code = CodeView(self.mono_family)
        v.addWidget(self.code, 1)
        return f

    def _connect(self):
        b = self.bridge
        b.finished.connect(self._on_finished)
        b.log.connect(lambda m: self.statusBar().showMessage(m, 6000))
        b.iteration.connect(self._on_iteration)
        b.msgbox.connect(self._on_msgbox)
        b.hotkey.connect(self._on_hotkey)
        b.rec_count.connect(self._on_rec_count)
        b.key_captured.connect(self._on_key_captured)
        b.spy.connect(self._on_spy)
        self.tabs.currentChanged.connect(self._on_tab)
        self.tabs.tabBarDoubleClicked.connect(lambda i: self.rename_macro() if i >= 0 else self.add_macro())
        self.tabs.tabMoved.connect(self._on_tab_moved)
        self.tabs.tabCloseRequested.connect(self.delete_macro)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._tab_menu)
        self.table.doubleClicked.connect(self._on_double)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        self.filter.textChanged.connect(lambda _: self._apply_filter())
        self.repeat_spin.valueChanged.connect(self._on_repeat)
        self.speed_spin.valueChanged.connect(self._on_speed)
        self.hotkey_edit.edited.connect(self._on_macro_hotkey)

    @property
    def macro(self):
        return self.project["macros"][max(0, self.tabs.currentIndex())]

    def selected_rows(self):
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

    def current_row(self):
        rows = self.selected_rows()
        if rows:
            return rows[-1]
        idx = self.table.currentIndex()
        return idx.row() if idx.isValid() else -1

    def select_rows(self, rows, scroll=True):
        sm = self.table.selectionModel()
        sm.clearSelection()
        sel = QItemSelection()
        n = self.model.rowCount()
        for r in rows:
            if 0 <= r < n:
                sel.select(self.model.index(r, 0), self.model.index(r, self.model.columnCount() - 1))
        sm.select(sel, QItemSelectionModel.Select)
        if rows and 0 <= rows[-1] < n:
            sm.setCurrentIndex(self.model.index(rows[-1], 1), QItemSelectionModel.NoUpdate)
            if scroll:
                self.table.scrollTo(self.model.index(rows[-1], 1))

    def changed(self, structure=True):
        self.modified = True
        if structure:
            sel = self.selected_rows()
            sv = self.table.verticalScrollBar().value()
            self.model.refresh()
            self._apply_filter()
            self.select_rows(sel, scroll=False)
            self.table.verticalScrollBar().setValue(sv)
        self._update_title()
        self._update_counts()
        self._sync_actions()
        self.regen_timer.start(60)
        self.session_timer.start(1500)

    def _sync_actions(self):
        rec = self.recorder.active
        running = self.player.running
        busy = rec or running
        has_rows = bool(self.macro["actions"])
        has_sel = bool(self.selected_rows())
        key = id(self.macro)
        for a in self.edit_actions:
            a.setEnabled(not busy and has_sel)
        self.a_paste.setEnabled(not busy)
        self.a_selall.setEnabled(has_rows)
        self.a_undo.setEnabled(not busy and bool(self.undo.get(key)))
        self.a_redo.setEnabled(not busy and bool(self.redo.get(key)))
        self.a_record.setEnabled(not running)
        self.a_play.setEnabled(not busy and has_rows)
        self.a_playsel.setEnabled(not busy and has_sel)
        self.a_playonly.setEnabled(not busy and has_sel)
        self.a_pause.setEnabled(running)
        self.a_stop.setEnabled(busy)
        for a in (self.a_new, self.a_open, self.a_example, self.a_newmacro, self.a_rename, self.a_settings):
            a.setEnabled(not busy)
        self.a_delmacro.setEnabled(not busy and len(self.project["macros"]) > 1)
        self.commands.setEnabled(not busy)
        self._insert_menu.setEnabled(not busy)
        self.tabs.setEnabled(not busy)
        for w in (self.repeat_spin, self.speed_spin, self.hotkey_edit, *self.rec_boxes.values()):
            w.setEnabled(not busy)

    def _update_counts(self):
        n = len(self.macro["actions"])
        errs = self.model.info["errors"]
        text = f"{n} row{'s' if n != 1 else ''}"
        if errs:
            text += f", {len(errs)} problem{'s' if len(errs) != 1 else ''}"
        self.count_label.setText(text + "  ")
        self.count_label.setToolTip("\n".join(str(e) for e in errs))
        self.count_label.setStyleSheet(f"color: {C['rec']};" if errs else "")
        self.welcome.setVisible(n == 0)

    def _update_welcome(self):
        h = self.settings["hotkeys"]
        rec, play, stop = h.get("record") or "record", h.get("play") or "play", h.get("stop") or "stop"
        self.welcome_steps[0].setText(f"press record ({rec}), do the task in any window, press {rec} again.")
        self.welcome_steps[1].setText("or click a command on the left to add steps by hand.")
        self.welcome_steps[2].setText(f"press play ({play}) to run it. {stop} stops it at any time.")
        self.welcome_record.setText(f"record ({rec})")

    def _update_title(self):
        name = os.path.basename(self.path) if self.path else "untitled"
        state = ""
        if self.recorder.active:
            state = " (recording)"
        elif self.player.running:
            state = " (playing)"
        self.setWindowTitle(f"{'*' if self.modified else ''}{name} - {APP_NAME}{state}")

    def _set_state(self, text, mode=""):
        self.state_label.setText(text)
        self.state_label.setProperty("mode", mode)
        repolish(self.state_label)

    def _set_banner(self, mode):
        if not mode:
            self.banner.hide()
            return
        self.banner.setProperty("mode", mode)
        repolish(self.banner)
        hk = self.settings["hotkeys"]
        colors = {"rec": ("record", C["rec"]), "play": ("play", C["ok"]), "pause": ("pause", C["warn"])}
        self.banner_icon.setPixmap(icons.pixmap(*colors[mode], 16))
        self.banner_pause.setVisible(mode != "rec")
        self.banner_pause.setText(f"resume ({hk.get('pause')})" if mode == "pause" else f"pause ({hk.get('pause')})")
        stop_key = hk.get("record") if mode == "rec" else hk.get("stop")
        self.banner_stop.setText(f"stop ({stop_key})" if stop_key else "stop")
        self._update_banner(mode)
        self.banner.show()

    def _update_banner(self, mode=None):
        mode = mode or self.banner.property("mode")
        if mode == "rec":
            self.banner_label.setText(f"recording, {self.recorder.count} events so far. "
                                      "work in your other window as normal, input in this window is ignored.")
        elif self.player.running:
            row = f"row {self._row_now + 1}" if self._row_now >= 0 else "starting"
            prefix = "paused at " if mode == "pause" else "playing "
            self.banner_label.setText(f"{prefix}{row}{self._run_text}")

    def push_undo(self):
        st = self.undo.setdefault(id(self.macro), [])
        st.append(json.dumps(self.macro["actions"]))
        if len(st) > UNDO_LIMIT:
            st.pop(0)
        self.redo[id(self.macro)] = []

    def _restore(self, src, dst):
        st = src.get(id(self.macro))
        if not st or self.busy:
            return
        dst.setdefault(id(self.macro), []).append(json.dumps(self.macro["actions"]))
        self.macro["actions"][:] = json.loads(st.pop())
        self.changed()

    def do_undo(self):
        self._restore(self.undo, self.redo)

    def do_redo(self):
        self._restore(self.redo, self.undo)

    def insert_actions(self, acts, at=None, select=True):
        if at is None:
            r = self.current_row()
            at = r + 1 if r >= 0 else len(self.macro["actions"])
        self.push_undo()
        self.macro["actions"][at:at] = acts
        self.changed()
        if select:
            self.select_rows(list(range(at, at + len(acts))))

    def insert_type(self, t, params=None, wrap=False):
        if self.busy:
            return
        a = new_action(t, self.settings.get("default_delay", 10), **(params or {}))
        if "x2" in a["p"]:
            w, h = self.backend.screen_size()
            a["p"].update(x2=str(w - 1), y2=str(h - 1))
        if t not in NO_DIALOG:
            d = ActionDialog(self, a)
            if not d.exec():
                return
            a = d.action
        if t in ("loop", "if"):
            closer = new_action("endloop" if t == "loop" else "endif")
            rows = self.selected_rows()
            if rows and (wrap or len(rows) > 1):
                lo, hi = rows[0], rows[-1]
                self.push_undo()
                acts = self.macro["actions"]
                acts.insert(hi + 1, closer)
                acts.insert(lo, a)
                self.changed()
                self.select_rows([lo])
                return
            r = self.current_row()
            at = r + 1 if r >= 0 else len(self.macro["actions"])
            self.insert_actions([a, closer], at)
            self.select_rows([at])
            return
        self.insert_actions([a])
        self.table.setFocus()

    def _on_double(self, idx):
        if self.busy or (idx.column() in (3, 4, 5) and self.model.flags(idx) & Qt.ItemIsEditable):
            return
        self.edit_row(idx.row())

    def edit_current(self):
        r = self.current_row()
        if r >= 0 and not self.busy:
            self.edit_row(r)

    def edit_row(self, r):
        d = ActionDialog(self, self.macro["actions"][r])
        if d.exec() and d.action != self.macro["actions"][r]:
            self.push_undo()
            self.macro["actions"][r] = d.action
            self.changed()
            self.select_rows([r])

    def delete_rows(self):
        rows = self.selected_rows()
        if not rows or self.busy:
            return
        # a lone loop or end loop left behind just turns the macro red
        rows = with_partners(rows, self.model.info)
        self.push_undo()
        for r in reversed(rows):
            del self.macro["actions"][r]
        self.changed()
        n = len(self.macro["actions"])
        if n:
            self.select_rows([min(rows[0], n - 1)])

    def toggle_rows(self):
        acts = self.macro["actions"]
        rows = [r for r in self.selected_rows() if acts[r]["type"] not in LOCKED_ON]
        if not rows or self.busy:
            return
        self.push_undo()
        new = not acts[rows[0]]["enabled"]
        for r in rows:
            acts[r]["enabled"] = new
        self.changed()

    def move_rows(self, d):
        rows = self.selected_rows()
        acts = self.macro["actions"]
        if not rows or self.busy or (d < 0 and rows[0] == 0) or (d > 0 and rows[-1] >= len(acts) - 1):
            return
        self.push_undo()
        for r in (rows if d < 0 else reversed(rows)):
            acts[r], acts[r + d] = acts[r + d], acts[r]
        self.changed()
        self.select_rows([r + d for r in rows])

    def move_rows_to(self, rows, dest):
        acts = self.macro["actions"]
        rows = sorted(set(r for r in rows if 0 <= r < len(acts)))
        if not rows or (rows[0] <= dest <= rows[-1] + 1 and rows == list(range(rows[0], rows[-1] + 1))):
            return
        self.push_undo()
        moving = [acts[r] for r in rows]
        before = sum(1 for r in rows if r < dest)
        for r in reversed(rows):
            del acts[r]
        at = dest - before
        acts[at:at] = moving
        # the drag is still being unwound by qt, resetting the model right now crashes it
        QTimer.singleShot(0, lambda: (self.changed(), self.select_rows(list(range(at, at + len(moving))))))

    def copy_rows(self):
        rows = self.selected_rows()
        if not rows:
            return
        acts = [copy.deepcopy(self.macro["actions"][r]) for r in rows]
        md = QMimeData()
        md.setData(MIME, QByteArray(json.dumps(acts).encode()))
        code, maps, _ = ahk.generate({"macros": [dict(new_macro("selection"), actions=acts)]}, {}, self._image_size)
        lines = code.splitlines()
        body = []
        for a, b in maps[0]:
            body += [ln[4:] if ln.startswith("    ") else ln for ln in lines[a:b + 1]]
        md.setText("\n".join(body))
        QGuiApplication.clipboard().setMimeData(md)

    def cut_rows(self):
        self.copy_rows()
        self.delete_rows()

    def paste_rows(self):
        md = QGuiApplication.clipboard().mimeData()
        if self.busy or not md or not md.hasFormat(MIME):
            return
        try:
            acts = [normalize(a) for a in json.loads(bytes(md.data(MIME)).decode())]
        except (ValueError, TypeError, AttributeError):
            return
        acts = [a for a in acts if a]
        if acts:
            self.insert_actions(acts)

    def duplicate_rows(self):
        rows = self.selected_rows()
        if rows and not self.busy:
            self.insert_actions([copy.deepcopy(self.macro["actions"][r]) for r in rows], rows[-1] + 1)

    def set_tag(self, color):
        rows = self.selected_rows()
        if not rows:
            return
        self.push_undo()
        for r in rows:
            self.macro["actions"][r]["color"] = color
        self.changed()

    def _table_menu(self, pos):
        m = QMenu(self)
        m.addAction(self.a_edit)
        ins = m.addMenu("insert")
        ins.setEnabled(not self.busy)
        self._fill_insert_menu(ins)
        m.addSeparator()
        for a in (self.a_cut, self.a_copy, self.a_paste, self.a_dup, self.a_del):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_toggle, self.a_up, self.a_down, self.a_wrap_loop, self.a_wrap_if):
            m.addAction(a)
        tag = m.addMenu("row color")
        for c, n in TAG_COLORS.items():
            act = tag.addAction(n, lambda c=c: self.set_tag(c))
            if c:
                act.setIcon(QIcon(swatch_pixmap(c)))
        tag.setEnabled(bool(self.selected_rows()) and not self.busy)
        m.addSeparator()
        m.addAction(self.a_playsel)
        m.addAction(self.a_playonly)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _apply_filter(self):
        text = self.filter.text().strip().lower()
        for r, a in enumerate(self.macro["actions"]):
            hide = False
            if text:
                lab, det = self.model.data(self.model.index(r, 1)), self.model.data(self.model.index(r, 2))
                hide = text not in f"{lab} {det} {a['comment']}".lower()
            self.table.setRowHidden(r, hide)

    def _on_selection(self, *_):
        mi = self.tabs.currentIndex()
        ranges = []
        if 0 <= mi < len(self.maps):
            mp = self.maps[mi]
            ranges = [mp[r] for r in self.selected_rows() if r < len(mp)]
        self.code.sel_ranges = ranges
        self.code.apply_highlights(scroll=True)
        self._sync_actions()

    def _image_size(self, path):
        if not path:
            return None
        s = QImageReader(os.path.expanduser(path)).size()
        return (s.width(), s.height()) if s.isValid() else None

    def regen_code(self):
        if not self.a_script.isChecked():
            return
        text, maps, _ = ahk.generate(self.project, self.settings, self._image_size)
        self.maps = maps
        self.code.set_code(text)
        self._on_selection()

    def copy_code(self):
        text, _, _ = ahk.generate(self.project, self.settings, self._image_size)
        QGuiApplication.clipboard().setText(text)
        self.statusBar().showMessage("script copied", 3000)

    def toggle_script(self, on):
        self.settings["script"] = bool(on)
        self.code_panel.setVisible(on)
        self._save_settings()
        if on:
            self.regen_code()

    def _tab_title(self, m):
        return m["name"] + (f" [{m['hotkey']}]" if m.get("hotkey") else "")

    def _refresh_tabs(self, index=None):
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for m in self.project["macros"]:
            self.tabs.addTab(self._tab_title(m))
        self.tabs.blockSignals(False)
        i = 0 if index is None else max(0, min(index, len(self.project["macros"]) - 1))
        self.tabs.setCurrentIndex(i)
        self._on_tab(i)

    def _on_tab(self, i):
        if i < 0 or i >= len(self.project["macros"]):
            return
        m = self.project["macros"][i]
        self.model.set_macro(m)
        self.code.cur_range = None
        for w, v in ((self.repeat_spin, int(m.get("repeat", 1))), (self.speed_spin, float(m.get("speed", 1.0)))):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self.hotkey_edit.setText(m.get("hotkey", ""))
        self.filter.clear()
        self._update_counts()
        self.regen_code()
        if m["actions"]:
            self.select_rows([0])
        self._sync_actions()

    def _on_tab_moved(self, frm, to):
        ms = self.project["macros"]
        ms.insert(to, ms.pop(frm))
        self.changed(structure=False)
        self._update_hotkeys()

    def _tab_menu(self, pos):
        i = self.tabs.tabAt(pos)
        m = QMenu(self)
        m.addAction("new macro tab", self.add_macro)
        if i >= 0:
            m.addAction("rename...", lambda: (self.tabs.setCurrentIndex(i), self.rename_macro()))
            m.addAction("duplicate", lambda: self.duplicate_macro(i))
            m.addSeparator()
            m.addAction("delete", lambda: self.delete_macro(i)).setEnabled(len(self.project["macros"]) > 1)
        m.exec(self.tabs.mapToGlobal(pos))

    def add_macro(self):
        if self.busy:
            return
        names = {m["name"] for m in self.project["macros"]}
        n = len(self.project["macros"]) + 1
        while f"macro{n}" in names:
            n += 1
        self.project["macros"].append(new_macro(f"macro{n}"))
        self._refresh_tabs(len(self.project["macros"]) - 1)
        self.changed(structure=False)

    def duplicate_macro(self, i):
        if self.busy:
            return
        m = copy.deepcopy(self.project["macros"][i])
        m["name"] += "_copy"
        m["hotkey"] = ""
        self.project["macros"].insert(i + 1, m)
        self._refresh_tabs(i + 1)
        self.changed(structure=False)

    def delete_macro(self, i):
        if len(self.project["macros"]) <= 1 or self.busy:
            return
        m = self.project["macros"][i]
        if self.settings.get("confirm_delete", True) and m["actions"]:
            n = len(m["actions"])
            choice = ask(self, APP_NAME, f"delete {m['name']} and its {n} row{'s' if n != 1 else ''}?",
                         (("delete", QMessageBox.DestructiveRole, "yes"), ("cancel", QMessageBox.RejectRole, "no")))
            if choice != "yes":
                return
        self.undo.pop(id(m), None)
        self.redo.pop(id(m), None)
        del self.project["macros"][i]
        self._refresh_tabs(max(0, i - 1))
        self.changed(structure=False)
        self._update_hotkeys()

    def rename_macro(self):
        if self.busy:
            return
        m = self.macro
        d = QInputDialog(self)
        d.setWindowTitle("rename macro")
        d.setLabelText("name")
        d.setTextValue(m["name"])
        d.setOkButtonText("ok")
        d.setCancelButtonText("cancel")
        if d.exec() and d.textValue().strip():
            m["name"] = d.textValue().strip()
            self.tabs.setTabText(self.tabs.currentIndex(), self._tab_title(m))
            self.changed(structure=False)

    def _on_repeat(self, v):
        self.macro["repeat"] = v
        self.changed(structure=False)

    def _on_speed(self, v):
        self.macro["speed"] = v
        self.changed(structure=False)

    def _set_rec_option(self, key, on):
        self.settings[key] = bool(on)
        self._save_settings()

    def _hotkey_valid(self, spec):
        return self.backend.keymap.knows(parse_hotkey(spec)[1])

    def _macro_hotkey_problem(self, spec, macro):
        if not spec:
            return None
        if not self._hotkey_valid(spec):
            return f"{spec} is not a known key."
        taken = [v for v in self.settings["hotkeys"].values() if v]
        taken += [m["hotkey"] for m in self.project["macros"] if m is not macro and m.get("hotkey")]
        return f"{spec} is already in use." if spec in taken else None

    def hotkey_problems(self, specs):
        seen = {}
        macro_keys = {m["hotkey"] for m in self.project["macros"] if m.get("hotkey")}
        for k, spec in specs.items():
            if not spec:
                continue
            if not self._hotkey_valid(spec):
                return f"{spec} is not a known key."
            if spec in seen:
                return f"{k} and {seen[spec]} both use {spec}."
            if spec in macro_keys:
                return f"{spec} is already used by a macro."
            seen[spec] = k
        return None

    def _on_macro_hotkey(self):
        m = self.macro
        spec = self.hotkey_edit.text()
        if spec == m.get("hotkey", ""):
            return
        problem = self._macro_hotkey_problem(spec, m)
        if problem:
            self.hotkey_edit.setText(m.get("hotkey", ""))
            self.statusBar().showMessage(problem, 6000)
            return
        m["hotkey"] = spec
        self.tabs.setTabText(self.tabs.currentIndex(), self._tab_title(m))
        self.changed(structure=False)
        self._update_hotkeys()

    def _update_hotkeys(self):
        hk = [(self.settings["hotkeys"].get(k, ""), k) for k in ("record", "play", "stop", "pause")]
        hk = [(s, k) for s, k in hk if s]
        hk += [(m["hotkey"], f"macro:{i}") for i, m in enumerate(self.project["macros"]) if m.get("hotkey")]
        self._hotkeys = hk
        self.backend.block_hotkeys([spec for spec, _a in hk] if self.settings.get("block_hotkeys", True) else [])
        h = self.settings["hotkeys"]
        for a, k in ((self.a_record, "record"), (self.a_play, "play"), (self.a_stop, "stop"), (self.a_pause, "pause")):
            a.setToolTip(f"{k} ({h.get(k) or 'no hotkey'})")
        self.hint_label.setText("   ".join(f"{h[k]} {k}" for k in ("record", "play", "pause", "stop") if h.get(k)))
        self._update_welcome()

    def capture_next_key(self, cb, with_mods=False, buttons=False):
        self.cancel_capture()
        self._capture = (cb, with_mods, buttons)
        QApplication.instance().installEventFilter(self._swallower)
        # without this a missing input permission would leave the keyboard dead in our windows
        self.capture_timer.start(CAPTURE_TIMEOUT_MS)

    def cancel_capture(self):
        cap, self._capture = self._capture, None
        if cap is None:
            return
        self.capture_timer.stop()
        QApplication.instance().removeEventFilter(self._swallower)
        cap[0](None, None)

    def _on_key_captured(self, name, payload):
        cb, mods = payload
        self.capture_timer.stop()
        QTimer.singleShot(250, lambda: QApplication.instance().removeEventFilter(self._swallower))
        cb(name, mods)

    def _on_input(self, ev):
        k = ev["kind"]
        if k in ("key", "button"):
            name = ev["name"]
            if ev["down"] and not ev.get("repeat"):
                if self._capture is not None:
                    cb, with_mods, buttons = self._capture
                    if (with_mods and name in MODIFIERS) or (k == "button" and not buttons):
                        return
                    self._capture = None
                    mods = self.backend.held_mods() - ({MODIFIERS[name]} if name in MODIFIERS else set())
                    self._swallow.add(name)
                    self.bridge.key_captured.emit(name, (cb, mods))
                    return
                if k == "key":
                    mods = self.backend.held_mods() - ({MODIFIERS[name]} if name in MODIFIERS else set())
                    for spec, action in self._hotkeys:
                        if hotkey_matches(spec, name, mods):
                            self._swallow.add(name)
                            self.bridge.hotkey.emit(action)
                            return
            elif name in self._swallow:
                if not ev["down"]:
                    self._swallow.discard(name)
                return
        if self.recorder.active and self.recorder.feed(ev):
            self.bridge.rec_count.emit(self.recorder.count)

    def _on_hotkey(self, action):
        if action not in ("stop", "pause") and QApplication.activeModalWidget() is not None:
            return
        if action == "record":
            self.toggle_record()
        elif action == "play":
            self.play()
        elif action == "stop":
            self.stop_all()
        elif action == "pause":
            self.toggle_pause()
        elif action.startswith("macro:"):
            i = int(action.split(":")[1])
            if not self.busy and i < len(self.project["macros"]):
                if self.tabs.currentIndex() != i:
                    self.tabs.setCurrentIndex(i)
                self.play()

    def toggle_record(self):
        if self.player.running:
            return
        if self.recorder.active:
            acts = self.recorder.stop(held=set(self.backend.pressed_names))
            self.rec_btn.setProperty("recording", False)
            repolish(self.rec_btn)
            self.a_record.setText("record")
            self._set_banner("")
            self._set_state(f"recorded {len(acts)} row{'s' if len(acts) != 1 else ''}")
            self.bridge.rec_count.emit(0)
            if acts:
                self.insert_actions(acts)
            self._update_title()
            self._sync_actions()
            return
        self.recorder.start(self.settings)
        self.rec_btn.setProperty("recording", True)
        repolish(self.rec_btn)
        self.a_record.setText("stop rec")
        self._set_banner("rec")
        self._set_state("recording", "rec")
        self._update_title()
        self._sync_actions()

    def _on_rec_count(self, n):
        if self.recorder.active:
            self._update_banner("rec")

    def play(self, from_selected=False, only_selected=False):
        if self.busy:
            return
        m = self.macro
        if not m["actions"]:
            self.statusBar().showMessage("nothing to play yet", 3000)
            return
        start, only, rep = 0, None, None
        rows = self.selected_rows()
        if from_selected and rows:
            start, rep = rows[0], 1
        if only_selected and rows:
            only, rep = with_partners(rows, self.model.info), 1
        try:
            self.player.start(copy.deepcopy(m), self.tabs.currentIndex(), start, only, rep)
        except MacroError as e:
            self._set_state(f"cannot play: {e}", "bad")
            if e.row is not None:
                self.select_rows([e.row])
            return
        self._row_now = -1
        self._run_text = ""
        self.step_timer.start()
        self._set_state("playing", "play")
        self._set_banner("play")
        self._update_title()
        self._sync_actions()

    def toggle_pause(self):
        if not self.player.running:
            return
        p = self.player.toggle_pause()
        self.a_pause.setText("resume" if p else "pause")
        self._set_state("paused" if p else "playing", "pause" if p else "play")
        self._set_banner("pause" if p else "play")

    def stop_all(self):
        if self.recorder.active:
            self.toggle_record()
        if self.player.running:
            self.player.stop()

    def _cb_step(self, row):
        self._step_value = row

    def _apply_step(self):
        v = self._step_value
        if v is None:
            return
        self._step_value = None
        if v >= 0:
            self._row_now = v
            self._update_banner()
        if self.player.macro_index != self.tabs.currentIndex():
            return
        self.model.set_current(v)
        mi = self.tabs.currentIndex()
        if v >= 0 and mi < len(self.maps) and v < len(self.maps[mi]):
            self.code.cur_range = self.maps[mi][v]
            follow = self.settings.get("follow", True)
            if follow:
                self.table.scrollTo(self.model.index(v, 1))
            self.code.apply_highlights(scroll=follow, focus=self.code.cur_range)
        elif v >= 0 and self.settings.get("follow", True):
            self.table.scrollTo(self.model.index(v, 1))

    def _cb_msgbox(self, title, text):
        ev = threading.Event()
        self.bridge.msgbox.emit(title, text, ev)
        while not ev.wait(0.05):
            if self.player.stopping:
                return

    def _on_msgbox(self, title, text, ev):
        box = QMessageBox(QMessageBox.NoIcon, title or APP_NAME, text, QMessageBox.NoButton, self)
        box.addButton("ok", QMessageBox.AcceptRole)
        self._msgbox = box
        box.exec()
        self._msgbox = None
        ev.set()

    def _on_iteration(self, n, total):
        if total == 1:
            self._run_text = ""
        else:
            self._run_text = f", run {n} of {total}" if total else f", run {n}"
        if self.player.running:
            self._update_banner()

    def _on_finished(self, msg):
        self.player.wait(1)
        if self._msgbox is not None:
            self._msgbox.done(0)
        self.step_timer.stop()
        self._step_value = None
        self.model.set_current(-1)
        self.code.cur_range = None
        self.code.apply_highlights(scroll=False)
        self.a_pause.setText("pause")
        self._set_banner("")
        self._set_state(msg, "bad" if msg.startswith("error") else "")
        self._update_title()
        self._sync_actions()

    def _spy_loop(self):
        last = None
        while not self._quit.wait(0.25):
            try:
                x, y = self.backend.cursor_pos()
                hx = title = ""
                if self.settings.get("spy"):
                    hx = hex_color(self.backend.pixel(x, y))
                    w = self.backend.active_window()
                    title = f"{w['title'][:40]} [{w['class']}]" if w else ""
            except (OSError, RuntimeError, ValueError):
                continue
            state = (x, y, hx, title)
            if state != last:
                last = state
                self.bridge.spy.emit(*state)

    def _on_spy(self, x, y, hx, title):
        txt = f"x {x}  y {y}"
        if hx:
            txt += (f"   <span style='background:#{hx}'>&nbsp;&nbsp;&nbsp;&nbsp;</span> #{hx}"
                    f"   <span style='color:{C['faint']}'>{title.replace('<', '&lt;')}</span>")
        self.spy_label.setText(txt)

    def toggle_spy(self, on):
        self.settings["spy"] = bool(on)
        self._save_settings()

    def pick_color_tool(self):
        got = self.picker.color()
        if got:
            pt, rgb = got
            hx = hex_color(rgb)
            QGuiApplication.clipboard().setText(hx)
            self.statusBar().showMessage(f"#{hx} at {pt[0]}, {pt[1]} copied", 6000)

    def pick_point_tool(self):
        pt = self.picker.point()
        if pt:
            QGuiApplication.clipboard().setText(f"{pt[0]}, {pt[1]}")
            self.statusBar().showMessage(f"{pt[0]}, {pt[1]} copied", 6000)

    def open_settings(self):
        d = SettingsDialog(self, self.settings)
        if d.exec():
            self.settings = d.values()
            self._save_settings()
            self._update_hotkeys()
            self.regen_code()

    def show_help(self):
        HelpDialog(self, self.settings["hotkeys"]).exec()

    def show_about(self):
        message(self, f"about {APP_NAME}", f"{APP_NAME} {__version__}\n\nrecord, edit and replay macros.\nmit license.")

    def _reset_history(self):
        self.modified = False
        self.undo.clear()
        self.redo.clear()

    def new_project(self):
        if self.busy or not self._confirm_discard():
            return
        self.project = {"macros": [new_macro()]}
        self.path = ""
        self._reset_history()
        self._refresh_tabs(0)
        self._update_hotkeys()
        self._update_title()
        self._save_session()

    def _confirm_discard(self):
        if not self.modified or not any(m["actions"] for m in self.project["macros"]):
            return True
        r = ask(self, APP_NAME, "save changes to the current project?",
                (("save", QMessageBox.AcceptRole, "save"), ("don't save", QMessageBox.DestructiveRole, "discard"),
                 ("cancel", QMessageBox.RejectRole, "cancel")))
        if r == "save":
            return self.save_project()
        return r == "discard"

    def _load_project_file(self, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("macros"), list):
            raise ValueError(f"this is not a {APP_NAME} project")
        macros = [normalize_macro(m, f"macro{i + 1}") for i, m in enumerate(data["macros"])]
        return {"macros": macros or [new_macro()]}

    def _open_path(self, p, remember=True):
        try:
            self.project = self._load_project_file(p)
        except (OSError, ValueError, TypeError, AttributeError) as e:
            message(self, APP_NAME, f"could not open {p}:\n{e}", QMessageBox.Critical)
            return False
        self.path = p if remember else ""
        self._reset_history()
        if remember:
            self.settings["last_path"] = p
            self._save_settings()
        self._refresh_tabs(0)
        self._update_hotkeys()
        self._update_title()
        return True

    def open_project(self):
        if self.busy or not self._confirm_discard():
            return
        p, _ = QFileDialog.getOpenFileName(self, "open project",
                                           os.path.dirname(self.path or self.settings.get("last_path", "")) or os.path.expanduser("~"),
                                           "reprise projects (*.reprise *.json);;all files (*)")
        if p:
            self._open_path(p)

    def open_example(self):
        if not self.busy and self._confirm_discard():
            self._open_path(EXAMPLE_PATH, remember=False)

    def _project_json(self):
        return json.dumps({"app": APP_NAME, "version": 1, "macros": self.project["macros"]}, indent=1)

    def save_project(self):
        if not self.path:
            return self.save_project_as()
        try:
            write_atomic(self.path, self._project_json())
        except OSError as e:
            message(self, APP_NAME, f"save failed:\n{e}", QMessageBox.Critical)
            return False
        self.modified = False
        self._update_title()
        self.statusBar().showMessage(f"saved {self.path}", 3000)
        return True

    def save_project_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "save project", self.path or os.path.join(os.path.expanduser("~"), "macro.reprise"),
                                           "reprise projects (*.reprise)")
        if not p:
            return False
        if not p.endswith((".reprise", ".json")):
            p += ".reprise"
        self.path = p
        self.settings["last_path"] = p
        self._save_settings()
        return self.save_project()

    def export_ahk(self):
        if self.model.info["errors"]:
            choice = ask(self, APP_NAME, f"this macro has a problem and the script may not run:\n{self.model.info['errors'][0]}",
                         (("export anyway", QMessageBox.AcceptRole, "yes"), ("cancel", QMessageBox.RejectRole, "no")))
            if choice != "yes":
                return
        base = os.path.splitext(self.path)[0] + ".ahk" if self.path else os.path.join(os.path.expanduser("~"), "macro.ahk")
        p, _ = QFileDialog.getSaveFileName(self, "export autohotkey script", base, "autohotkey scripts (*.ahk)")
        if not p:
            return
        if not p.lower().endswith(".ahk"):
            p += ".ahk"
        text, _, images = ahk.generate(self.project, self.settings, self._image_size)
        try:
            with open(p, "w", newline="\r\n", encoding="utf-8-sig") as f:
                f.write(text)
            d = os.path.dirname(p)
            for src, name in images.items():
                src = os.path.expanduser(src)
                dst = os.path.join(d, name)
                if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
                    shutil.copy2(src, dst)
        except OSError as e:
            message(self, APP_NAME, f"export failed:\n{e}", QMessageBox.Critical)
            return
        extra = f" and {len(images)} image{'s' if len(images) != 1 else ''}" if images else ""
        self.statusBar().showMessage(f"exported {p}{extra}", 5000)

    def _load_settings(self):
        s = copy.deepcopy(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            hk = dict(s["hotkeys"])
            hk.update({k: str(v).lower() for k, v in data.get("hotkeys", {}).items()})
            s.update(data)
            s["hotkeys"] = hk
        except (OSError, ValueError, AttributeError):
            pass
        return s

    def _save_settings(self):
        self.settings["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self.settings["splitter"] = self.split.sizes() if hasattr(self, "split") else None
        try:
            write_atomic(SETTINGS_PATH, json.dumps(self.settings, indent=1))
        except OSError:
            pass

    def _save_session(self):
        try:
            # recordings can contain anything that was typed, passwords included
            write_atomic(SESSION_PATH, json.dumps({"path": self.path, "modified": self.modified, "tab": self.tabs.currentIndex(),
                                                   "macros": self.project["macros"]}), private=True)
        except OSError:
            pass

    def _load_session(self):
        tab = 0
        try:
            proj = self._load_project_file(SESSION_PATH)
            with open(SESSION_PATH, encoding="utf-8") as f:
                meta = json.load(f)
            self.project = proj
            self.path = str(meta.get("path", ""))
            self.modified = bool(meta.get("modified"))
            tab = int(meta.get("tab", 0))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        g = self.settings.get("geometry")
        if g:
            self.restoreGeometry(QByteArray.fromBase64(g.encode()))
        if self.settings.get("splitter"):
            self.split.setSizes(self.settings["splitter"])
        self._refresh_tabs(tab)
        self._update_title()

    def closeEvent(self, e):
        self.cancel_capture()
        self._quit.set()
        self.player.stop()
        self.player.wait(2)
        if self.recorder.active:
            self.recorder.stop()
        self._save_session()
        self._save_settings()
        self.backend.shutdown()
        # qt segfaults on exit if it still owns mime data set from python
        board = QGuiApplication.clipboard()
        held = board.mimeData()
        if held is not None and held.hasFormat(MIME):
            board.setText(held.text())
        e.accept()
