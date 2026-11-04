import os
import signal
import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from . import APP_NAME
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


def main():
    if sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("reprise")
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    f = app.font()
    f.setPointSize(10)
    app.setFont(f)
    w = MainWindow(open_path=sys.argv[1] if len(sys.argv) > 1 else None)
    w.show()

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
