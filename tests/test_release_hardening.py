from __future__ import annotations

import os
import shutil
import subprocess
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
        spec = (ROOT / "astroview.spec").read_text(encoding="utf-8")
        verifier = (ROOT / "scripts" / "verify_conda_environment.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("Invoke-BundledSmokeTest", build_script)
        self.assertIn("Invoke-BundledSmokeAttempt", build_script)
        self.assertIn('"--smoke-test"', build_script)
        self.assertIn('-AttemptName "cold-start"', build_script)
        self.assertIn('-TimeoutMilliseconds 300000', build_script)
        self.assertIn('-AttemptName "warm-start"', build_script)
        self.assertIn('-TimeoutMilliseconds 60000', build_script)
        self.assertIn("$process.Kill($true)", build_script)
        self.assertIn('"System32\\taskkill.exe"', build_script)
        self.assertIn("/PID $process.Id /T /F", build_script)
        self.assertIn("Get-FileHash", build_script)
        self.assertIn("SHA256SUMS.txt", build_script)
        self.assertIn('$line + "`n"', build_script)
        self.assertNotIn("[Environment]::NewLine", build_script)
        self.assertIn("$helpOutput = @(& $IsccPath /? 2>&1)", build_script)
        self.assertIn('$previousErrorActionPreference = $ErrorActionPreference', build_script)
        self.assertIn('$ErrorActionPreference = "Continue"', build_script)
        self.assertIn('$ErrorActionPreference = $previousErrorActionPreference', build_script)
        self.assertIn("Where-Object { $_ -match '^Inno Setup \\d+(?:\\s|$)' }", build_script)
        self.assertIn("$versionBanner -notmatch '^Inno Setup 6(?:\\s|$)'", build_script)
        self.assertIn("stdout/stderr merging does not guarantee", build_script)
        self.assertIn("CondaLockPath", build_script)
        self.assertIn('"verify_conda_environment.ps1"', build_script)
        self.assertIn("-Prefix $env:CONDA_PREFIX", build_script)
        self.assertIn("-PythonPath $buildPython", build_script)
        self.assertIn("--explicit --sha256", verifier)
        self.assertIn("list --prefix $resolvedPrefix --json", verifier)
        self.assertIn("list --prefix $resolvedPrefix --no-pip --json", verifier)
        self.assertIn('build_string -eq "pypi_0"', verifier)
        self.assertIn("contains unlocked pip-managed packages", verifier)
        self.assertIn("read_text('INSTALLER')", verifier)
        self.assertIn("distributions installed by pip instead of the release lock", verifier)
        self.assertIn("doctor --prefix $resolvedPrefix altered-files missing-files", verifier)
        self.assertIn("Compare-Object", verifier)
        self.assertIn("-m pip check", verifier)
        self.assertNotIn("str(workspace_dir)", spec)
        self.assertNotIn("upx=True", spec)
        self.assertGreaterEqual(spec.count("upx=False"), 2)

    def test_release_environment_preparation_is_fail_closed(self) -> None:
        prepare_script = (ROOT / "scripts" / "prepare_release_env.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('[string]$Name = "astroview-release"', prepare_script)
        self.assertIn('[switch]$Recreate', prepare_script)
        self.assertIn('if (-not $Recreate)', prepare_script)
        self.assertIn('@("info", "--base")', prepare_script)
        self.assertIn("base environment cannot be used or recreated", prepare_script)
        self.assertIn('"env", "remove", "--prefix", $resolvedExistingPrefix, "--yes"', prepare_script)
        self.assertIn('"create",', prepare_script)
        self.assertIn('"--file", $resolvedLockPath', prepare_script)
        self.assertIn('"verify_conda_environment.ps1"', prepare_script)
        self.assertIn('-LockOnly', prepare_script)
        self.assertIn("No changes were made", prepare_script)

    @unittest.skipUnless(os.name == "nt", "PowerShell release verifier is Windows-specific")
    def test_release_environment_verifier_rejects_non_https_actual_records(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")

        expected_url = (
            "https://conda.anaconda.org/conda-forge/win-64/"
            "example-1.0-0.conda#" + "a" * 64
        )
        extra_url = "file:///local/extra-1.0-0.conda#" + "b" * 64
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            lock_path = tmp / "environment.lock"
            lock_path.write_text(f"@EXPLICIT\n{expected_url}\n", encoding="utf-8")
            fake_conda = tmp / "conda.cmd"
            fake_conda.write_text(
                "@echo off\n"
                "echo @EXPLICIT\n"
                f"echo {expected_url}\n"
                f"echo {extra_url}\n"
                "exit /b 0\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PATH"] = str(tmp) + os.pathsep + environment.get("PATH", "")
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts" / "verify_conda_environment.ps1"),
                    "-LockPath",
                    str(lock_path),
                    "-Prefix",
                    sys.prefix,
                    "-PythonPath",
                    sys.executable,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "unsupported or malformed package records",
            completed.stdout + completed.stderr,
        )

    @unittest.skipUnless(os.name == "nt", "PowerShell release verifier is Windows-specific")
    def test_release_environment_verifier_rejects_unlocked_pip_packages(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")

        expected_url = (
            "https://conda.anaconda.org/conda-forge/win-64/"
            "example-1.0-0.conda#" + "a" * 64
        )
        conda_record = (
            '[{"name":"example","version":"1.0","build_string":"0",'
            '"channel":"conda-forge","platform":"win-64"}]'
        )
        mixed_records = (
            '[{"name":"example","version":"1.0","build_string":"0",'
            '"channel":"conda-forge","platform":"win-64"},'
            '{"name":"extra","version":"2.0","build_string":"pypi_0",'
            '"channel":"pypi","platform":"pypi"}]'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            lock_path = tmp / "environment.lock"
            lock_path.write_text(f"@EXPLICIT\n{expected_url}\n", encoding="utf-8")
            fake_conda = tmp / "conda.cmd"
            fake_conda.write_text(
                "@echo off\n"
                'echo %* | findstr /C:"--no-pip" >nul\n'
                "if not errorlevel 1 (\n"
                f"  echo {conda_record}\n"
                "  exit /b 0\n"
                ")\n"
                'echo %* | findstr /C:"--json" >nul\n'
                "if not errorlevel 1 (\n"
                f"  echo {mixed_records}\n"
                "  exit /b 0\n"
                ")\n"
                "echo @EXPLICIT\n"
                f"echo {expected_url}\n"
                "exit /b 0\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PATH"] = str(tmp) + os.pathsep + environment.get("PATH", "")
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts" / "verify_conda_environment.ps1"),
                    "-LockPath",
                    str(lock_path),
                    "-Prefix",
                    sys.prefix,
                    "-PythonPath",
                    sys.executable,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "contains unlocked pip-managed packages",
            completed.stdout + completed.stderr,
        )

    @unittest.skipUnless(os.name == "nt", "PowerShell release verifier is Windows-specific")
    def test_release_environment_verifier_rejects_pip_replacement(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")

        expected_url = (
            "https://conda.anaconda.org/conda-forge/win-64/"
            "example-1.0-0.conda#" + "a" * 64
        )
        conda_record = (
            '[{"name":"example","version":"1.0","build_string":"0",'
            '"channel":"conda-forge","platform":"win-64"}]'
        )
        pip_record = (
            '[{"name":"example","version":"1.0","build_string":"pypi_0",'
            '"channel":"pypi","platform":"pypi"}]'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            lock_path = tmp / "environment.lock"
            lock_path.write_text(f"@EXPLICIT\n{expected_url}\n", encoding="utf-8")
            dist_info = tmp / "example-1.0.dist-info"
            dist_info.mkdir()
            (dist_info / "METADATA").write_text(
                "Name: example\nVersion: 1.0\n",
                encoding="utf-8",
            )
            (dist_info / "INSTALLER").write_text("pip\n", encoding="utf-8")
            fake_conda = tmp / "conda.cmd"
            fake_conda.write_text(
                "@echo off\n"
                'echo %* | findstr /C:"--no-pip" >nul\n'
                "if not errorlevel 1 (\n"
                f"  echo {conda_record}\n"
                "  exit /b 0\n"
                ")\n"
                'echo %* | findstr /C:"--json" >nul\n'
                "if not errorlevel 1 (\n"
                f"  echo {pip_record}\n"
                "  exit /b 0\n"
                ")\n"
                "echo @EXPLICIT\n"
                f"echo {expected_url}\n"
                "exit /b 0\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PATH"] = str(tmp) + os.pathsep + environment.get("PATH", "")
            environment["PYTHONPATH"] = str(tmp)
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts" / "verify_conda_environment.ps1"),
                    "-LockPath",
                    str(lock_path),
                    "-Prefix",
                    sys.prefix,
                    "-PythonPath",
                    sys.executable,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

        self.assertNotEqual(completed.returncode, 0)
        verifier_output = completed.stdout + completed.stderr
        self.assertIn("contains distributions installed by pip", verifier_output)
        # PowerShell 7 may wrap the rendered error between "instead of" and
        # "the release lock" (and inject ANSI styling), so assert the stable
        # semantic fragments rather than one display-width-dependent phrase.
        self.assertIn("the release lock", verifier_output)

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
            "/pyinstaller-hooks-contrib-2026.6-",
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
