from __future__ import annotations

import argparse
import importlib
import importlib.abc
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview import main as main_module


class TestMainEntry(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_package_main_module_does_not_run_app_on_import(self) -> None:
        sys.modules.pop("astroview.__main__", None)

        with patch("astroview.main.main") as main_mock:
            importlib.import_module("astroview.__main__")

        main_mock.assert_not_called()

    def test_pyinstaller_bootstrap_freeze_support_runs_before_gui_import(self) -> None:
        calls: list[str] = []

        class FakeMainLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
            def find_spec(
                self,
                fullname: str,
                path: object = None,
                target: object = None,
            ) -> object:
                if fullname == "astroview.main":
                    return importlib.util.spec_from_loader(fullname, self)
                return None

            def create_module(self, spec: object) -> types.ModuleType:
                name = getattr(spec, "name", "astroview.main")
                return types.ModuleType(str(name))

            def exec_module(self, module: types.ModuleType) -> None:
                calls.append("import_main")

                def fake_main() -> int:
                    calls.append("main")
                    return 17

                module.main = fake_main

        fake_package = types.ModuleType("astroview")
        fake_package.__path__ = []
        finder = FakeMainLoader()
        bootstrap_path = Path(__file__).resolve().parents[1] / "astroview_bootstrap.py"
        bootstrap_spec = importlib.util.spec_from_file_location(
            "_astroview_bootstrap_order_test",
            bootstrap_path,
        )
        self.assertIsNotNone(bootstrap_spec)
        self.assertIsNotNone(bootstrap_spec.loader)
        bootstrap_module = importlib.util.module_from_spec(bootstrap_spec)
        old_package = sys.modules.get("astroview")
        old_main = sys.modules.pop("astroview.main", None)

        def fake_freeze_support() -> None:
            calls.append("freeze_support")

        sys.modules["astroview"] = fake_package
        sys.meta_path.insert(0, finder)
        try:
            bootstrap_spec.loader.exec_module(bootstrap_module)
            with patch.object(
                bootstrap_module.multiprocessing,
                "freeze_support",
                side_effect=fake_freeze_support,
            ):
                result = bootstrap_module._run()
        finally:
            sys.meta_path.remove(finder)
            sys.modules.pop("astroview.main", None)
            if old_main is not None:
                sys.modules["astroview.main"] = old_main
            if old_package is not None:
                sys.modules["astroview"] = old_package
            else:
                sys.modules.pop("astroview", None)

        self.assertEqual(result, 17)
        self.assertEqual(calls, ["freeze_support", "import_main", "main"])

    def test_main_defers_startup_file_open_until_after_window_show(self) -> None:
        parser = Mock()
        parser.parse_args.return_value = argparse.Namespace(path="demo.fits", hdu=None)
        app = Mock()
        app.exec.return_value = 0
        window = Mock()

        with patch.object(main_module, "build_arg_parser", return_value=parser):
            with patch.object(main_module, "QApplication", return_value=app):
                with patch.object(main_module, "build_main_window", return_value=window):
                    with patch.object(main_module, "install_translator") as install_translator_mock:
                        with patch("astroview.main.QTimer.singleShot") as single_shot_mock:
                            with patch.object(main_module, "_resource_path", return_value=Path(".")):
                                with patch.object(main_module, "install_exception_hooks", return_value=Path("astroview.log")):
                                    with patch.object(main_module, "log_startup"):
                                        with patch.object(main_module, "log_shutdown"):
                                            with patch.object(main_module, "apply_theme"):
                                                with patch.object(main_module, "load_saved_theme", return_value="light"):
                                                    result = main_module.main()

        self.assertEqual(result, 0)
        install_translator_mock.assert_called_once_with(app)
        window.initialize.assert_called_once_with(apply_startup_request=False)
        window.show.assert_called_once_with()
        single_shot_mock.assert_called_once_with(0, window.schedule_startup_request)
        app.exec.assert_called_once_with()

    def test_smoke_test_argument_is_hidden(self) -> None:
        parser = main_module.build_arg_parser()

        args = parser.parse_args(["--smoke-test"])

        self.assertTrue(args.smoke_test)
        self.assertNotIn("--smoke-test", parser.format_help())

    def test_main_smoke_test_bypasses_normal_gui_startup(self) -> None:
        parser = Mock()
        parser.parse_args.return_value = argparse.Namespace(
            path=None,
            hdu=None,
            smoke_test=True,
        )

        with patch.object(main_module, "build_arg_parser", return_value=parser):
            with patch.object(main_module, "run_smoke_test", return_value=23) as smoke_mock:
                with patch.object(main_module, "install_exception_hooks") as hooks_mock:
                    result = main_module.main()

        self.assertEqual(result, 23)
        smoke_mock.assert_called_once_with()
        hooks_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
