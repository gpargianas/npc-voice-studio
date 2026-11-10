import json
from pathlib import Path
import re
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingTests(unittest.TestCase):
    def test_release_icon_contains_all_windows_sizes(self) -> None:
        png_path = ROOT / "assets" / "app_icon.png"
        ico_path = ROOT / "assets" / "app_icon.ico"
        self.assertTrue(png_path.is_file())
        self.assertTrue(ico_path.is_file())
        self.assertFalse((ROOT / "assets" / "app_icon.png.png").exists())

        data = ico_path.read_bytes()
        reserved, image_type, count = struct.unpack_from("<HHH", data)
        self.assertEqual((reserved, image_type), (0, 1))
        sizes = set()
        for index in range(count):
            width, height = struct.unpack_from("<BB", data, 6 + index * 16)
            sizes.add((256 if width == 0 else width, 256 if height == 0 else height))
        expected = {(size, size) for size in (16, 24, 32, 48, 64, 128, 256)}
        self.assertEqual(sizes, expected)

    def test_one_manifest_version_drives_project_and_installer(self) -> None:
        manifest = json.loads(
            (ROOT / "runtime_manifest.json").read_text(encoding="utf-8")
        )
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"$', pyproject, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), manifest["application_version"])

        inno = (ROOT / "installer" / "NPCVoiceStudio.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn("#ifndef AppVersion", inno)
        self.assertIn("AppVersion={#AppVersion} alpha", inno)
        self.assertNotIn('AppVersion=0.1.0', inno)

    def test_installer_is_per_user_and_preserves_user_data(self) -> None:
        source = (ROOT / "installer" / "NPCVoiceStudio.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn("PrivilegesRequired=lowest", source)
        self.assertIn(
            r"DefaultDirName={localappdata}\Programs\{#AppName}", source
        )
        self.assertIn("ArchitecturesAllowed=x64compatible", source)
        self.assertIn("NPC Voice Studio.exe", source)
        self.assertNotIn("[UninstallDelete]", source)
        self.assertNotIn(r"{localappdata}\NPC Voice Studio\*", source)

    def test_launcher_is_only_a_hidden_sta_bridge(self) -> None:
        source = (ROOT / "launcher" / "NpcVoiceStudioLauncher.cs").read_text(
            encoding="utf-8"
        )
        self.assertIn("[STAThread]", source)
        self.assertIn('"-STA"', source)
        self.assertIn('"WindowsPowerShell"', source)
        self.assertIn("Assembly.GetExecutingAssembly().Location", source)
        self.assertIn("CreateNoWindow = true", source)
        self.assertIn("return process.ExitCode", source)
        for forbidden in ("torch", "omnivoice", "python.exe", "conda", "uv.exe"):
            self.assertNotIn(forbidden, source.lower())

    def test_build_stages_verified_uv_and_rejects_user_data(self) -> None:
        source = (ROOT / "scripts" / "build_windows_release.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("uv_sha256", source)
        self.assertIn('"tools\\uv\\uv.exe"', source)
        self.assertIn('"voice_profiles"', source)
        self.assertIn('"generated_audio"', source)
        self.assertIn('"models"', source)
        self.assertIn('"logs"', source)
        self.assertIn("Get-FileHash", source)
        self.assertIn('"scripts\\managed_python_bootstrap.ps1"', source)
        self.assertIn('"assets\\app_icon.png"', source)
        self.assertIn('"assets\\app_icon.ico"', source)
        self.assertIn('"BUILDING.md"', source)
        self.assertNotIn('"docs\\phase-c', source)
        self.assertIn('/win32icon:', source)

    def test_windows_branding_references_packaged_icon(self) -> None:
        inno = (ROOT / "installer" / "NPCVoiceStudio.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn(r"SetupIconFile={#SourceDir}\assets\app_icon.ico", inno)
        self.assertIn(r"UninstallDisplayIcon={app}\assets\app_icon.ico", inno)
        self.assertEqual(
            inno.count(r'IconFilename: "{app}\assets\app_icon.ico"'), 2
        )

        launcher = (ROOT / "scripts" / "launch_npc_voice_studio.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('Join-Path $SourceRoot "assets\\app_icon.ico"', launcher)
        self.assertEqual(launcher.count("Set-FormIcon "), 2)

        app = (ROOT / "app.py").read_text(encoding="utf-8")
        bootstrap = (ROOT / "scripts" / "bootstrap_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("favicon_path=", app)
        self.assertIn('source_root / "assets" / "app_icon.png"', bootstrap)

    def test_release_resource_paths_are_not_developer_absolute_paths(self) -> None:
        for relative_path in (
            "app.py",
            "installer/NPCVoiceStudio.iss",
            "scripts/build_windows_release.ps1",
            "scripts/launch_npc_voice_studio.ps1",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"[A-Za-z]:[\\/]npc-voice-studio", source),
                relative_path,
            )

    def test_launchers_do_not_write_bytecode_into_installed_source(self) -> None:
        for relative_path in (
            "scripts/launch_npc_voice_studio.ps1",
            "scripts/bootstrap_runtime.ps1",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('PYTHONDONTWRITEBYTECODE = "1"', source)

    def test_launcher_uses_milestone_progress_and_requires_runtime_marker(self) -> None:
        source = (ROOT / "scripts" / "launch_npc_voice_studio.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('$script:ProgressBar.Style = "Continuous"', source)
        self.assertNotIn('$Progress.Style = "Marquee"', source)
        self.assertIn("Update-SetupElapsedTime", source)
        self.assertIn("$RuntimeMarkerValid = Test-BasicRuntimeMarker", source)
        self.assertIn(
            "$BootstrapExit -ne 0 -or -not $RuntimeMarkerValid", source
        )
        self.assertIn('Arguments @("-u", $ModelScript', source)
        self.assertIn("--result-file", source)
        self.assertIn('$CheckState -eq "setup_required"', source)
        self.assertIn('$InstallState -eq "ready"', source)
        self.assertIn("Test-BasicModelMarker", source)
        self.assertIn("separate CC-BY-NC/non-commercial terms", source)
        self.assertIn("THIRD_PARTY_NOTICES.md", source)
        self.assertNotIn("Show-ModelLicenseDialog", source)
        self.assertNotIn("--license-status", source)
        self.assertNotIn("--acknowledge-license", source)
        self.assertNotIn("AcceptModelLicense", source)

    def test_application_and_model_licenses_are_separate(self) -> None:
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0", license_text)
        self.assertIn("CC-BY-NC", notices)
        self.assertIn("not licensed by", notices)
        self.assertIn("not bundled in the installer", notices)


if __name__ == "__main__":
    unittest.main()
