import csv
from dataclasses import dataclass
import os
from pathlib import Path
import re
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile


_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class BatchCsvError(ValueError):
    """Raised when an uploaded dialogue CSV is not safe to generate."""


@dataclass(frozen=True)
class BatchRow:
    filename: str
    text: str


def sanitize_wav_filename(filename: str) -> str:
    """Convert one user filename to a simple WAV name with no path parts."""
    name = filename.strip()
    if name.lower().endswith(".wav"):
        name = name[:-4]

    # A conservative allow-list prevents traversal and Windows-invalid paths.
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_-.")
    if not safe_stem:
        raise BatchCsvError("Filename must contain letters or numbers.")
    if len(safe_stem) > 120:
        raise BatchCsvError("Filename must be 120 characters or fewer.")
    if safe_stem.upper() in _RESERVED_WINDOWS_NAMES:
        safe_stem = f"_{safe_stem}"

    return f"{safe_stem}.wav"


def parse_dialogue_csv(csv_path: str | Path) -> list[BatchRow]:
    """Read and validate a UTF-8 CSV containing filename and text columns."""
    if not csv_path:
        raise BatchCsvError("Select a dialogue CSV first.")

    path = Path(csv_path)
    if path.suffix.lower() != ".csv":
        raise BatchCsvError("Only .csv files are supported.")

    rows: list[BatchRow] = []
    errors: list[str] = []
    seen_filenames: dict[str, int] = {}

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.reader(csv_file)
            try:
                raw_headers = next(reader)
            except StopIteration as exc:
                raise BatchCsvError("The CSV is empty.") from exc

            headers = [header.strip() for header in raw_headers]
            if len(headers) != 2 or set(headers) != {"filename", "text"}:
                raise BatchCsvError(
                    'CSV headers must be exactly "filename" and "text".'
                )

            filename_index = headers.index("filename")
            text_index = headers.index("text")

            for line_number, values in enumerate(reader, start=2):
                if not values or all(not value.strip() for value in values):
                    continue
                if len(values) != 2:
                    errors.append(
                        f"Row {line_number}: expected exactly 2 columns."
                    )
                    continue

                raw_filename = values[filename_index].strip()
                text = values[text_index]
                if not raw_filename:
                    errors.append(f"Row {line_number}: filename is required.")
                    continue
                if not text.strip():
                    errors.append(f"Row {line_number}: text is required.")
                    continue

                try:
                    safe_filename = sanitize_wav_filename(raw_filename)
                except BatchCsvError as exc:
                    errors.append(f"Row {line_number}: {exc}")
                    continue

                duplicate_key = safe_filename.casefold()
                first_line = seen_filenames.get(duplicate_key)
                if first_line is not None:
                    errors.append(
                        f'Rows {first_line} and {line_number}: duplicate output '
                        f'filename "{safe_filename}".'
                    )
                    continue

                seen_filenames[duplicate_key] = line_number
                rows.append(BatchRow(safe_filename, text))
    except UnicodeDecodeError as exc:
        raise BatchCsvError("The CSV must be encoded as UTF-8.") from exc
    except csv.Error as exc:
        raise BatchCsvError(f"Could not parse the CSV: {exc}") from exc
    except OSError as exc:
        raise BatchCsvError("Could not read the CSV file.") from exc

    if errors:
        visible_errors = errors[:20]
        if len(errors) > len(visible_errors):
            visible_errors.append(f"...and {len(errors) - len(visible_errors)} more.")
        raise BatchCsvError(
            "CSV validation failed:\n" + "\n".join(visible_errors)
        )
    if not rows:
        raise BatchCsvError("The CSV contains no dialogue rows.")

    return rows


def validate_batch_table(table: object) -> list[BatchRow]:
    """Validate the current editable preview instead of rereading its CSV."""
    if not isinstance(table, list) or not table:
        raise BatchCsvError("The dialogue table contains no rows.")

    rows: list[BatchRow] = []
    errors: list[str] = []
    seen_filenames: dict[str, int] = {}
    for row_number, values in enumerate(table, start=1):
        if not isinstance(values, (list, tuple)) or len(values) < 2:
            errors.append(f"Row {row_number}: expected filename and dialogue.")
            continue

        filename = values[0]
        text = values[1]
        if not isinstance(filename, str) or not filename.strip():
            errors.append(f"Row {row_number}: filename is required.")
            continue
        if not isinstance(text, str) or not text.strip():
            errors.append(f"Row {row_number}: dialogue is required.")
            continue

        try:
            safe_filename = sanitize_wav_filename(filename)
        except BatchCsvError as exc:
            errors.append(f"Row {row_number}: {exc}")
            continue
        # Imported filenames are already normalized. Reject any later edit that
        # would need sanitizing rather than silently changing its output path.
        if safe_filename != filename:
            errors.append(
                f'Row {row_number}: invalid output filename "{filename}".'
            )
            continue

        duplicate_key = safe_filename.casefold()
        first_row = seen_filenames.get(duplicate_key)
        if first_row is not None:
            errors.append(
                f'Rows {first_row} and {row_number}: duplicate output '
                f'filename "{safe_filename}".'
            )
            continue

        seen_filenames[duplicate_key] = row_number
        rows.append(BatchRow(safe_filename, text))

    if errors:
        visible_errors = errors[:20]
        if len(errors) > len(visible_errors):
            visible_errors.append(f"...and {len(errors) - len(visible_errors)} more.")
        raise BatchCsvError(
            "Dialogue table validation failed:\n" + "\n".join(visible_errors)
        )
    if not rows:
        raise BatchCsvError("The dialogue table contains no rows.")
    return rows


def batch_output_path(batch_directory: str | Path, filename: str) -> Path:
    """Resolve one output while enforcing direct containment in the batch."""
    root = Path(batch_directory).resolve()
    output = (root / filename).resolve()
    if output.parent != root or output.suffix.lower() != ".wav":
        raise BatchCsvError("Invalid batch output filename.")
    return output


def create_batch_zip(
    batch_directory: str | Path,
    successful_files: list[str | Path],
) -> Path:
    """Archive successful WAVs at the ZIP root using clean filenames."""
    root = Path(batch_directory).resolve()
    valid_files: list[Path] = []
    for file_path in successful_files:
        resolved = Path(file_path).resolve()
        if (
            resolved.parent == root
            and resolved.suffix.lower() == ".wav"
            and resolved.is_file()
        ):
            valid_files.append(resolved)

    if not valid_files:
        raise BatchCsvError("No successful WAV files are available to archive.")

    zip_path = root / "batch.zip"
    temporary_zip = root / f".batch.{uuid4().hex}.tmp.zip"
    try:
        with ZipFile(temporary_zip, "w", compression=ZIP_DEFLATED) as archive:
            for file_path in valid_files:
                archive.write(file_path, arcname=file_path.name)
        os.replace(temporary_zip, zip_path)
    except Exception:
        temporary_zip.unlink(missing_ok=True)
        # Never leave an older archive available after a refresh failure.
        zip_path.unlink(missing_ok=True)
        raise
    return zip_path
