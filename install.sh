#!/bin/sh
# adds a launcher and menu entry for the current user, nothing outside ~/.local
set -e
here=$(cd "$(dirname "$0")" && pwd)
bin="$HOME/.local/bin"
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor"

mkdir -p "$bin" "$apps" "$icons/256x256/apps" "$icons/scalable/apps"
cat > "$bin/reprise" <<LAUNCH
#!/bin/sh
PYTHONPATH="$here" exec python3 -m reprise "\$@"
LAUNCH
chmod +x "$bin/reprise"
cp "$here/reprise/assets/icon-256.png" "$icons/256x256/apps/reprise.png"
cp "$here/reprise/assets/icon.svg" "$icons/scalable/apps/reprise.svg"
cat > "$apps/reprise.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=reprise macro creator
Comment=record, edit and replay macros
Exec=$bin/reprise %f
Icon=reprise
Terminal=false
Categories=Utility;Development;
DESK
echo "installed. run reprise, or find reprise macro creator in your app menu."
