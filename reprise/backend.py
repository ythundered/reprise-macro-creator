import sys


def create():
    if sys.platform == "win32":
        from .backend_win import Backend
    else:
        from .backend_linux import Backend
    return Backend()
