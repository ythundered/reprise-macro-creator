import functools

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

GLYPHS = {
    "new": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    "open": '<path d="M3 19V6h6l2 2h10v3"/><path d="M3 19l3-8h17l-3 8z"/>',
    "save": '<path d="M4 4h13l3 3v13H4z"/><path d="M8 4v5h7V4"/><path d="M7 20v-7h10v7"/>',
    "export": '<path d="M12 15V4"/><path d="M8 8l4-4 4 4"/><path d="M5 14v6h14v-6"/>',
    "undo": '<path d="M9 7H5V3"/><path d="M5 7c4-4 13-3 14 5 .5 4-3 8-7 8"/>',
    "redo": '<path d="M15 7h4V3"/><path d="M19 7c-4-4-13-3-14 5-.5 4 3 8 7 8"/>',
    "record": '<circle cx="12" cy="12" r="7" fill="FILL"/>',
    "play": '<path d="M7 4l13 8-13 8z" fill="FILL"/>',
    "pause": '<path d="M8 5v14M16 5v14" stroke-width="4"/>',
    "halt": '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="FILL"/>',
    "playfrom": '<path d="M5 4v16"/><path d="M10 5l10 7-10 7z" fill="FILL"/>',
    "playonly": '<path d="M9 6l10 6-10 6z" fill="FILL"/><path d="M4 6v12"/>',
    "script": '<path d="M9 7l-5 5 5 5"/><path d="M15 7l5 5-5 5"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.8 2.1c-.8.5-1.3 1-1.3 2"/><path d="M12 17v.01"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="M4 20l1-4L16 5l3 3L8 19z"/><path d="M14 7l3 3"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M5 16H4V4h12v1"/>',
    "delete": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    "up": '<path d="M12 20V5"/><path d="M6 11l6-6 6 6"/>',
    "down": '<path d="M12 4v15"/><path d="M6 13l6 6 6-6"/>',
    "toggle": '<rect x="3" y="7" width="18" height="10" rx="5"/><circle cx="16" cy="12" r="2.5" fill="FILL"/>',
    "wraploop": '<path d="M17 3l3 3-3 3"/><path d="M20 6H8a4 4 0 0 0-4 4v1"/><path d="M7 21l-3-3 3-3"/><path d="M4 18h12a4 4 0 0 0 4-4v-1"/>',
    "wrapif": '<path d="M12 3l8 9-8 9-8-9z"/>',
    "click": '<path d="M9 9l11 4-5 2-2 5z" fill="FILL"/><path d="M5 5l2 2M9 3v3M3 9h3"/>',
    "mousemove": '<path d="M12 3v18M3 12h18"/><path d="M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/>',
    "wheel": '<rect x="7" y="3" width="10" height="18" rx="5"/><path d="M12 7v4"/>',
    "key": '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10v.01M11 10v.01M15 10v.01M8 14h8"/>',
    "text": '<path d="M5 6V4h14v2"/><path d="M12 4v16"/><path d="M9 20h6"/>',
    "keywait": '<rect x="3" y="9" width="18" height="11" rx="2"/><path d="M8 15h8"/><path d="M12 2v4M10 4h4"/>',
    "sleep": '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l3 2"/><path d="M9 2h6"/>',
    "loop": '<path d="M17 3l3 3-3 3"/><path d="M20 6H8a4 4 0 0 0-4 4v1"/><path d="M7 21l-3-3 3-3"/><path d="M4 18h12a4 4 0 0 0 4-4v-1"/>',
    "endloop": '<path d="M5 5v14h14"/><path d="M9 15V9"/>',
    "if": '<path d="M12 3l8 9-8 9-8-9z"/>',
    "else": '<path d="M6 4v8h12"/><path d="M14 8l4 4-4 4"/>',
    "endif": '<path d="M5 5v14h14"/><path d="M9 15V9"/>',
    "break": '<path d="M4 12h6"/><path d="M14 6l4 6-4 6"/><path d="M20 5v14"/>',
    "continue": '<path d="M4 12h13"/><path d="M12 7l5 5-5 5"/><path d="M20 5v14"/>',
    "label": '<path d="M4 5h10l6 7-6 7H4z"/><path d="M9 12v.01"/>',
    "goto": '<path d="M5 19V9a4 4 0 0 1 4-4h11"/><path d="M16 1l4 4-4 4"/>',
    "stop": '<path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z"/><path d="M9 12h6"/>',
    "pixelsearch": '<rect x="3" y="3" width="8" height="8" fill="FILL"/><circle cx="15" cy="15" r="5"/><path d="M19 19l3 3"/>',
    "imagesearch": '<path d="M3 13V3h14v6"/><path d="M3 11l4-4 4 4"/><circle cx="15" cy="15" r="5"/><path d="M19 19l3 3"/>',
    "pixelgetcolor": '<path d="M14 4l6 6-3 1-8 8-4 1 1-4 8-8z"/>',
    "winactivate": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M6 6.5v.01"/>',
    "winwait": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M12 12v3l2 1.5"/>',
    "winclose": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M9.5 12l5 5M14.5 12l-5 5"/>',
    "wingettitle": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M7 13h10M7 16h6"/>',
    "setvar": '<path d="M8 4c-3 0-3 2-3 4s0 4-2 4c2 0 2 2 2 4s0 4 3 4"/><path d="M16 4c3 0 3 2 3 4s0 4 2 4c-2 0-2 2-2 4s0 4-3 4"/>',
    "run": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3"/><path d="M12 15h5"/>',
    "msgbox": '<path d="M3 4h18v13H10l-5 4v-4H3z"/>',
    "comment": '<path d="M5 3h14v18H5z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
}


@functools.lru_cache(maxsize=512)
def pixmap(name, color="#dcdee4", size=20, ratio=2):
    body = GLYPHS[name].replace("FILL", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size * ratio, size * ratio))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


@functools.lru_cache(maxsize=256)
def icon(name, color="#dcdee4", size=20):
    ic = QIcon(pixmap(name, color, size))
    ic.addPixmap(pixmap(name, "#62666f", size), QIcon.Disabled)
    return ic
