import argparse
import base64
import csv
import json
import mimetypes
import os
import re
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_CSV = SCRIPT_DIR / "personnel_claude.csv"
DEFAULT_ERROR_DIR = SCRIPT_DIR / "personnel_errors"
MODEL = "claude-haiku-4-5-20251001"
DELAY_SECONDS = 0.5

INPUT_FOLDERS = [
    (
        "LNER_Birmingham",
        Path(
            r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\RawData\LNER\Birmingham"
        ),
    ),
    (
        "GWR_BirminghamStation_Sample_1898_1913",
        Path(
            r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\RawData\GWR\BirminghamStation\Sample 1898-1913"
        ),
    ),
    (
        "GWR_BirminghamStation_Sample_1910_1915",
        Path(
            r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\RawData\GWR\BirminghamStation\Sample 1910-1915"
        ),
    ),
    (
        "GWR_AylesburyStation",
        Path(
            r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\RawData\GWR\AylesburyStation"
        ),
    ),
]

CSV_COLUMNS = [
    "source_file",
    "source_folder",
    "company",
    "format",
    "station",
    "name",
    "dob",
    "entry_date",
    "entry_year",
    "grade_pit_gd_date",
    "grade_shunter_date",
    "grade_gds_gd_date",
    "seniority",
    "staff_no",
    "grade",
    "from_station",
    "from_date",
    "to_station",
    "to_date",
    "remarks",
    "locations",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".JPG", ".JPEG"}

SYSTEM_PROMPT = """You are a precise data extractor for Victorian railway personnel records.
Always return valid JSON only. No explanation, no markdown, no code blocks."""

USER_PROMPT = """This is a Victorian railway personnel register page. Extract every 
worker record visible on this page.

FORMAT A (LNWR Guards register) has columns:
Name | Date of Birth | Date Entered Service | Date Made Pit Goods Guard |
Date Made Shunter | Date Made Goods Guard | Position in Seniority |
Remarks (right page - free text with transfer locations and dates)

FORMAT B (GWR Weekly Staff register) has columns:
Name | Staff Register Number | Grade | Date Entering Service |
Multiple wage columns with dates | FROM Station | FROM Date |
TO Station | TO Date | Remarks

Rules:
- Skip cover pages, index pages, and blank pages — return empty workers array
- For Remarks extract all location names and dates mentioned
- Dates format DD.MM.YY where YY is 1860s-1920s
- Grade promotion dates are the key variable — extract carefully

Return ONLY valid JSON, no markdown:
{
  "format": "A" or "B",
  "station": "station name from header if visible",
  "workers": [
    {
      "name": "Harris",
      "dob": "21.10.56",
      "entry_date": "1.10.79",
      "entry_year": 1879,
      "grade_pit_gd_date": null,
      "grade_shunter_date": "31.10.79",
      "grade_gds_gd_date": "1.2.86",
      "seniority": null,
      "staff_no": null,
      "grade": null,
      "from_station": null,
      "from_date": null,
      "to_station": null,
      "to_date": null,
      "remarks": "full remarks text here",
      "locations": ["Walsall", "Berwick"]
    }
  ]
}
"""


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def null_to_empty(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(clean_text(item) for item in value if clean_text(item))
    return value


def source_key(source_folder, source_file):
    return f"{source_folder}/{source_file}"


def load_done_sources(output_csv):
    if not output_csv.exists():
        return set()
    with output_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return {
            source_key(row.get("source_folder", ""), row.get("source_file", ""))
            for row in reader
            if row.get("source_file")
        }


def ensure_csv(output_csv):
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        return
    with output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()


def list_images(folder):
    return sorted(
        path for path in folder.iterdir() if path.is_file() and path.suffix in IMAGE_EXTENSIONS
    )


def image_media_type(path):
    media_type, _ = mimetypes.guess_type(path.name)
    return media_type or "image/jpeg"


def encode_image(path):
    return base64.b64encode(path.read_bytes()).decode("ascii")


def get_response_text(message):
    parts = []
    for block in message.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def parse_json_response(raw_text):
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def save_error(error_dir, source_folder, source_file, raw_text):
    error_dir.mkdir(parents=True, exist_ok=True)
    safe_folder = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_folder).strip("_")
    safe_file = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_file).strip("_")
    path = error_dir / f"{safe_folder}__{safe_file}.txt"
    path.write_text(raw_text, encoding="utf-8")


def call_claude(client, image_path):
    return client.messages.create(
        model=MODEL,
        max_tokens=12000,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_media_type(image_path),
                            "data": encode_image(image_path),
                        },
                    },
                    {"type": "text", "text": USER_PROMPT},
                ],
            }
        ],
    )


def infer_company(source_folder):
    return "LNWR" if source_folder.startswith("LNER") else "GWR"


def normalize_worker_row(worker, response_data, source_folder, source_file):
    row = {
        "source_file": source_file,
        "source_folder": source_folder,
        "company": infer_company(source_folder),
        "format": null_to_empty(response_data.get("format")),
        "station": null_to_empty(response_data.get("station")),
    }
    for column in CSV_COLUMNS:
        row.setdefault(column, "")

    row.update(
        {
            "name": null_to_empty(worker.get("name")),
            "dob": null_to_empty(worker.get("dob")),
            "entry_date": null_to_empty(worker.get("entry_date")),
            "entry_year": null_to_empty(worker.get("entry_year")),
            "grade_pit_gd_date": null_to_empty(worker.get("grade_pit_gd_date")),
            "grade_shunter_date": null_to_empty(worker.get("grade_shunter_date")),
            "grade_gds_gd_date": null_to_empty(worker.get("grade_gds_gd_date")),
            "seniority": null_to_empty(worker.get("seniority")),
            "staff_no": null_to_empty(worker.get("staff_no")),
            "grade": null_to_empty(worker.get("grade")),
            "from_station": null_to_empty(worker.get("from_station")),
            "from_date": null_to_empty(worker.get("from_date")),
            "to_station": null_to_empty(worker.get("to_station")),
            "to_date": null_to_empty(worker.get("to_date")),
            "remarks": null_to_empty(worker.get("remarks")),
            "locations": null_to_empty(worker.get("locations")),
        }
    )
    return {column: row.get(column, "") for column in CSV_COLUMNS}


def normalize_empty_page_row(response_data, source_folder, source_file):
    row = {column: "" for column in CSV_COLUMNS}
    row.update(
        {
            "source_file": source_file,
            "source_folder": source_folder,
            "company": infer_company(source_folder),
            "format": null_to_empty(response_data.get("format")),
            "station": null_to_empty(response_data.get("station")),
        }
    )
    return row


def append_workers(output_csv, source_folder, source_file, response_data):
    workers = response_data.get("workers") or []
    if not isinstance(workers, list):
        raise ValueError("Claude response field 'workers' is not a list.")

    with output_csv.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        if not workers:
            writer.writerow(normalize_empty_page_row(response_data, source_folder, source_file))
            return 0
        for worker in workers:
            if not isinstance(worker, dict):
                continue
            writer.writerow(normalize_worker_row(worker, response_data, source_folder, source_file))
    return sum(1 for worker in workers if isinstance(worker, dict))


def build_client():
    load_dotenv(SCRIPT_DIR / ".env")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to the environment or to .env in the script directory."
        )
    return Anthropic(api_key=api_key)


def collect_images():
    queued = []
    for source_folder, folder in INPUT_FOLDERS:
        if not folder.exists():
            print(f"{source_folder}: input folder not found: {folder}")
            continue
        for image_path in list_images(folder):
            queued.append((source_folder, image_path))
    return queued


def process_files(output_csv, error_dir):
    ensure_csv(output_csv)
    done_sources = load_done_sources(output_csv)
    client = build_client()
    images = collect_images()

    processed = 0
    skipped = 0
    failed = 0
    total_workers = 0

    for index, (source_folder, image_path) in enumerate(images, start=1):
        source_file = image_path.name
        if source_key(source_folder, source_file) in done_sources:
            skipped += 1
            print(f"Processing {index}/{len(images)}: {source_file} -> skipped")
            continue

        raw_text = ""
        try:
            message = call_claude(client, image_path)
            raw_text = get_response_text(message)
            response_data = parse_json_response(raw_text)
            worker_count = append_workers(output_csv, source_folder, source_file, response_data)
            done_sources.add(source_key(source_folder, source_file))
            processed += 1
            total_workers += worker_count
            print(f"Processing {index}/{len(images)}: {source_file} -> {worker_count} workers")
        except Exception as exc:
            failed += 1
            error_text = raw_text or f"{type(exc).__name__}: {exc}"
            save_error(error_dir, source_folder, source_file, error_text)
            print(f"Processing {index}/{len(images)}: {source_file} -> failed")

        time.sleep(DELAY_SECONDS)

    print()
    print(f"Files processed: {processed}")
    print(f"Files skipped: {skipped}")
    print(f"Files failed: {failed}")
    print(f"Total workers: {total_workers}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract LNWR/GWR personnel records directly from JPGs with Claude."
    )
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--error-dir", type=Path, default=DEFAULT_ERROR_DIR)
    args = parser.parse_args()

    process_files(args.output_csv, args.error_dir)


if __name__ == "__main__":
    main()
