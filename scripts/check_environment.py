from importlib import import_module, metadata
from pathlib import Path
import sys


EXPECTED_PACKAGES = {
    "accelerate": "1.14.0",
    "gradio": "6.22.0",
    "huggingface-hub": "1.26.0",
    "librosa": "0.11.0",
    "numpy": "2.4.6",
    "omnivoice": "0.2.1",
    "pydub": "0.25.1",
    "soundfile": "0.14.0",
    "tensorboardX": "2.6.5",
    "torch": "2.8.0+cu128",
    "torchaudio": "2.8.0+cu128",
    "transformers": "5.14.1",
    "webdataset": "1.0.2",
}

IMPORT_NAMES = {
    "huggingface-hub": "huggingface_hub",
    "tensorboardX": "tensorboardX",
}


def main() -> int:
    errors: list[str] = []

    if sys.version_info[:2] != (3, 11):
        errors.append(f"Expected Python 3.11, found {sys.version.split()[0]}.")

    for package_name, expected_version in EXPECTED_PACKAGES.items():
        try:
            installed_version = metadata.version(package_name)
            import_module(IMPORT_NAMES.get(package_name, package_name))
        except (metadata.PackageNotFoundError, ImportError) as exc:
            errors.append(f"{package_name} is unavailable: {exc}")
            continue

        status = "OK" if installed_version == expected_version else "MISMATCH"
        print(f"{package_name}={installed_version} [{status}]")
        if installed_version != expected_version:
            errors.append(
                f"Expected {package_name} {expected_version}, found "
                f"{installed_version}."
            )

    for unwanted_package in ("f5-tts", "torchcodec"):
        try:
            installed_version = metadata.version(unwanted_package)
        except metadata.PackageNotFoundError:
            print(f"{unwanted_package}=not installed [OK]")
        else:
            errors.append(
                f"Unexpected package {unwanted_package} {installed_version} is installed."
            )

    import torch

    print(f"torch CUDA build={torch.version.cuda}")
    print(f"CUDA available={torch.cuda.is_available()}")
    if torch.version.cuda != "12.8":
        errors.append(f"Expected Torch CUDA build 12.8, found {torch.version.cuda}.")
    if not torch.cuda.is_available():
        errors.append("CUDA is not available to PyTorch.")
    else:
        print(f"GPU={torch.cuda.get_device_name(0)}")

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    from src.app_paths import APP_PATHS

    print(f"application data={APP_PATHS.root}")
    if APP_PATHS.root == project_root or project_root in APP_PATHS.root.parents:
        errors.append("Application data resolves inside the source repository.")

    if errors:
        print("\nEnvironment check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("\nEnvironment check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
