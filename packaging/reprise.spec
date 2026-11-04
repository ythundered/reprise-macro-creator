import os
import shutil
import sys

root = os.path.abspath(os.path.join(SPECPATH, ".."))
linux = sys.platform.startswith("linux")
name = "reprise-macro-creator"

# grim and slurp go in too, pyinstaller pulls in the libraries they need
binaries = []
if linux:
    for tool in ("grim", "slurp"):
        binaries.append((shutil.which(tool), "tools"))

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[root],
    binaries=binaries,
    datas=[(os.path.join(root, "reprise", "assets"), "reprise/assets")],
    hiddenimports=["reprise.backend_linux"] if linux else ["reprise.backend_win"],
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork",
              "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.Qt3DCore"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name=name,
    console=False,
    upx=False,
    icon=None if linux else os.path.join(root, "reprise", "assets", "icon.ico"),
)
