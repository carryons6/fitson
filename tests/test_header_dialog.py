from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import sys

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.contracts import HeaderPayload
from astroview.app.header_dialog import HeaderDialog
from astroview.app.header_parser import parse_header_text


class TestHeaderDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_parse_header_text_merges_continue_and_comment_blocks(self) -> None:
        cards = parse_header_text(
            "\n".join(
                [
                    "SIMPLE  =                    T",
                    "OBJECT  = 'M31&'",
                    "CONTINUE  ' galaxy' / merged target",
                    "COMMENT first line",
                    "COMMENT second line",
                    "HISTORY one",
                    "HISTORY two",
                    "HIERARCH ESO DET WIN1 NX = 1024 / width",
                    "END",
                ]
            )
        )

        self.assertEqual([card.kind for card in cards], ["keyword", "continue", "comment", "history", "hierarch", "keyword"])
        self.assertEqual(cards[1].key, "OBJECT")
        self.assertEqual(cards[1].value, "M31 galaxy")
        self.assertEqual(cards[1].comment, "merged target")
        self.assertEqual(cards[1].raw_lines, (2, 3))
        self.assertEqual(cards[2].value, "first line second line")
        self.assertEqual(cards[3].value, "one two")
        self.assertEqual(cards[4].key, "HIERARCH ESO DET WIN1 NX")
        self.assertEqual(cards[4].comment, "width")

    def test_scope_and_regex_filtering_keep_raw_text_intact(self) -> None:
        dialog = self._dialog_with_payload(
            "\n".join(
                [
                    "OBJECT  = 'M31' / target field",
                    "FILTER  = 'g'",
                    "EXPTIME = 30 / seconds",
                ]
            )
        )
        try:
            dialog.set_filter_text("M31")
            self.assertEqual(dialog.filter_state.match_count, 1)
            self.assertEqual(dialog.proxy_model.rowCount(), 1)
            self.assertIn("EXPTIME", dialog.raw_view.toPlainText())

            dialog.set_filter_scope("key")
            self.assertEqual(dialog.filter_state.match_count, 0)

            dialog.set_filter_scope("value")
            self.assertEqual(dialog.filter_state.match_count, 1)

            dialog.set_filter_scope("key")
            dialog.set_use_regex(True)
            dialog.set_filter_text(r"^EXP")
            self.assertEqual(dialog.filter_state.match_count, 1)
            self.assertEqual(dialog.proxy_model.rowCount(), 1)
        finally:
            dialog.deleteLater()

    def test_next_previous_match_wraps(self) -> None:
        dialog = self._dialog_with_payload(
            "\n".join(
                [
                    "OBJECT  = 'M31'",
                    "OBJECT2 = 'M42'",
                    "FILTER  = 'g'",
                ]
            )
        )
        try:
            dialog.set_filter_text("OBJECT")
            self.assertEqual(dialog.filter_state.current_match, 1)

            dialog.show_next_match()
            self.assertEqual(dialog.filter_state.current_match, 2)

            dialog.show_next_match()
            self.assertEqual(dialog.filter_state.current_match, 1)

            dialog.show_previous_match()
            self.assertEqual(dialog.filter_state.current_match, 2)
        finally:
            dialog.deleteLater()

    def test_multi_hdu_switch_preserves_query_and_refreshes_matches(self) -> None:
        dialog = self._dialog()
        try:
            payloads = [
                self._payload(0, "PRIMARY", "OBJECT  = 'M31'\nFILTER  = 'g'"),
                self._payload(1, "SCI", "OBJECT  = 'M42'\nEXPTIME = 120"),
            ]

            dialog.set_header_payloads(payloads, current_hdu_index=0)
            dialog.set_filter_text("EXPTIME")
            self.assertEqual(dialog.filter_state.match_count, 0)

            dialog.hdu_combo.setCurrentIndex(1)

            self.assertEqual(dialog.filter_input.text(), "EXPTIME")
            self.assertEqual(dialog.filter_state.match_count, 1)
            self.assertIn("EXPTIME", dialog.raw_view.toPlainText())
            self.assertEqual(dialog.table_model.payload().hdu_index, 1)
        finally:
            dialog.deleteLater()

    def test_copy_actions_send_expected_text_to_clipboard(self) -> None:
        dialog = self._dialog_with_payload("OBJECT  = 'M31' / target field\nFILTER  = 'g'")
        try:
            dialog.set_filter_text("OBJECT")
            dialog.table_view.setCurrentIndex(dialog.proxy_model.index(0, 0))

            clipboard = Mock()
            with patch("astroview.app.header_dialog.QGuiApplication.clipboard", return_value=clipboard):
                dialog.copy_selected_key()
                dialog.copy_selected_value()
                dialog.copy_selected_card()
                dialog.copy_all_matching()

            self.assertEqual(
                [call.args[0] for call in clipboard.setText.call_args_list],
                ["OBJECT", "M31", "OBJECT  = 'M31' / target field", "OBJECT  = 'M31' / target field"],
            )
        finally:
            dialog.deleteLater()

    def test_persistence_restores_scope_regex_view_mode_and_column_widths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = str(Path(tmp_dir) / "header-dialog.ini")

            first_dialog = self._dialog(settings_path=settings_path)
            try:
                first_dialog.view_selector.setCurrentIndex(first_dialog.view_selector.findData("raw"))
                first_dialog.scope_combo.setCurrentIndex(first_dialog.scope_combo.findData("comment"))
                first_dialog.case_sensitive_checkbox.setChecked(True)
                first_dialog.regex_checkbox.setChecked(True)
                first_dialog.table_view.setColumnWidth(1, 333)
                first_dialog._store_preferences()
            finally:
                first_dialog.deleteLater()

            second_dialog = self._dialog(settings_path=settings_path)
            try:
                self.assertEqual(second_dialog.current_view_state().view_mode, "raw")
                self.assertEqual(second_dialog.current_filter_state().scope, "comment")
                self.assertTrue(second_dialog.case_sensitive_checkbox.isChecked())
                self.assertTrue(second_dialog.regex_checkbox.isChecked())
                self.assertEqual(second_dialog.table_view.columnWidth(1), 333)
            finally:
                second_dialog.deleteLater()

    def test_double_click_key_switches_to_raw_view(self) -> None:
        dialog = self._dialog_with_payload("OBJECT  = 'M31' / target field\nFILTER  = 'g'")
        try:
            dialog._handle_table_double_clicked(dialog.proxy_model.index(0, 1))
            self.assertEqual(dialog.current_view_state().view_mode, "raw")
            self.assertEqual(dialog.stack.currentIndex(), 1)
            self.assertEqual(dialog.raw_view.textCursor().blockNumber(), 0)
        finally:
            dialog.deleteLater()

    def _dialog(self, *, settings_path: str | None = None) -> HeaderDialog:
        if settings_path is None:
            file_descriptor, settings_path = tempfile.mkstemp(suffix="-header-dialog.ini")
            os.close(file_descriptor)
            self.addCleanup(lambda path=settings_path: Path(path).unlink(missing_ok=True))
        settings = QSettings(settings_path, QSettings.Format.IniFormat)
        return HeaderDialog(settings=settings)

    def _dialog_with_payload(self, raw_text: str, *, settings_path: str | None = None) -> HeaderDialog:
        dialog = self._dialog(settings_path=settings_path)
        dialog.set_header_payloads([self._payload(0, "PRIMARY", raw_text)], current_hdu_index=0)
        return dialog

    @staticmethod
    def _payload(hdu_index: int, name: str, raw_text: str) -> HeaderPayload:
        return HeaderPayload(
            hdu_index=hdu_index,
            name=name,
            kind="PrimaryHDU" if hdu_index == 0 else "ImageHDU",
            shape=(2, 2),
            cards=parse_header_text(raw_text),
            raw_text=raw_text,
        )


if __name__ == "__main__":
    unittest.main()
