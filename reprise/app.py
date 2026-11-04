import json
import os
import shutil
import signal
import subprocess
import sys
import traceback

from PySide6.QtCore import QLibraryInfo, QTimer
from PySide6.QtGui import QColor, QIcon, QImageReader, QPalette
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .paths import FROZEN, ICON_PATH, asset, find_tool
from .theme import C
from .window import MainWindow


def build_palette():
    pal = QPalette()
    for role, col in ((QPalette.Window, C["bg"]), (QPalette.WindowText, C["text"]), (QPalette.Base, C["panel"]),
                      (QPalette.AlternateBase, C["row_alt"]), (QPalette.Text, C["text"]), (QPalette.Button, C["panel3"]),
                      (QPalette.ButtonText, C["text"]), (QPalette.Highlight, C["accent_dim"]),
                      (QPalette.HighlightedText, C["text"]), (QPalette.ToolTipBase, C["panel3"]),
                      (QPalette.ToolTipText, C["text"]), (QPalette.PlaceholderText, C["faint"]),
                      (QPalette.Link, C["accent"])):
        pal.setColor(role, QColor(col))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(C["faint"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(C["faint"]))
    return pal


def add_to_app_menu():
    # the linux build is one file you can put anywhere, so keep the menu entry pointing at it
    data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    entry = os.path.join(data, "applications", "reprise-macro-creator.desktop")
    icon = os.path.join(data, "icons", "hicolor", "256x256", "apps", "reprise-macro-creator.png")
    text = ("[Desktop Entry]\nType=Application\n"
            f"Name={APP_NAME}\nComment=record, edit and replay macros\n"
            f'Exec="{sys.executable}" %f\nIcon=reprise-macro-creator\nTerminal=false\nCategories=Utility;Development;\n')
    try:
        with open(entry, encoding="utf-8") as f:
            if f.read() == text:
                return
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(entry), exist_ok=True)
        os.makedirs(os.path.dirname(icon), exist_ok=True)
        shutil.copyfile(asset("icon-256.png"), icon)
        with open(entry, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def smoke_report(window):
    plugins = QLibraryInfo.path(QLibraryInfo.PluginsPath)
    platforms = sorted(os.listdir(os.path.join(plugins, "platforms"))) if os.path.isdir(os.path.join(plugins, "platforms")) else []
    report = {
        "version": __version__, "frozen": FROZEN, "backend": window.backend.name, "platforms": platforms,
        "svg": b"svg" in [bytes(f) for f in QImageReader.supportedImageFormats()],
        "icon": not QIcon(ICON_PATH).isNull(), "screen": window.backend.screen_size(),
        "problems": window.backend.problems(), "title": window.windowTitle(), "tools": {},
    }
    if sys.platform != "win32":
        for name in ("grim", "slurp"):
            path, env = find_tool(name)
            code = subprocess.run([path, "-h"], env=env, capture_output=True).returncode if path else None
            report["tools"][name] = {"path": path, "exit": code}
    return report


def main():
    # a windowed exe has no console and these are None
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    args = sys.argv[1:]
    smoke_path = None
    if "--smoke-test" in args:
        at = args.index("--smoke-test")
        smoke_path = args[at + 1]
        del args[at:at + 2]
    if sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")
        if FROZEN and smoke_path is None:
            add_to_app_menu()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("reprise")
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    f = app.font()
    f.setPointSize(10)
    app.setFont(f)
    w = MainWindow(open_path=args[0] if args else None, quiet=smoke_path is not None)
    w.show()
    if smoke_path:
        def finish():
            with open(smoke_path, "w", encoding="utf-8") as f:
                json.dump(smoke_report(w), f, indent=1)
            w.close()
        QTimer.singleShot(1500, finish)

    def report(kind, value, tb):
        traceback.print_exception(kind, value, tb)
        w.statusBar().showMessage(f"internal error: {value}", 10000)
    sys.excepthook = report
    signal.signal(signal.SIGINT, lambda *_: w.close())
    signal.signal(signal.SIGTERM, lambda *_: w.close())
    # python only runs signal handlers between bytecodes, qt's loop needs waking for that
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(300)
    sys.exit(app.exec())
