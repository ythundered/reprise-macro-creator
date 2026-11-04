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

# qt ships a lot this app never loads
DROP = ("qt6quick", "qt6qml", "qt6network", "qt6pdf", "qt6virtualkeyboard", "qvnc", "qeglfs", "qlinuxfb", "qminimal",
        "qvkkhrdisplay", "qdirect2d", "eglfs", "opengl32sw", "/translations/", "\\translations\\", "virtualkeyboard",
        "networkinformation", "/tls/", "\\tls\\", "qgtk3", "libgtk-3", "libgdk-3", "qpdf", "qicns", "qtga", "qtiff", "qwbmp", "qwebp")


def keep(entry):
    low = entry[0].lower()
    return not any(d in low for d in DROP)


a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]
for size, dest in sorted(((os.path.getsize(b[1]), b[0]) for b in a.binaries), reverse=True)[:25]:
    print(f"{size / 1e6:7.1f} MB  {dest}")

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
