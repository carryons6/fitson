from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import sys
from pathlib import Path

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.i18n import install_translator, load_preferred_language, save_preferred_language
from astroview.app.main_window import MainWindow
from astroview.app.status_bar import AppStatusBar


class TestI18n(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        install_translator(self._app, "en")

    def test_save_and_load_preferred_language_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = QSettings(str(Path(tmp_dir) / "astroview-test.ini"), QSettings.Format.IniFormat)

            save_preferred_language("zh_CN", settings)

            self.assertEqual(load_preferred_language(settings), "zh_CN")

    def test_install_translator_localizes_status_bar(self) -> None:
        install_translator(self._app, "zh_CN")
        bar = AppStatusBar()
        try:
            self.assertEqual(bar.activity_cancel_btn.text(), "取消")
            self.assertEqual(bar.activity_continue_btn.text(), "继续")
            self.assertEqual(bar.pixel_label.text(), "像素：(-, -)")
            self.assertEqual(bar.zoom_label.text(), "缩放：100%")
        finally:
            bar.close()
            bar.deleteLater()

    def test_main_window_builds_chinese_menu_labels(self) -> None:
        install_translator(self._app, "zh_CN")
        window = MainWindow()
        try:
            window.create_actions()
            window.build_ui()

            self.assertEqual(window.menu_file.title(), "文件")
            self.assertEqual(window.menu_view.title(), "视图")
            self.assertEqual(window.menu_language.title(), "语言")
            self.assertEqual(window.action_frame_layout_single.text(), "单帧显示")
            self.assertEqual(window.action_check_updates.text(), "检查更新...")
        finally:
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
