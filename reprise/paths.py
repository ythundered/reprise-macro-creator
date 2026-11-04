import os
import shutil
import sys

FROZEN = getattr(sys, "frozen", False)
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

if sys.platform == "win32":
    _base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "reprise")
    CONFIG_DIR = _base
    DATA_DIR = _base
else:
    CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "reprise")
    DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "reprise")

SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
SESSION_PATH = os.path.join(CONFIG_DIR, "session.reprise")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
EXAMPLE_PATH = os.path.join(ASSETS, "example.reprise")
ICON_PATH = os.path.join(ASSETS, "icon-256.png")


def clean_env():
    # the one-file build points LD_LIBRARY_PATH at its own libs, system programs must not see that
    env = dict(os.environ)
    if FROZEN and sys.platform != "win32":
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        env.pop("LD_LIBRARY_PATH", None)
        if orig:
            env["LD_LIBRARY_PATH"] = orig
    return env


def find_tool(name):
    found = shutil.which(name)
    if found:
        return found, clean_env()
    if FROZEN:
        bundled = os.path.join(sys._MEIPASS, "tools", name)
        if os.path.exists(bundled):
            return bundled, dict(os.environ)
    return None, None


def asset(name):
    return os.path.join(ASSETS, name).replace("\\", "/")


def write_atomic(path, text, private=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    if private and sys.platform != "win32":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
