"""Application theming: Fusion style + dark/light palettes + QSS.

Two themes are provided ("dark", "light"). The active theme is persisted
via QSettings under the "ui/theme" key so it survives restarts.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, QStandardPaths, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

THEME_KEY = "ui/theme"
DEFAULT_THEME = "light"
AVAILABLE_THEMES = ("dark", "light")

logger = logging.getLogger(__name__)


def _dark_palette() -> QPalette:
    p = QPalette()
    window = QColor("#1e2228")
    base = QColor("#161a20")
    alt = QColor("#232831")
    text = QColor("#e4e7eb")
    dim = QColor("#8a93a0")
    accent = QColor("#4ea1ff")

    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, alt)
    p.setColor(QPalette.ColorRole.ToolTipBase, alt)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, window)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, QColor("#ff5c5c"))
    p.setColor(QPalette.ColorRole.Link, accent)
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#0b0e12"))
    p.setColor(QPalette.ColorRole.PlaceholderText, dim)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, dim)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, dim)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, dim)
    return p


def _light_palette() -> QPalette:
    p = QPalette()
    window = QColor("#f4f6f9")
    base = QColor("#ffffff")
    alt = QColor("#eceff4")
    text = QColor("#1f2430")
    dim = QColor("#7a8290")
    accent = QColor("#2563eb")

    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, alt)
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, window)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, QColor("#d92d20"))
    p.setColor(QPalette.ColorRole.Link, accent)
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, dim)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, dim)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, dim)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, dim)
    return p


_arrow_cache_context: tempfile.TemporaryDirectory[str] | None = None
_arrow_cache_dir: Path | None = None
_arrow_cache_init_attempted = False
_arrow_paths_cache: dict[tuple[str, str], str] = {}


def _create_private_arrow_cache(base_dir: Path | None) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Create a process-private, unpredictable directory for generated icons."""

    if base_dir is not None:
        base_dir.mkdir(parents=True, exist_ok=True)
    context = tempfile.TemporaryDirectory(
        prefix="astroview-theme-icons-",
        dir=str(base_dir) if base_dir is not None else None,
    )
    cache_dir = Path(context.name)
    # TemporaryDirectory already creates mode 0700 on POSIX.  Re-apply it in
    # case an unusual platform umask or temporary-directory implementation did
    # not, while leaving Windows ACL handling to the OS.
    try:
        cache_dir.chmod(0o700)
    except OSError:
        if not cache_dir.is_dir():
            context.cleanup()
            raise
    if not cache_dir.is_dir():
        context.cleanup()
        raise OSError(f"Theme icon cache was not created: {cache_dir}")
    return context, cache_dir


def _get_arrow_cache_dir() -> Path | None:
    """Return a private per-process cache, or ``None`` if it cannot be made."""

    global _arrow_cache_context, _arrow_cache_dir, _arrow_cache_init_attempted
    if _arrow_cache_dir is not None:
        return _arrow_cache_dir
    if _arrow_cache_init_attempted:
        return None
    _arrow_cache_init_attempted = True

    cache_location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    candidates = [Path(cache_location) if cache_location else None]
    if candidates[0] is not None:
        # A secure random directory in the system temp location is a fallback
        # when the per-user Qt cache is read-only or otherwise unavailable.
        candidates.append(None)

    for base_dir in candidates:
        try:
            context, cache_dir = _create_private_arrow_cache(base_dir)
        except OSError as exc:
            logger.warning("Could not create theme icon cache under %s: %s", base_dir, exc)
            continue
        _arrow_cache_context = context
        _arrow_cache_dir = cache_dir
        return cache_dir

    logger.warning("Theme arrow icons are disabled because no writable private cache is available")
    return None


def _arrow_pixmap(direction: str, color: QColor, size: int = 12) -> QPixmap:
    """Draw a chevron arrow into a transparent pixmap."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    # Chevron points inside the pixmap with a small inset.
    inset_x = 2
    if direction == "up":
        top_y = size // 2 - 2
        bot_y = size // 2 + 2
        left = QPoint(inset_x, bot_y)
        mid = QPoint(size // 2, top_y)
        right = QPoint(size - inset_x, bot_y)
    else:  # down
        top_y = size // 2 - 2
        bot_y = size // 2 + 2
        left = QPoint(inset_x, top_y)
        mid = QPoint(size // 2, bot_y)
        right = QPoint(size - inset_x, top_y)
    painter.drawPolyline([left, mid, right])
    painter.end()
    return pm


def _arrow_path(direction: str, hex_color: str) -> str | None:
    """Return an absolute file path to a cached PNG arrow icon."""
    key = (direction, hex_color)
    cached = _arrow_paths_cache.get(key)
    if cached and Path(cached).exists():
        return cached
    cache_dir = _get_arrow_cache_dir()
    if cache_dir is None:
        return None
    pm = _arrow_pixmap(direction, QColor(hex_color))
    out = cache_dir / f"arrow_{direction}_{hex_color.lstrip('#')}.png"
    try:
        saved = pm.save(str(out), "PNG")
    except (OSError, RuntimeError) as exc:
        logger.warning("Could not write theme arrow icon %s: %s", out, exc)
        return None
    if not saved or not out.is_file():
        logger.warning("Could not write theme arrow icon %s", out)
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    # Qt QSS url() wants forward slashes; absolute path works cross-platform.
    url = out.as_posix()
    _arrow_paths_cache[key] = url
    return url


def _spinbox_qss(btn_bg: str, btn_hover: str, btn_pressed: str, border: str, arrow_color: str) -> str:
    up = _arrow_path("up", arrow_color)
    down = _arrow_path("down", arrow_color)
    up_image = f'image: url("{up}"); width: 10px; height: 10px;' if up else "image: none;"
    down_image = f'image: url("{down}"); width: 10px; height: 10px;' if down else "image: none;"
    return f"""
QSpinBox, QDoubleSpinBox {{
    padding-right: 22px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; height: 13px;
    background: {btn_bg}; border-left: 1px solid {border};
    border-top-right-radius: 4px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; height: 13px;
    background: {btn_bg}; border-left: 1px solid {border};
    border-bottom-right-radius: 4px;
    border-top: 1px solid {border};
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {btn_hover};
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: {btn_pressed};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    {up_image}
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    {down_image}
}}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled,
QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{
    image: none;
}}
"""


_QSS_DARK = """
QMainWindow, QDialog { background: #1e2228; }
QToolTip { color: #e4e7eb; background: #232831; border: 1px solid #3a414d; padding: 4px; }

QMenuBar { background: #1a1e24; color: #e4e7eb; padding: 2px 4px; border-bottom: 1px solid #2a2f38; }
QMenuBar::item { background: transparent; padding: 5px 10px; border-radius: 4px; }
QMenuBar::item:selected { background: #2d3441; }
QMenu { background: #232831; color: #e4e7eb; border: 1px solid #3a414d; padding: 4px; }
QMenu::item { padding: 5px 22px; border-radius: 3px; }
QMenu::item:selected { background: #4ea1ff; color: #0b0e12; }
QMenu::separator { height: 1px; background: #3a414d; margin: 4px 6px; }

QToolBar { background: #1a1e24; border: none; spacing: 4px; padding: 4px; }
QToolBar::separator { background: #2f3541; width: 1px; margin: 4px 6px; }
QToolButton { background: transparent; color: #e4e7eb; padding: 5px 9px; border-radius: 5px; }
QToolButton:hover { background: #2d3441; }
QToolButton:pressed, QToolButton:checked { background: #3a4557; }

QStatusBar { background: #1a1e24; color: #b8bfc9; border-top: 1px solid #2a2f38; }
QStatusBar::item { border: none; }

QDockWidget { color: #e4e7eb; titlebar-close-icon: url(none); }
QDockWidget::title { background: #232831; padding: 6px 10px; border-bottom: 1px solid #2f3541; }

QPushButton { background: #2d3441; color: #e4e7eb; border: 1px solid #3a414d; padding: 5px 12px; border-radius: 5px; }
QPushButton:hover { background: #38404e; }
QPushButton:pressed { background: #242a33; }
QPushButton:disabled { color: #6b7280; background: #232831; }
QPushButton:default { border: 1px solid #4ea1ff; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: #161a20; color: #e4e7eb; border: 1px solid #323844;
    border-radius: 4px; padding: 4px 6px; selection-background-color: #4ea1ff;
    selection-color: #0b0e12;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid #4ea1ff; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView { background: #232831; border: 1px solid #3a414d; selection-background-color: #4ea1ff; }

QTableView, QTreeView, QListView {
    background: #161a20; alternate-background-color: #1c2128; color: #e4e7eb;
    gridline-color: #2a2f38; border: 1px solid #2a2f38; selection-background-color: #4ea1ff;
    selection-color: #0b0e12;
}
QHeaderView::section {
    background: #232831; color: #c8cdd6; padding: 5px 8px;
    border: none; border-right: 1px solid #2a2f38; border-bottom: 1px solid #2a2f38;
}

QScrollBar:vertical { background: #1a1e24; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #3a414d; min-height: 24px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #4a5264; }
QScrollBar:horizontal { background: #1a1e24; height: 11px; margin: 0; }
QScrollBar::handle:horizontal { background: #3a414d; min-width: 24px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #4a5264; }
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: none; height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QTabWidget::pane { border: 1px solid #2a2f38; background: #1e2228; }
QTabBar::tab { background: #1a1e24; color: #b8bfc9; padding: 6px 14px; border: 1px solid #2a2f38; border-bottom: none; }
QTabBar::tab:selected { background: #2d3441; color: #e4e7eb; }
QTabBar::tab:hover:!selected { background: #242a33; }

QGroupBox { border: 1px solid #2f3541; border-radius: 5px; margin-top: 10px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #b8bfc9; }

QSlider::groove:horizontal { height: 4px; background: #2a2f38; border-radius: 2px; }
QSlider::handle:horizontal { background: #4ea1ff; width: 14px; margin: -5px 0; border-radius: 7px; }

QProgressBar { background: #1a1e24; border: 1px solid #2a2f38; border-radius: 4px; text-align: center; color: #e4e7eb; }
QProgressBar::chunk { background: #4ea1ff; border-radius: 3px; }

QCheckBox::indicator, QRadioButton::indicator { width: 14px; height: 14px; }
"""

_QSS_LIGHT = """
QMainWindow, QDialog { background: #f4f6f9; }
QToolTip { color: #1f2430; background: #ffffff; border: 1px solid #c9cfd9; padding: 4px; }

QMenuBar { background: #ffffff; color: #1f2430; padding: 2px 4px; border-bottom: 1px solid #e1e5ec; }
QMenuBar::item { background: transparent; padding: 5px 10px; border-radius: 4px; }
QMenuBar::item:selected { background: #e6edf7; }
QMenu { background: #ffffff; color: #1f2430; border: 1px solid #d4dae4; padding: 4px; }
QMenu::item { padding: 5px 22px; border-radius: 3px; }
QMenu::item:selected { background: #2563eb; color: #ffffff; }
QMenu::separator { height: 1px; background: #e1e5ec; margin: 4px 6px; }

QToolBar { background: #ffffff; border: none; spacing: 4px; padding: 4px; border-bottom: 1px solid #e1e5ec; }
QToolBar::separator { background: #e1e5ec; width: 1px; margin: 4px 6px; }
QToolButton { background: transparent; color: #1f2430; padding: 5px 9px; border-radius: 5px; }
QToolButton:hover { background: #eef2f8; }
QToolButton:pressed, QToolButton:checked { background: #dce5f3; }

QStatusBar { background: #ffffff; color: #4a5260; border-top: 1px solid #e1e5ec; }
QStatusBar::item { border: none; }

QDockWidget { color: #1f2430; }
QDockWidget::title { background: #eceff4; padding: 6px 10px; border-bottom: 1px solid #dde2ea; }

QPushButton { background: #ffffff; color: #1f2430; border: 1px solid #c9cfd9; padding: 5px 12px; border-radius: 5px; }
QPushButton:hover { background: #eef2f8; }
QPushButton:pressed { background: #dce5f3; }
QPushButton:disabled { color: #9aa3b2; background: #f4f6f9; }
QPushButton:default { border: 1px solid #2563eb; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: #ffffff; color: #1f2430; border: 1px solid #c9cfd9;
    border-radius: 4px; padding: 4px 6px; selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid #2563eb; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #d4dae4; selection-background-color: #2563eb; selection-color: #ffffff; }

QTableView, QTreeView, QListView {
    background: #ffffff; alternate-background-color: #f6f8fb; color: #1f2430;
    gridline-color: #e1e5ec; border: 1px solid #e1e5ec; selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QHeaderView::section {
    background: #eceff4; color: #3d4452; padding: 5px 8px;
    border: none; border-right: 1px solid #dde2ea; border-bottom: 1px solid #dde2ea;
}

QScrollBar:vertical { background: #f4f6f9; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #c4cbd6; min-height: 24px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #a8b1bf; }
QScrollBar:horizontal { background: #f4f6f9; height: 11px; margin: 0; }
QScrollBar::handle:horizontal { background: #c4cbd6; min-width: 24px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #a8b1bf; }
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: none; height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QTabWidget::pane { border: 1px solid #dde2ea; background: #ffffff; }
QTabBar::tab { background: #eceff4; color: #4a5260; padding: 6px 14px; border: 1px solid #dde2ea; border-bottom: none; }
QTabBar::tab:selected { background: #ffffff; color: #1f2430; }
QTabBar::tab:hover:!selected { background: #e4e9f1; }

QGroupBox { border: 1px solid #dde2ea; border-radius: 5px; margin-top: 10px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #4a5260; }

QSlider::groove:horizontal { height: 4px; background: #dde2ea; border-radius: 2px; }
QSlider::handle:horizontal { background: #2563eb; width: 14px; margin: -5px 0; border-radius: 7px; }

QProgressBar { background: #eceff4; border: 1px solid #dde2ea; border-radius: 4px; text-align: center; color: #1f2430; }
QProgressBar::chunk { background: #2563eb; border-radius: 3px; }

QCheckBox::indicator, QRadioButton::indicator { width: 14px; height: 14px; }
"""


def load_saved_theme() -> str:
    settings = QSettings("AstroView", "AstroView")
    name = settings.value(THEME_KEY, DEFAULT_THEME)
    if isinstance(name, str) and name in AVAILABLE_THEMES:
        return name
    return DEFAULT_THEME


def save_theme(name: str) -> None:
    if name not in AVAILABLE_THEMES:
        return
    QSettings("AstroView", "AstroView").setValue(THEME_KEY, name)


def apply_theme(app: QApplication, name: str) -> str:
    """Apply the named theme to the QApplication. Returns the applied name."""
    if name not in AVAILABLE_THEMES:
        name = DEFAULT_THEME
    app.setStyle("Fusion")
    if name == "dark":
        app.setPalette(_dark_palette())
        spin = _spinbox_qss(
            btn_bg="#232831", btn_hover="#2d3441", btn_pressed="#3a4557",
            border="#323844", arrow_color="#e4e7eb",
        )
        app.setStyleSheet(_QSS_DARK + spin)
    else:
        app.setPalette(_light_palette())
        spin = _spinbox_qss(
            btn_bg="#f4f6f9", btn_hover="#e6edf7", btn_pressed="#dce5f3",
            border="#c9cfd9", arrow_color="#1f2430",
        )
        app.setStyleSheet(_QSS_LIGHT + spin)
    return name
