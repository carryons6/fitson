from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_release_tag import read_version, verify_release_tag


class TestReleaseTagValidation(unittest.TestCase):
    def test_tag_must_exactly_match_version(self) -> None:
        verify_release_tag("v1.7.4", "1.7.4")
        for bad_tag in ("1.7.4", "v1.7.5", "v1.7.4-rc1", "v01.7.4"):
            with self.subTest(tag=bad_tag):
                with self.assertRaises(ValueError):
                    verify_release_tag(bad_tag, "1.7.4")

    def test_version_file_rejects_non_numeric_release_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            version_file = Path(tmpdir) / "VERSION"
            version_file.write_text("1.7.4-rc1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_version(version_file)


class TestReleaseConfigurationHardening(unittest.TestCase):
    def test_installer_only_registers_optional_open_with_handler(self) -> None:
        installer = (ROOT / "installer.iss").read_text(encoding="utf-8")

        self.assertNotIn("Root: HKCR", installer)
        self.assertIn('Name: "fileassoc"', installer)
        self.assertIn('Flags: unchecked', installer)
        self.assertEqual(installer.count("OpenWithProgids"), 3)
        self.assertEqual(
            installer.count(
                'OpenWithProgids"; ValueType: string; ValueName: "AstroView.FITS"; ValueData: ""'
            ),
            3,
        )
        self.assertNotIn('OpenWithProgids"; ValueType: none', installer)
        self.assertNotIn('Subkey: "Software\\Classes\\.fits"; ValueType: string', installer)

    def test_spec_does_not_disable_pyinstaller_discovery(self) -> None:
        spec = (ROOT / "astroview.spec").read_text(encoding="utf-8")

        self.assertNotIn("discover_hook_directories =", spec)
        self.assertNotIn("find_binary_dependencies =", spec)
        self.assertNotIn("icudt78.dll", spec.lower())
        self.assertIn("_collect_conda_icu_binaries", spec)
        self.assertIn('"metadata.py"', spec)
        self.assertIn("Required runtime binary", spec)

    def test_release_build_smoke_tests_and_hashes_frozen_executable(self) -> None:
        build_script = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")

        self.assertIn("Invoke-BundledSmokeTest", build_script)
        self.assertIn('"--smoke-test"', build_script)
        self.assertIn("Get-FileHash", build_script)
        self.assertIn("SHA256SUMS.txt", build_script)
        self.assertIn('$line + "`n"', build_script)
        self.assertNotIn("[Environment]::NewLine", build_script)
        self.assertIn("$helpOutput = @(& $IsccPath /? 2>&1)", build_script)
        self.assertIn("Where-Object { $_ -match '^Inno Setup \\d+(?:\\s|$)' }", build_script)
        self.assertIn("$versionBanner -notmatch '^Inno Setup 6(?:\\s|$)'", build_script)
        self.assertIn("stdout/stderr merging does not guarantee", build_script)
        self.assertIn("CondaLockPath", build_script)
        self.assertIn("--explicit --sha256", build_script)
        self.assertIn("Compare-Object", build_script)

    def test_release_environment_pins_critical_build_inputs(self) -> None:
        environment = (ROOT / "environment.yml").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        for requirement in (
            "python=3.12.13",
            "pyside6=6.11.0",
            "astropy=7.2.0",
            "numpy=2.4.3",
            "sep=1.4.1",
            "pyinstaller=6.20.0",
            "pyinstaller-hooks-contrib=2026.6",
            "libopenblas=0.3.32",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, environment)
        self.assertIn('setuptools==82.0.1', pyproject)
        self.assertIn('wheel==0.47.0', pyproject)

    def test_windows_release_lock_uses_only_hash_pinned_conda_forge_artifacts(self) -> None:
        lock_lines = (ROOT / "environment-win-64.conda.lock").read_text(
            encoding="ascii"
        ).splitlines()
        content_lines = [line for line in lock_lines if line and not line.startswith("#")]

        self.assertGreater(len(content_lines), 200)
        self.assertEqual(content_lines[0], "@EXPLICIT")
        package_urls = content_lines[1:]
        self.assertEqual(len(package_urls), len(set(package_urls)))
        for package_url in package_urls:
            with self.subTest(package_url=package_url):
                self.assertRegex(package_url, r"#[0-9a-f]{64}$")
                parsed = urlparse(package_url.rsplit("#", 1)[0])
                self.assertEqual(parsed.scheme, "https")
                self.assertEqual(parsed.netloc, "conda.anaconda.org")
                self.assertRegex(parsed.path, r"^/conda-forge/(?:win-64|noarch)/[^/]+$")

        joined = "\n".join(package_urls).lower()
        for artifact in (
            "/python-3.12.13-",
            "/pyside6-6.11.0-",
            "/astropy-7.2.0-",
            "/numpy-2.4.3-",
            "/sep-1.4.1-",
            "/pyinstaller-6.20.0-",
        ):
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, joined)

    def test_release_workflow_separates_build_and_publish_permissions(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

        self.assertEqual(workflow.count("contents: write"), 1)
        self.assertIn("publish-release:", workflow)
        self.assertIn("needs: windows-build", workflow)
        self.assertIn("verify_release_tag.py", workflow)
        self.assertIn("SHA256SUMS.txt", workflow)
        self.assertIn("sha256sum --check SHA256SUMS.txt", workflow)
        self.assertIn("RELEASE_NOTES.md", workflow)
        self.assertIn("body_path: release-assets/RELEASE_NOTES.md", workflow)
        self.assertIn("environment-win-64.conda.lock", workflow)
        self.assertNotIn("environment-file: environment.yml", workflow)
        self.assertIn("-CondaLockPath environment-win-64.conda.lock", workflow)
        self.assertNotIn("miniforge-version:", workflow)
        self.assertIn(
            "14a8635465b5190537ddad6286746ffebbc55a1ed2a7bb14a506595fe3191e1e",
            workflow,
        )
        self.assertIn(
            "https://github.com/jrsoftware/issrc/releases/download/is-6_7_1/innosetup-6.7.1.exe",
            workflow,
        )
        self.assertIn(
            "4d11e8050b6185e0d49bd9e8cc661a7a59f44959a621d31d11033124c4e8a7b0",
            workflow,
        )
        self.assertNotIn("choco install innosetup", workflow)
        self.assertIn("installer-url: ${{ steps.miniforge.outputs.installer-url }}", workflow)
        self.assertNotIn("actions/checkout@v", workflow)
        self.assertNotIn("setup-miniconda@v", workflow)
        self.assertNotIn("upload-artifact@v", workflow)
        self.assertNotIn("action-gh-release@v", workflow)

    def test_ci_smoke_tests_built_wheel_across_declared_python_range(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("package-smoke:", workflow)
        self.assertIn('python-version: ["3.10", "3.11", "3.12", "3.13"]', workflow)
        self.assertIn("pip wheel . --no-deps", workflow)
        self.assertIn("astroview --smoke-test", workflow)
        self.assertIn("Push-Location $outsideCheckout", workflow)
        self.assertIn("astroview/environment-win-64.conda.lock", workflow)
        self.assertNotIn("miniforge-version:", workflow)
        self.assertIn(
            "14a8635465b5190537ddad6286746ffebbc55a1ed2a7bb14a506595fe3191e1e",
            workflow,
        )
        self.assertNotIn("actions/setup-python@v", workflow)


if __name__ == "__main__":
    unittest.main()
