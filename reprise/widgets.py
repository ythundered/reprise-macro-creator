import json
import re

from PySide6.QtCore import QAbstractTableModel, QByteArray, QMimeData, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTextEdit, QWidget

from . import icons
from .model import CATEGORY_COLORS, LOCKED_ON, TYPES, UNTIMED, analyze, describe, new_macro
from .theme import C

MIME = "application/x-reprise-actions"
INDENT_ROLE = Qt.UserRole + 1
TYPE_ROLE = Qt.UserRole + 2
MAX_HIGHLIGHT_LINES = 500


class AhkHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)

        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.DemiBold)
            if italic:
                f.setFontItalic(True)
            return f
        cmds = ("click|mousemove|send|sendraw|sendinput|sendevent|sleep|loop|while|until|if|else|break|continue|return|"
                "goto|gosub|pixelsearch|pixelgetcolor|imagesearch|winactivate|winwaitactive|winclose|wingettitle|run|"
                "runwait|msgbox|keywait|random|setkeydelay|setmousedelay|setbatchlines|settitlematchmode|coordmode|"
                "sendmode|setworkingdir|setdefaultmousespeed|reload|pause|exitapp")
        self.rules = [
            (re.compile(r"^\s*#\w+"), fmt("#c586c0")),
            (re.compile(rf"\b({cmds})\b", re.I), fmt("#6cb0ff", True)),
            (re.compile(r"\b(winactive|winexist|getkeystate|round|floor|ceil|abs|mod|min|max|strlen|substr|instr|strreplace)(?=\()", re.I), fmt("#dcdcaa")),
            (re.compile(r"\b(a_\w+|errorlevel|foundx|foundy|waitstart|sleeptime)\b", re.I), fmt("#9cdcfe")),
            (re.compile(r"\b(0x[0-9a-f]+|\d+)\b", re.I), fmt("#b5cea8")),
            (re.compile(r"%\w+%"), fmt("#f58ac0")),
            (re.compile(r"\{[^}\s]+(\s+(down|up|\d+))?\}", re.I), fmt("#d7ba7d")),
            (re.compile(r"\b(left|right|middle|x1|x2|down|up|rel|fast|rgb|screen|input|mouse|pixel)\b", re.I), fmt("#c8a2f0")),
            (re.compile(r"\"(?:[^\"]|\"\")*\""), fmt("#ce9178")),
            (re.compile(r"^\s*[^\s:;,]+::"), fmt("#e5c246", True)),
            (re.compile(r"^\s*\w+:\s*$"), fmt("#e5c246", True)),
            (re.compile(r"[{}]"), fmt("#808590")),
        ]
        self.comment = fmt("#6a9955", italic=True)
        self.disabled = fmt("#555963", italic=True)
        self.comment_rx = re.compile(r"(^|\s);.*$")

    def highlightBlock(self, text):
        if text.startswith(";"):
            self.setFormat(0, len(text), self.disabled)
            return
        for rx, f in self.rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)
        m = self.comment_rx.search(text)
        if m:
            self.setFormat(m.start(), len(text) - m.start(), self.comment)


class LineNumbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, e):
        self.editor.paint_gutter(e)


class CodeView(QPlainTextEdit):
    def __init__(self, mono):
        super().__init__()
        self.setObjectName("code")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        f = QFont(mono)
        f.setPointSize(10)
        f.setStyleHint(QFont.Monospace)
        self.setFont(f)
        self.gutter = LineNumbers(self)
        self.blockCountChanged.connect(self._update_width)
        self.updateRequest.connect(self._update_gutter)
        self._update_width()
        self.hl = AhkHighlighter(self.document())
        self.sel_ranges = []
        self.cur_range = None
        self._hot = set()
        self._text = ""

    def gutter_width(self):
        digits = max(3, len(str(self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, e):
        p = QPainter(self.gutter)
        p.fillRect(e.rect(), QColor(C["bg"]))
        block = self.firstVisibleBlock()
        n = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = range(self.cur_range[0], self.cur_range[1] + 1) if self.cur_range else ()
        h = self.fontMetrics().height()
        w = self.gutter.width() - 8
        while block.isValid() and top <= e.rect().bottom():
            if block.isVisible() and bottom >= e.rect().top():
                p.setPen(QColor(C["accent"] if n in cur else (C["text"] if n in self._hot else C["faint"])))
                p.drawText(0, top, w, h, Qt.AlignRight, str(n + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            n += 1

    def set_code(self, text):
        if text == self._text:
            return
        self._text = text
        v = self.verticalScrollBar().value()
        h = self.horizontalScrollBar().value()
        self.setPlainText(text)
        self.verticalScrollBar().setValue(v)
        self.horizontalScrollBar().setValue(h)
        self.apply_highlights(scroll=False)

    def _line_sel(self, lines, color):
        sels = []
        doc = self.document()
        for ln in lines:
            blk = doc.findBlockByNumber(ln)
            if not blk.isValid():
                continue
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(QColor(color))
            s.format.setProperty(QTextFormat.FullWidthSelection, True)
            s.cursor = QTextCursor(blk)
            sels.append(s)
        return sels

    def apply_highlights(self, scroll=True, focus=None):
        hot = []
        for a, b in self.sel_ranges:
            hot.extend(range(a, b + 1))
            if len(hot) > MAX_HIGHLIGHT_LINES:
                break
        self._hot = set(hot)
        sels = self._line_sel(hot[:MAX_HIGHLIGHT_LINES], "#1f2c45")
        if self.cur_range:
            sels += self._line_sel(range(self.cur_range[0], self.cur_range[1] + 1), "#2d4f8f")
        self.setExtraSelections(sels)
        self.gutter.update()
        target = focus or (self.sel_ranges[0] if self.sel_ranges else None)
        if scroll and target:
            self.ensure_range_visible(target)

    def ensure_range_visible(self, rng):
        a, b = rng
        first = self.firstVisibleBlock().blockNumber()
        visible = max(1, self.viewport().height() // max(1, self.fontMetrics().height()))
        if a < first or b >= first + visible - 1:
            self.verticalScrollBar().setValue(max(0, a - visible // 3))


class ActionDelegate(QStyledItemDelegate):
    def paint(self, p, opt, idx):
        o = QStyleOptionViewItem(opt)
        self.initStyleOption(o, idx)
        text = o.text
        o.text = ""
        style = o.widget.style() if o.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, o, p, o.widget)
        indent = idx.data(INDENT_ROLE) or 0
        t = idx.data(TYPE_ROLE)
        fg = idx.data(Qt.ForegroundRole)
        r = o.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        x = r.x() + 6
        p.setPen(QPen(QColor("#3a3c46"), 1))
        for i in range(indent):
            gx = x + i * 14 + 7
            p.drawLine(gx, r.top(), gx, r.bottom())
        x += indent * 14
        disabled = fg is not None and fg.color() == QColor(C["faint"])
        color = C["faint"] if disabled else CATEGORY_COLORS[TYPES[t]["cat"]]
        p.drawPixmap(x, r.center().y() - 8, icons.pixmap(t, color, 16))
        x += 22
        p.setPen(fg.color() if isinstance(fg, QBrush) else QColor(C["text"]))
        f = idx.data(Qt.FontRole)
        if isinstance(f, QFont):
            p.setFont(f)
        area = QRect(x, r.y(), max(0, r.right() - x - 3), r.height())
        p.drawText(area, Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(text, Qt.ElideRight, area.width()))
        p.restore()


class MacroModel(QAbstractTableModel):
    COLS = ["#", "action", "details", "repeat", "delay ms", "comment"]

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.macro = new_macro()
        self.info = analyze([])
        self.current = -1
        self.err_rows = {}
        self.disabled_rows = set()

    @property
    def acts(self):
        return self.macro["actions"]

    def set_macro(self, m):
        self.beginResetModel()
        self.macro = m
        self.current = -1
        self._recalc()
        self.endResetModel()

    def refresh(self):
        self.beginResetModel()
        self._recalc()
        self.endResetModel()

    def _recalc(self):
        self.info = analyze(self.acts)
        self.err_rows = {}
        for e in self.info["errors"]:
            self.err_rows.setdefault(e.row, str(e))
        self.disabled_rows = set()
        for i, a in enumerate(self.acts):
            if not a["enabled"] and a["type"] in ("loop", "if") and i in self.info["partner"]:
                self.disabled_rows.update(range(i, self.info["partner"][i] + 1))

    def set_current(self, row):
        old = self.current
        self.current = row
        for r in (old, row):
            if 0 <= r < len(self.acts):
                self.dataChanged.emit(self.index(r, 0), self.index(r, len(self.COLS) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.acts)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLS)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if o == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLS[s]
        if o == Qt.Horizontal and role == Qt.TextAlignmentRole:
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        r, c = idx.row(), idx.column()
        a = self.acts[r]
        t = a["type"]
        if role == Qt.DisplayRole:
            if c == 0:
                return str(r + 1)
            if c in (1, 2):
                return describe(a)[c - 1]
            if c == 3:
                return "" if t in UNTIMED else str(a["repeat"])
            if c == 4:
                return "" if t in UNTIMED or not a["delay"] else str(a["delay"])
            return a["comment"]
        if role == Qt.EditRole:
            if c == 3:
                return int(a["repeat"])
            if c == 4:
                return int(a["delay"])
            if c == 5:
                return a["comment"]
            return None
        if role == Qt.CheckStateRole and c == 0:
            return Qt.Checked if a["enabled"] else Qt.Unchecked
        if role == INDENT_ROLE:
            return self.info["indent"][r] if r < len(self.info["indent"]) else 0
        if role == TYPE_ROLE:
            return t
        if role == Qt.ForegroundRole:
            if not a["enabled"] or r in self.disabled_rows:
                return QBrush(QColor(C["faint"]))
            if c in (0, 3, 4):
                return QBrush(QColor(C["dim"]))
            if c == 2 and t == "comment":
                return QBrush(QColor("#7fae68"))
            if c == 1 and TYPES[t].get("block"):
                return QBrush(QColor(C["warn"]))
            return None
        if role == Qt.BackgroundRole:
            if r == self.current:
                return QBrush(QColor(C["row_now"]))
            if r in self.err_rows:
                return QBrush(QColor(C["row_err"]))
            if a.get("color"):
                col = QColor(a["color"])
                col.setAlpha(46)
                return QBrush(col)
            return None
        if role == Qt.FontRole:
            if c == 1 and TYPES[t].get("block"):
                f = QFont(self.app.font())
                f.setWeight(QFont.DemiBold)
                return f
            if not a["enabled"]:
                f = QFont(self.app.font())
                f.setItalic(True)
                return f
            if c == 2 and t in ("text", "setvar", "if", "loop"):
                return self.app.mono_small
            return None
        if role == Qt.ToolTipRole:
            if r in self.err_rows:
                return self.err_rows[r]
            return describe(a)[1] if c == 2 else None
        return None

    def flags(self, idx):
        if not idx.isValid():
            return Qt.ItemIsDropEnabled
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self.app.busy:
            return base
        base |= Qt.ItemIsDragEnabled
        c = idx.column()
        t = self.acts[idx.row()]["type"]
        if c == 0 and t not in LOCKED_ON:
            base |= Qt.ItemIsUserCheckable
        if c == 5 or (c in (3, 4) and t not in UNTIMED):
            base |= Qt.ItemIsEditable
        return base

    def setData(self, idx, value, role=Qt.EditRole):
        if not idx.isValid() or self.app.busy:
            return False
        r, c = idx.row(), idx.column()
        a = self.acts[r]
        if role == Qt.CheckStateRole and c == 0:
            self.app.push_undo()
            a["enabled"] = Qt.CheckState(value) == Qt.Checked
            self.app.changed()
            return True
        if role != Qt.EditRole or c not in (3, 4, 5):
            return False
        key = {3: "repeat", 4: "delay", 5: "comment"}[c]
        new = {3: lambda v: max(1, int(v)), 4: lambda v: max(0, int(v)), 5: str}[c](value)
        if a[key] == new:
            return False
        self.app.push_undo()
        a[key] = new
        self.dataChanged.emit(idx, idx)
        self.app.changed(structure=False)
        return True

    def supportedDropActions(self):
        return Qt.MoveAction | Qt.CopyAction

    def mimeTypes(self):
        return [MIME]

    def mimeData(self, idxs):
        rows = sorted({i.row() for i in idxs})
        md = QMimeData()
        md.setData(MIME, QByteArray(json.dumps({"rows": rows, "src": id(self)}).encode()))
        return md

    def canDropMimeData(self, data, action, row, col, parent):
        return data.hasFormat(MIME)

    def dropMimeData(self, data, action, row, col, parent):
        try:
            payload = json.loads(bytes(data.data(MIME)).decode())
        except ValueError:
            return False
        if not isinstance(payload, dict) or payload.get("src") != id(self):
            return False
        if row < 0:
            row = parent.row() if parent.isValid() else len(self.acts)
        self.app.move_rows_to(payload["rows"], row)
        # returning true would make qt delete the source rows as well
        return False
