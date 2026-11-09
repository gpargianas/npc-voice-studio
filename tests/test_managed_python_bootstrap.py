import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import hashlib
import json
import shutil


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "managed_python_bootstrap.ps1"
POWERSHELL = Path(os.environ.get("WINDIR", r"C:\Windows")) / (
    "System32/WindowsPowerShell/v1.0/powershell.exe"
)


@unittest.skipUnless(os.name == "nt", "Windows PowerShell bootstrap tests")
class ManagedPythonBootstrapTests(unittest.TestCase):
    def run_scenario(
        self,
        root: Path,
        *,
        already_installed: bool = False,
        install_fails: bool = False,
        install_exits_after_create: bool = False,
        reported_version: str = "3.11.15",
    ) -> subprocess.CompletedProcess[str]:
        managed_root = root / "runtime" / "python"
        managed_root.mkdir(parents=True)
        fake_python = managed_root / "cpython-3.11.15" / "python.cmd"
        fake_python.parent.mkdir(parents=True)
        fake_python.write_text(
            "@echo off\r\necho %TEST_FAKE_PYTHON_VERSION%\r\nexit /b 0\r\n",
            encoding="ascii",
        )

        state_file = root / "python-installed.txt"
        install_count = root / "install-count.txt"
        if already_installed:
            state_file.write_text("installed", encoding="ascii")

        fake_uv = root / "fake-uv.cmd"
        fake_uv.write_text(
            "@echo off\r\n"
            "if \"%~1\"==\"python\" if \"%~2\"==\"find\" goto find\r\n"
            "if \"%~1\"==\"python\" if \"%~2\"==\"install\" goto install\r\n"
            "echo Unexpected fake uv arguments 1>&2\r\n"
            "exit /b 80\r\n"
            ":find\r\n"
            "if exist \"%TEST_PYTHON_STATE%\" (\r\n"
            "  echo %TEST_MANAGED_PYTHON%\r\n"
            "  exit /b 0\r\n"
            ")\r\n"
            "echo error: No interpreter found for Python 3.11.15 in managed installations 1>&2\r\n"
            "exit /b 2\r\n"
            ":install\r\n"
            "echo invoked>>\"%TEST_INSTALL_COUNT%\"\r\n"
            "if \"%TEST_INSTALL_FAIL%\"==\"1\" (\r\n"
            "  echo simulated Python download failure 1>&2\r\n"
            "  exit /b 9\r\n"
            ")\r\n"
            "echo installed>\"%TEST_PYTHON_STATE%\"\r\n"
            "if \"%TEST_INSTALL_EXIT_AFTER_CREATE%\"==\"1\" exit /b 2\r\n"
            "exit /b 0\r\n",
            encoding="ascii",
        )

        harness = root / "run-test.ps1"
        harness.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            f". '{HELPER}'\n"
            "try {\n"
            f"  $Resolved = Resolve-AppManagedPython -UvPath '{fake_uv}' "
            f"-PythonVersion '3.11.15' -ManagedInstallRoot '{managed_root}'\n"
            "  Write-Output \"RESULT=$Resolved\"\n"
            "  exit 0\n"
            "} catch {\n"
            "  [Console]::Error.WriteLine($_.Exception.Message)\n"
            "  exit 1\n"
            "}\n",
            encoding="utf-8-sig",
        )

        environment = dict(os.environ)
        environment.update(
            {
                "TEST_MANAGED_PYTHON": str(fake_python),
                "TEST_PYTHON_STATE": str(state_file),
                "TEST_INSTALL_COUNT": str(install_count),
                "TEST_INSTALL_FAIL": "1" if install_fails else "0",
                "TEST_INSTALL_EXIT_AFTER_CREATE": (
                    "1" if install_exits_after_create else "0"
                ),
                "TEST_FAKE_PYTHON_VERSION": reported_version,
            }
        )
        return subprocess.run(
            [
                str(POWERSHELL),
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_managed_python_is_installed_then_found(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = self.run_scenario(root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("RESULT=", result.stdout)
            self.assertEqual(
                (root / "install-count.txt").read_text(encoding="ascii").count(
                    "invoked"
                ),
                1,
            )

    def test_existing_exact_managed_python_skips_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = self.run_scenario(root, already_installed=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / "install-count.txt").exists())

    def test_python_install_failure_stops_with_useful_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = self.run_scenario(root, install_fails=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("failed to install managed Python 3.11.15", result.stderr)
            self.assertIn("exit code 9", result.stderr)
            self.assertTrue((root / "install-count.txt").is_file())

    def test_nonzero_install_is_accepted_only_after_exact_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = self.run_scenario(root, install_exits_after_create=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("RESULT=", result.stdout)
            self.assertIn("exact app-managed Python 3.11.15", result.stdout)

    def test_wrong_python_version_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = self.run_scenario(
                root,
                already_installed=True,
                reported_version="3.11.14",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected 3.11.15, found 3.11.14", result.stderr)
            self.assertFalse((root / "install-count.txt").exists())

    def run_component_scenario(
        self,
        root: Path,
        *,
        install_fails: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        """Exercise the real PowerShell component boundary and final exit code."""
        source = root / "source"
        scripts = source / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts/bootstrap_runtime.ps1", scripts)
        shutil.copy2(ROOT / "scripts/managed_python_bootstrap.ps1", scripts)
        (scripts / "bootstrap_runtime.py").write_text("# handled by fake python\n")

        app_data = root / "app-data"
        managed_root = app_data / "runtime" / "python"
        fake_python = managed_root / "cpython-3.11.15" / "python.cmd"
        fake_python.parent.mkdir(parents=True)
        fake_python.write_text(
            "@echo off\r\n"
            "if \"%~1\"==\"-c\" (echo 3.11.15& exit /b 0)\r\n"
            "if \"%~1\"==\"-u\" shift\r\n"
            "if not exist \"%NPC_VOICE_STUDIO_DATA_DIR%\\runtime\" "
            "mkdir \"%NPC_VOICE_STUDIO_DATA_DIR%\\runtime\"\r\n"
            "echo {\"verified\":true}>\"%NPC_VOICE_STUDIO_DATA_DIR%\\runtime\\runtime_ready.json\"\r\n"
            "echo Environment check passed.\r\n"
            "echo Managed runtime verified.\r\n"
            "exit /b 0\r\n",
            encoding="ascii",
        )
        state = root / "installed.txt"
        fake_uv = root / "uv.cmd"
        fake_uv.write_text(
            "@echo off\r\n"
            "if \"%~1\"==\"--version\" (echo uv 0.13.5 (fixture)& exit /b 0)\r\n"
            "if \"%~1\"==\"python\" if \"%~2\"==\"find\" goto find\r\n"
            "if \"%~1\"==\"python\" if \"%~2\"==\"install\" goto install\r\n"
            "exit /b 80\r\n"
            ":find\r\n"
            f"if exist \"{state}\" (echo {fake_python}& exit /b 0)\r\n"
            "echo error: No interpreter found 1>&2\r\n"
            "exit /b 2\r\n"
            ":install\r\n"
            + (
                "echo simulated download failure 1>&2\r\nexit /b 9\r\n"
                if install_fails
                else (
                    f"echo installed>\"{state}\"\r\n"
                    "echo error: Failed to create Python minor version link directory 1>&2\r\n"
                    "echo cause: The path cannot be traversed because it contains an untrusted mount point. 1>&2\r\n"
                    "echo (os error 448) 1>&2\r\n"
                    "exit /b 2\r\n"
                )
            ),
            encoding="ascii",
        )
        uv_hash = hashlib.sha256(fake_uv.read_bytes()).hexdigest()
        bootstrap_source = (scripts / "bootstrap_runtime.ps1").read_text(
            encoding="utf-8-sig"
        )
        bootstrap_source = bootstrap_source.replace(
            '$UvHash = (Get-FileHash -LiteralPath $UvPath -Algorithm SHA256).Hash',
            f'$UvHash = "{uv_hash}"',
        )
        (scripts / "bootstrap_runtime.ps1").write_text(
            bootstrap_source, encoding="utf-8-sig"
        )
        (source / "runtime_manifest.json").write_text(
            json.dumps(
                {
                    "uv_version": "0.13.5",
                    "uv_sha256": uv_hash,
                    "python_version": "3.11.15",
                }
            ),
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment["NPC_VOICE_STUDIO_DATA_DIR"] = str(app_data)
        result = subprocess.run(
            [
                str(POWERSHELL),
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(scripts / "bootstrap_runtime.ps1"),
                "-UvPath",
                str(fake_uv),
                "-NoLaunch",
                "-StatusFile",
                str(app_data / "runtime" / "setup_status.txt"),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        return result, app_data / "runtime" / "runtime_ready.json"

    def test_recovered_error_448_does_not_leak_from_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result, marker = self.run_component_scenario(Path(temporary_directory))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(marker.is_file())
            self.assertIn("os error 448", result.stdout)
            self.assertIn("exact app-managed Python 3.11.15", result.stdout)

    def test_component_stops_when_install_fails_without_interpreter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result, marker = self.run_component_scenario(
                Path(temporary_directory), install_fails=True
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())
            self.assertIn("exit code 9", result.stderr)


if __name__ == "__main__":
    unittest.main()
