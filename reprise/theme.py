from .paths import asset

C = {
    "bg": "#16171b", "panel": "#1d1e23", "panel2": "#24252b", "panel3": "#2d2e36", "border": "#34363f",
    "text": "#dcdee4", "dim": "#8d919c", "faint": "#62666f", "accent": "#5b9dff", "accent_dim": "#274a85",
    "rec": "#ee5a5f", "rec_dim": "#4a1d20", "ok": "#4cc76a", "ok_dim": "#1b3d25", "warn": "#e0b040", "warn_dim": "#47391a",
    "row_alt": "#202127", "row_now": "#22457a", "row_err": "#432024",
}


def stylesheet(mono):
    return f"""
* {{ outline: 0; dialogbuttonbox-buttons-have-icons: 0; }}
QWidget {{ background: {C['bg']}; color: {C['text']}; font-size: 10pt; }}
QLabel {{ background: transparent; }}
QMainWindow::separator {{ background: {C['border']}; width: 1px; height: 1px; }}
QToolTip {{ background: {C['panel3']}; color: {C['text']}; border: 1px solid {C['border']}; padding: 4px 6px; }}
QMenuBar {{ background: {C['panel']}; padding: 2px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; background: transparent; }}
QMenuBar::item:selected {{ background: {C['panel3']}; }}
QMenu {{ background: {C['panel2']}; border: 1px solid {C['border']}; padding: 4px; }}
QMenu::item {{ padding: 5px 26px 5px 10px; border-radius: 4px; }}
QMenu::item:selected {{ background: {C['accent_dim']}; }}
QMenu::item:disabled {{ color: {C['faint']}; }}
QMenu::separator {{ height: 1px; background: {C['border']}; margin: 4px 6px; }}
QToolBar {{ background: {C['panel']}; border: none; spacing: 2px; }}
QToolBar#main {{ border-top: 1px solid {C['border']}; border-bottom: 1px solid {C['border']}; padding: 3px 6px; }}
QToolBar#rows {{ border-bottom: 1px solid {C['border']}; padding: 2px 4px; }}
QToolBar::separator {{ background: {C['border']}; width: 1px; margin: 5px 7px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 3px 7px; }}
QToolBar#main QToolButton {{ min-width: 46px; }}
QToolButton:hover {{ background: {C['panel3']}; border-color: {C['border']}; }}
QToolButton:pressed, QToolButton:checked {{ background: {C['accent_dim']}; border-color: {C['accent']}; }}
QToolButton:disabled {{ color: {C['faint']}; background: transparent; border-color: transparent; }}
QToolButton#recBtn[recording="true"] {{ background: {C['rec_dim']}; border-color: {C['rec']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton {{ background: {C['panel3']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px 12px; }}
QPushButton:hover {{ border-color: {C['accent']}; }}
QPushButton:pressed {{ background: {C['accent_dim']}; }}
QPushButton:default {{ border-color: {C['accent']}; }}
QPushButton:disabled {{ color: {C['faint']}; border-color: {C['panel3']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 3px 5px;
    selection-background-color: {C['accent_dim']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {C['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {C['faint']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{ image: url({asset('down.svg')}); width: 12px; height: 12px; margin-right: 6px; }}
QComboBox QAbstractItemView {{ background: {C['panel2']}; border: 1px solid {C['border']}; selection-background-color: {C['accent_dim']}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({asset('up.svg')}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({asset('down.svg')}); width: 10px; height: 10px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {C['panel3']}; border-radius: 3px; }}
QCheckBox {{ spacing: 6px; background: transparent; }}
QCheckBox:disabled {{ color: {C['faint']}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #50535e; border-radius: 3px; background: {C['panel']}; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; image: url({asset('check.svg')}); }}
QTableView {{ background: {C['panel']}; alternate-background-color: {C['row_alt']}; border: none; gridline-color: #2a2b32;
    selection-background-color: {C['accent_dim']}; selection-color: {C['text']}; }}
QTableView::item {{ padding: 0 5px; border: none; }}
QTableView::indicator {{ width: 13px; height: 13px; border: 1px solid #50535e; border-radius: 3px; background: {C['panel2']}; }}
QTableView::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; image: url({asset('check.svg')}); }}
QTableView QLineEdit, QTableView QSpinBox {{ border-radius: 0; padding: 0 3px; }}
QHeaderView {{ background: {C['panel2']}; }}
QHeaderView::section {{ background: {C['panel2']}; color: {C['dim']}; border: none; border-right: 1px solid {C['border']};
    border-bottom: 1px solid {C['border']}; padding: 4px 7px; font-size: 9pt; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3e404a; border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: #50535f; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #3e404a; border-radius: 4px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {C['border']}; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: {C['panel']}; color: {C['dim']}; padding: 5px 10px; border: 1px solid {C['border']};
    border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin: 3px 2px 0 0; }}
QTabBar::tab:selected {{ background: {C['panel3']}; color: {C['text']}; border-top: 2px solid {C['accent']}; }}
QTabBar::tab:hover {{ color: {C['text']}; }}
QTabBar::close-button {{ image: url({asset('close.svg')}); subcontrol-position: right; margin-left: 4px; }}
QTabBar::close-button:hover {{ background: {C['panel2']}; border-radius: 3px; }}
QTabWidget::pane {{ border: 1px solid {C['border']}; border-radius: 4px; top: -1px; }}
QStatusBar {{ background: {C['panel']}; border-top: 1px solid {C['border']}; color: {C['dim']}; }}
QStatusBar QLabel {{ background: transparent; padding: 0 8px; }}
QStatusBar::item {{ border: none; }}
QLabel#state[mode="rec"] {{ color: {C['rec']}; font-weight: 600; }}
QLabel#state[mode="play"] {{ color: {C['ok']}; font-weight: 600; }}
QLabel#state[mode="pause"] {{ color: {C['warn']}; font-weight: 600; }}
QLabel#state[mode="bad"] {{ color: {C['rec']}; }}
QFrame#bar {{ background: {C['panel']}; border-bottom: 1px solid {C['border']}; }}
QFrame#bar QWidget {{ background: transparent; }}
QFrame#bar QLineEdit, QFrame#bar QSpinBox, QFrame#bar QDoubleSpinBox {{ background: {C['bg']}; }}
QFrame#bar QPushButton {{ background: {C['panel3']}; padding: 3px 9px; }}
QFrame#barSep {{ background: {C['border']}; }}
QLabel#barLabel {{ color: {C['dim']}; }}
QFrame#banner {{ border-bottom: 1px solid {C['border']}; }}
QFrame#banner[mode="rec"] {{ background: {C['rec_dim']}; }}
QFrame#banner[mode="play"] {{ background: {C['ok_dim']}; }}
QFrame#banner[mode="pause"] {{ background: {C['warn_dim']}; }}
QFrame#banner QLabel {{ background: transparent; font-weight: 600; }}
QFrame#commands {{ background: {C['panel']}; border-right: 1px solid {C['border']}; }}
QFrame#commands QWidget {{ background: {C['panel']}; }}
QLabel#cmdHead {{ color: {C['faint']}; font-size: 9pt; padding: 6px 10px 1px 10px; }}
QPushButton#cmd {{ text-align: left; padding: 2px 6px; border-radius: 4px; margin: 0 4px; background: transparent; border: 1px solid transparent; }}
QPushButton#cmd:hover {{ background: {C['panel3']}; border-color: {C['border']}; }}
QPushButton#cmd:pressed {{ background: {C['accent_dim']}; }}
QPushButton#cmd:disabled {{ color: {C['faint']}; }}
QFrame#tabRow, QFrame#tabRow QWidget {{ background: {C['panel2']}; }}
QFrame#tabRow {{ border-bottom: 1px solid {C['border']}; }}
QFrame#codePanel, QFrame#codePanel QWidget {{ background: {C['panel']}; }}
QFrame#codeHead {{ border-bottom: 1px solid {C['border']}; }}
QLabel#paneTitle {{ color: {C['dim']}; font-size: 9pt; padding: 0 4px; }}
QLabel#dim {{ color: {C['dim']}; }}
QLabel#hint {{ color: {C['dim']}; }}
QLabel#dlgHead {{ font-size: 13pt; font-weight: 600; }}
QFrame#card {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 6px; }}
QFrame#card QLabel {{ background: transparent; color: {C['dim']}; }}
QFrame#card QWidget {{ background: transparent; }}
QFrame#card QLineEdit, QFrame#card QComboBox, QFrame#card QSpinBox, QFrame#card QPlainTextEdit {{ background: {C['bg']}; }}
QFrame#card QPushButton {{ background: {C['panel3']}; }}
QLabel#preview {{ background: {C['bg']}; border: 1px dashed {C['border']}; border-radius: 4px; padding: 6px; color: {C['faint']}; }}
QLabel#result {{ color: {C['ok']}; font-family: "{mono}"; }}
QLabel#result[bad="true"] {{ color: {C['rec']}; }}
QPlainTextEdit#code {{ background: {C['bg']}; border: none; border-radius: 0; padding: 0; font-family: "{mono}"; }}
QTextBrowser {{ background: {C['panel']}; border: none; padding: 8px; }}
QFrame#welcome, QFrame#welcome QWidget {{ background: transparent; }}
QFrame#welcome QPushButton {{ background: {C['panel3']}; padding: 7px 16px; }}
QFrame#welcome QPushButton#recordBig {{ background: {C['rec_dim']}; border-color: {C['rec']}; }}
QLabel#welcomeHead {{ font-size: 15pt; font-weight: 600; }}
QFrame#welcome QLabel#stepNum {{ background: {C['panel3']}; border-radius: 12px; color: {C['text']}; font-weight: 600; }}
QLabel#stepText {{ color: {C['dim']}; }}
QDialog {{ background: {C['panel2']}; }}
QDialog QWidget {{ background: {C['panel2']}; }}
"""
