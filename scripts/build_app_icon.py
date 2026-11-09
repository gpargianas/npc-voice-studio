"""Build the multi-resolution Windows icon from the release PNG asset."""

from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = PROJECT_ROOT / "assets" / "app_icon.png"
OUTPUT_PATH = PROJECT_ROOT / "assets" / "app_icon.ico"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    if not SOURCE_PATH.is_file():
        raise FileNotFoundError(f"Source icon not found: {SOURCE_PATH}")

    with Image.open(SOURCE_PATH) as source:
        if source.width != source.height:
            raise ValueError("The application icon source must be square.")

        # RGBA preserves source transparency, while Pillow uses high-quality
        # Lanczos resampling when writing each requested ICO resolution.
        icon = source.convert("RGBA")
        icon.save(
            OUTPUT_PATH,
            format="ICO",
            sizes=[(size, size) for size in ICON_SIZES],
            bitmap_format="png",
        )

    with Image.open(OUTPUT_PATH) as result:
        generated_sizes = {width for width, height in result.ico.sizes() if width == height}
    if generated_sizes != set(ICON_SIZES):
        raise RuntimeError(
            f"ICO sizes do not match the release set: {sorted(generated_sizes)}"
        )

    print(f"Created {OUTPUT_PATH} with sizes: {', '.join(map(str, ICON_SIZES))}")


if __name__ == "__main__":
    main()
