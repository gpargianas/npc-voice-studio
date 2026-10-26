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


APP_NAME = "NPC Voice Studio"
RUNTIME_SCHEMA_VERSION = 1
PYTHON_VERSION = "3.11.15"
UV_VERSION = "0.13.5"


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

    override = values.get("NPC_VOICE_STUDIO_DATA_DIR")
    if override:
        app_root = Path(override).expanduser().resolve()
    else:
        local_app_data = values.get("LOCALAPPDATA")
        base = (
            Path(local_app_data)
            if local_app_data
            else user_home / "AppData" / "Local"
        )
        app_root = (base / APP_NAME).resolve()

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
        models_root=app_root / "models",
        voice_profiles=app_root / "voice_profiles",
        generated_audio=app_root / "generated_audio",
        logs=app_root / "logs",
    )


def lockfile_sha256(lockfile: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(lockfile).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_marker(lockfile: str | Path) -> dict[str, object]:
    return {
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "python_version": PYTHON_VERSION,
        "uv_version": UV_VERSION,
        "lockfile_sha256": lockfile_sha256(lockfile),
        "platform": "windows-x86_64",
    }


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


def _stage_project(source_root: Path, layout: RuntimeLayout) -> None:
    layout.project_root.mkdir(parents=True, exist_ok=True)
    for filename in ("app.py", "pyproject.toml", "uv.lock"):
        source = source_root / filename
        if not source.is_file():
            raise RuntimeError(f"Required runtime source is missing: {source}")
        shutil.copy2(source, layout.project_root / filename)

    for directory in ("src", "scripts"):
        destination = layout.project_root / directory
        destination.mkdir(parents=True, exist_ok=True)
        if directory == "src":
            shutil.copytree(
                source_root / directory,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            checker = source_root / directory / "check_environment.py"
            if not checker.is_file():
                raise RuntimeError(f"Required runtime checker is missing: {checker}")
            shutil.copy2(checker, destination / checker.name)


def _runtime_environment(layout: RuntimeLayout) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(model_cache_environment(layout))
    environment["NPC_VOICE_STUDIO_DATA_DIR"] = str(layout.app_root)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_CACHE_DIR"] = str(layout.runtime_root / "uv-cache")
    environment["UV_PYTHON_INSTALL_DIR"] = str(layout.runtime_root / "python")
    environment["UV_PROJECT_ENVIRONMENT"] = str(layout.venv_root)
    return environment


def _run_checked(command: list[str], environment: Mapping[str, str]) -> None:
    completed = subprocess.run(command, env=environment, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {command[0]}"
        )


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
) -> None:
    _verify_writable(layout.runtime_root)
    _stage_project(source_root, layout)
    lockfile = layout.project_root / "uv.lock"
    environment = _runtime_environment(layout)

    if repair:
        repair_runtime(layout)

    ready = runtime_is_ready(layout, lockfile)
    if ready:
        try:
            _verify_managed_python(layout, environment)
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
    _run_checked(sync_command, environment)
    if not layout.venv_python.is_file():
        raise RuntimeError("uv completed without creating the managed environment.")

    _verify_managed_python(layout, environment)
    _write_ready_marker(layout, lockfile)
    print(f"Managed runtime verified: {layout.venv_root}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare NPC Voice Studio runtime.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--uv-path", type=Path, required=True)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    uv_path = args.uv_path.resolve()
    layout = resolve_runtime_layout(source_root)

    print("Runtime layout:")
    for name, value in asdict(layout).items():
        print(f"  {name}: {value}")

    install_or_verify_runtime(source_root, uv_path, layout, repair=args.repair)
    if args.no_launch:
        return 0

    environment = _runtime_environment(layout)
    app_path = layout.project_root / "app.py"
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
