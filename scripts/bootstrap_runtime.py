import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Mapping


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from src.app_paths import resolve_app_paths
from src.setup_progress import FIRST_RUN_DETAIL, write_setup_progress


APP_NAME = "NPC Voice Studio"
RUNTIME_MANIFEST = json.loads(
    (SOURCE_ROOT / "runtime_manifest.json").read_text(encoding="utf-8")
)
APPLICATION_VERSION = RUNTIME_MANIFEST["application_version"]
RUNTIME_SCHEMA_VERSION = RUNTIME_MANIFEST["runtime_schema_version"]
PYTHON_VERSION = RUNTIME_MANIFEST["python_version"]
UV_VERSION = RUNTIME_MANIFEST["uv_version"]


@dataclass(frozen=True)
class RuntimeLayout:
    app_root: Path
    runtime_root: Path
    project_root: Path
    venv_root: Path
    venv_python: Path
    marker_path: Path
    models_root: Path
    voice_profiles: Path
    generated_audio: Path
    logs: Path


def resolve_runtime_layout(
    source_root: str | Path,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform_name: str | None = None,
) -> RuntimeLayout:
    """Resolve the Windows app-owned runtime separately from source and data."""
    values = os.environ if environ is None else environ
    user_home = Path.home() if home is None else Path(home)
    current_platform = os.name if platform_name is None else platform_name
    if current_platform != "nt":
        raise RuntimeError("The packaged runtime bootstrap currently supports Windows only.")

    app_paths = resolve_app_paths(values, user_home, current_platform)
    app_root = app_paths.root

    source = Path(source_root).resolve()
    if app_root == source or source in app_root.parents:
        raise RuntimeError("The managed runtime cannot be stored in the source tree.")

    runtime_root = app_root / "runtime"
    project_root = runtime_root / "project"
    venv_root = project_root / ".venv"
    return RuntimeLayout(
        app_root=app_root,
        runtime_root=runtime_root,
        project_root=project_root,
        venv_root=venv_root,
        venv_python=venv_root / "Scripts" / "python.exe",
        marker_path=runtime_root / "runtime_ready.json",
        models_root=app_paths.models,
        voice_profiles=app_paths.voice_profiles,
        generated_audio=app_paths.generated_audio,
        logs=app_paths.logs,
    )


def lockfile_sha256(lockfile: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(lockfile).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_marker(lockfile: str | Path) -> dict[str, object]:
    marker: dict[str, object] = {
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "python_version": PYTHON_VERSION,
        "uv_version": UV_VERSION,
        "lockfile_sha256": lockfile_sha256(lockfile),
        "platform": "windows-x86_64",
    }
    source_marker = _read_source_marker(Path(lockfile).parent / "app_source.json")
    if source_marker:
        marker["application_version"] = source_marker["application_version"]
        marker["source_sha256"] = source_marker["source_sha256"]
    return marker


def runtime_is_ready(layout: RuntimeLayout, lockfile: str | Path) -> bool:
    if not layout.venv_python.is_file() or not layout.marker_path.is_file():
        return False
    try:
        marker = json.loads(layout.marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    expected = expected_marker(lockfile)
    return all(marker.get(key) == value for key, value in expected.items())


def model_cache_environment(layout: RuntimeLayout) -> dict[str, str]:
    return {
        "HF_HOME": str(layout.models_root),
        "HF_HUB_CACHE": str(layout.models_root / "hub"),
        "HF_XET_CACHE": str(layout.models_root / "xet"),
    }


def repair_runtime(layout: RuntimeLayout) -> None:
    """Remove only the managed environment and marker, never user data/models."""
    if layout.venv_root.exists():
        resolved_venv = layout.venv_root.resolve()
        resolved_project = layout.project_root.resolve()
        if resolved_project not in resolved_venv.parents:
            raise RuntimeError("Refusing to remove a runtime outside its project.")
        shutil.rmtree(resolved_venv)
    layout.marker_path.unlink(missing_ok=True)


def _verify_writable(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / f".write-test-{os.getpid()}"
    try:
        probe.write_text("ok", encoding="ascii")
    except OSError as exc:
        raise RuntimeError(f"Runtime directory is not writable: {directory}") from exc
    finally:
        probe.unlink(missing_ok=True)


def _read_source_marker(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    required = ("application_version", "source_sha256")
    if not isinstance(value, dict) or not all(value.get(key) for key in required):
        return None
    return value


def _source_payload_files(source_root: Path) -> list[Path]:
    files = [
        source_root / "app.py",
        source_root / "pyproject.toml",
        source_root / "uv.lock",
        source_root / "runtime_manifest.json",
        source_root / "assets" / "app_icon.png",
        source_root / "scripts" / "check_environment.py",
        source_root / "scripts" / "setup_model.py",
    ]
    files.extend(sorted((source_root / "src").glob("*.py")))
    return files


def _source_payload_sha256(source_root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(source_root).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _stage_project(source_root: Path, layout: RuntimeLayout) -> None:
    payload_files = _source_payload_files(source_root)
    missing = [path for path in payload_files if not path.is_file()]
    if missing:
        raise RuntimeError(f"Required runtime source is missing: {missing[0]}")

    layout.project_root.mkdir(parents=True, exist_ok=True)
    for filename in ("app.py", "pyproject.toml", "uv.lock", "runtime_manifest.json"):
        source = source_root / filename
        shutil.copy2(source, layout.project_root / filename)

    source_destination = layout.project_root / "src"
    if source_destination.exists():
        shutil.rmtree(source_destination)
    shutil.copytree(
        source_root / "src",
        source_destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    assets_destination = layout.project_root / "assets"
    if assets_destination.exists():
        shutil.rmtree(assets_destination)
    assets_destination.mkdir()
    shutil.copy2(
        source_root / "assets" / "app_icon.png",
        assets_destination / "app_icon.png",
    )

    scripts_destination = layout.project_root / "scripts"
    if scripts_destination.exists():
        shutil.rmtree(scripts_destination)
    scripts_destination.mkdir()
    for filename in ("check_environment.py", "setup_model.py"):
        shutil.copy2(source_root / "scripts" / filename, scripts_destination / filename)

    source_marker = {
        "application_version": APPLICATION_VERSION,
        "source_sha256": _source_payload_sha256(source_root, payload_files),
        "staged_at_utc": datetime.now(UTC).isoformat(),
        "files": [path.relative_to(source_root).as_posix() for path in payload_files],
    }
    (layout.project_root / "app_source.json").write_text(
        json.dumps(source_marker, indent=2) + "\n",
        encoding="utf-8",
    )


def _runtime_environment(layout: RuntimeLayout) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(model_cache_environment(layout))
    environment["NPC_VOICE_STUDIO_DATA_DIR"] = str(layout.app_root)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    # The installer-owned source tree is immutable; keep bytecode in memory.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["UV_CACHE_DIR"] = str(layout.runtime_root / "uv-cache")
    environment["UV_DATA_DIR"] = str(layout.runtime_root / "uv-data")
    environment["UV_PYTHON_INSTALL_DIR"] = str(layout.runtime_root / "python")
    environment["UV_PYTHON_BIN_DIR"] = str(layout.runtime_root / "python-bin")
    environment["UV_PROJECT_ENVIRONMENT"] = str(layout.venv_root)
    return environment


def _run_checked(command: list[str], environment: Mapping[str, str]) -> None:
    # Keep native tool output in chronological order in setup.log. The launcher
    # still keeps the UI clean and displays only structured status milestones.
    completed = subprocess.run(
        command,
        env=environment,
        check=False,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {command[0]}"
        )


def _write_status(
    path: Path | None,
    message: str,
    percent: int,
    detail: str = "",
) -> None:
    write_setup_progress(path, message, percent, detail)


def _verify_managed_python(layout: RuntimeLayout, environment: Mapping[str, str]) -> None:
    checker = layout.project_root / "scripts" / "check_environment.py"
    _run_checked([str(layout.venv_python), str(checker)], environment)

    command = [
        str(layout.venv_python),
        "-c",
        "import platform; print(platform.python_version())",
    ]
    result = subprocess.run(
        command,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != PYTHON_VERSION:
        raise RuntimeError(
            f"Managed Python verification failed; expected {PYTHON_VERSION}."
        )


def _write_ready_marker(layout: RuntimeLayout, lockfile: Path) -> None:
    marker = expected_marker(lockfile)
    marker["verified_at_utc"] = datetime.now(UTC).isoformat()
    temporary = layout.marker_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, layout.marker_path)


def install_or_verify_runtime(
    source_root: Path,
    uv_path: Path,
    layout: RuntimeLayout,
    repair: bool = False,
    status_file: Path | None = None,
) -> None:
    _write_status(status_file, "Checking managed AI runtime...", 16)
    _verify_writable(layout.runtime_root)
    _stage_project(source_root, layout)
    lockfile = layout.project_root / "uv.lock"
    environment = _runtime_environment(layout)

    if repair:
        repair_runtime(layout)

    ready = runtime_is_ready(layout, lockfile)
    if ready:
        try:
            _write_status(status_file, "Verifying NVIDIA GPU...", 65)
            _verify_managed_python(layout, environment)
            _write_status(status_file, "Managed AI runtime is ready.", 70)
            print("Managed runtime is ready; dependency sync skipped.")
            return
        except RuntimeError:
            layout.marker_path.unlink(missing_ok=True)
            print("Runtime verification failed; repairing from the frozen lockfile.")

    sync_command = [
        str(uv_path),
        "sync",
        "--frozen",
        "--no-dev",
        "--no-install-project",
        "--managed-python",
        "--python",
        PYTHON_VERSION,
        "--project",
        str(layout.project_root),
    ]
    _write_status(
        status_file,
        "Downloading and installing AI runtime (~3.2 GB)...",
        25,
        FIRST_RUN_DETAIL,
    )
    _run_checked(sync_command, environment)
    if not layout.venv_python.is_file():
        raise RuntimeError("uv completed without creating the managed environment.")

    _write_status(status_file, "Verifying NVIDIA GPU...", 65)
    _verify_managed_python(layout, environment)
    _write_ready_marker(layout, lockfile)
    _write_status(status_file, "Managed AI runtime is ready.", 70)
    print(f"Managed runtime verified: {layout.venv_root}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare NPC Voice Studio runtime.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--uv-path", type=Path, required=True)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--status-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    uv_path = args.uv_path.resolve()
    layout = resolve_runtime_layout(source_root)

    print("Runtime layout:")
    for name, value in asdict(layout).items():
        print(f"  {name}: {value}")

    install_or_verify_runtime(
        source_root,
        uv_path,
        layout,
        repair=args.repair,
        status_file=args.status_file,
    )
    if args.no_launch:
        return 0

    environment = _runtime_environment(layout)
    app_path = layout.project_root / "app.py"
    _write_status(args.status_file, "Starting NPC Voice Studio...", 96)
    completed = subprocess.run(
        [str(layout.venv_python), str(app_path)],
        env=environment,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"NPC Voice Studio bootstrap failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
