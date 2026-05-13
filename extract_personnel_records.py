import argparse
import csv
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local convenience only
    load_dotenv = None

try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
except ImportError:  # pragma: no cover - depends on local environment
    DocumentAnalysisClient = None
    AzureKeyCredential = None


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_CSV = SCRIPT_DIR / "personnel_records_raw.csv"
DEFAULT_JSON_DIR = SCRIPT_DIR / "personnel_json"

INPUT_FOLDERS = [
    (
        "LNER_Birmingham",
        Path(
            r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\RawData\LNER\Birmingham"
        ),
    ),
    (
        "GWR_BirminghamStation",
        Path(
            r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\RawData\GWR\BirminghamStation"
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
    "name_raw",
    "dob_raw",
    "staff_register_number",
    "grade_raw",
    "grade_clean",
    "entry_date_raw",
    "entry_year",
    "grade_pit_gd_date",
    "grade_shunter_date",
    "grade_gds_gd_date",
    "seniority_position",
    "from_station",
    "from_date",
    "to_station",
    "to_date",
    "remarks_raw",
    "locations_mentioned",
]

KEY_FIELDS = [
    "name_raw",
    "entry_date_raw",
    "entry_year",
    "grade_clean",
    "from_station",
    "to_station",
    "remarks_raw",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".JPG", ".JPEG"}

GRADE_MAP = [
    (("ladporter", "ladport"), "Lad Porter"),
    (("horsekeeper", "horsekeeper"), "Horsekeeper"),
    (("signalman", "signalmen", "signal"), "Signalman"),
    (("shunter", "shuntr"), "Shunter"),
    (("foreman", "foremn"), "Foreman"),
    (("carman", "carmen", "cartman"), "Carman"),
    (("barman", "bar man"), "Barman"),
    (("porter",), "Porter"),
    (("clerk", "clerck"), "Clerk"),
]

PLACE_STOPWORDS = {
    "Transferred",
    "Transfer",
    "Returned",
    "Removed",
    "Resigned",
    "Dismissed",
    "Retired",
    "Died",
    "Dead",
    "Sick",
    "Ill",
    "Service",
    "Station",
    "Guard",
    "Goods",
    "Shunter",
    "Porter",
    "Carman",
    "Clerk",
    "Foreman",
    "Remarks",
    "Date",
    "From",
    "To",
}


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace(":selected:", " ")).strip()


def null_if_blank(value):
    value = clean_text(value)
    return value if value else "NULL"


def normalize_key(value):
    return re.sub(r"[^a-z0-9]+", "", clean_text(value).lower())


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def get_value(item, *names, default=None):
    for name in names:
        if isinstance(item, dict) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return default


def document_to_dict(result):
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if hasattr(result, "as_dict"):
        return result.as_dict()
    raise TypeError("Azure AnalyzeResult object cannot be serialized with this SDK version.")


def load_dotenv_if_present():
    if load_dotenv is not None:
        load_dotenv(SCRIPT_DIR / ".env")


def build_client():
    if DocumentAnalysisClient is None or AzureKeyCredential is None:
        raise RuntimeError(
            "azure-ai-formrecognizer is not installed. Install it with: "
            "pip install azure-ai-formrecognizer"
        )
    load_dotenv_if_present()
    endpoint = os.environ.get("AZURE_FORM_RECOGNIZER_ENDPOINT")
    key = os.environ.get("AZURE_FORM_RECOGNIZER_KEY")
    if not endpoint or not key:
        raise RuntimeError(
            "AZURE_FORM_RECOGNIZER_ENDPOINT and AZURE_FORM_RECOGNIZER_KEY must be set."
        )
    return DocumentAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))


def list_images(folder, test=False):
    images = sorted(
        path for path in folder.iterdir() if path.is_file() and path.suffix in IMAGE_EXTENSIONS
    )
    return images[:5] if test else images


def analysis_json_path(json_dir, source_folder, image_path):
    return json_dir / source_folder / f"{image_path.stem}_analysis.json"


def analyze_image(client, image_path):
    with image_path.open("rb") as handle:
        poller = client.begin_analyze_document("prebuilt-layout", document=handle)
    result = poller.result()
    return document_to_dict(result)


def ensure_csv(output_csv):
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        return
    with output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()


def load_done_sources(output_csv):
    if not output_csv.exists():
        return set()
    with output_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return {clean_text(row.get("source_file")) for row in reader if row.get("source_file")}


def append_rows(output_csv, rows):
    if not rows:
        return
    ensure_csv(output_csv)
    with output_csv.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        for row in rows:
            writer.writerow({column: row.get(column, "NULL") for column in CSV_COLUMNS})


def detect_format(document):
    content = clean_text(document.get("content", ""))
    key = normalize_key(content)
    if "weeklystaff" in key:
        return "B"
    if "goodsguard" in key or "goodsgds" in key or "pitgds" in key:
        return "A"
    return "A" if "seniority" in key else "B"


def infer_company(source_folder, content):
    source_key = source_folder.upper()
    content_key = content.upper()
    if "GWR" in source_key or "GREAT WESTERN" in content_key or "G.W.R" in content_key:
        return "GWR"
    return "LNWR"


def extract_entry_year(value):
    text = clean_text(value)
    if not text:
        return "NULL"
    match = re.search(r"\b(18\d{2}|19\d{2})\b", text)
    if match:
        return match.group(1)
    parts = re.findall(r"\d{1,2}", text)
    if not parts:
        return "NULL"
    year = int(parts[-1])
    if year <= 99:
        return str(1800 + year)
    return "NULL"


def clean_grade(value):
    text = clean_text(value)
    key = normalize_key(text)
    if not key:
        return "NULL"
    for variants, canonical in GRADE_MAP:
        if any(normalize_key(variant) in key for variant in variants):
            return canonical
    return text


def extract_locations(remarks):
    text = clean_text(remarks)
    if not text:
        return "NULL"

    candidates = []
    for match in re.finditer(
        r"\b(?:to|from|at|for)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})",
        text,
    ):
        candidates.append(match.group(1))

    for match in re.finditer(r"\b([A-Z][A-Za-z.'-]{2,}(?:\s+[A-Z][A-Za-z.'-]{2,})?)\b", text):
        candidates.append(match.group(1))

    places = []
    seen = set()
    for candidate in candidates:
        cleaned = clean_text(re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?\b.*$", "", candidate))
        words = [word for word in cleaned.split() if word not in PLACE_STOPWORDS]
        cleaned = " ".join(words).strip(" ,.;")
        if not cleaned or cleaned in PLACE_STOPWORDS:
            continue
        key = cleaned.lower()
        if key not in seen:
            places.append(cleaned)
            seen.add(key)
    return "; ".join(places) if places else "NULL"


def table_rows(document):
    rows = []
    for table in as_list(document.get("tables")):
        by_row = defaultdict(dict)
        max_col = 0
        for cell in as_list(table.get("cells")):
            row_index = get_value(cell, "rowIndex", "row_index", default=0)
            col_index = get_value(cell, "columnIndex", "column_index", default=0)
            content = clean_text(get_value(cell, "content", default=""))
            by_row[int(row_index)][int(col_index)] = content
            max_col = max(max_col, int(col_index))
        for row_index in sorted(by_row):
            rows.append([by_row[row_index].get(col_index, "") for col_index in range(max_col + 1)])
    return rows


def is_header_row(values):
    key = normalize_key(" ".join(values))
    header_bits = [
        "name",
        "dateofbirth",
        "dateentered",
        "weeklystaff",
        "staffregister",
        "wages",
        "remarks",
        "seniority",
    ]
    return sum(bit in key for bit in header_bits) >= 2


def plausible_name(value):
    text = clean_text(value)
    if not text or len(text) < 4:
        return False
    if re.fullmatch(r"[\d\s./-]+", text):
        return False
    if normalize_key(text) in {"name", "surname", "remarks"}:
        return False
    return bool(re.search(r"[A-Za-z]", text))


def pad(values, length):
    return list(values) + [""] * max(0, length - len(values))


def split_format_a_date_made(cells):
    grade_pit = ""
    grade_shunter = ""
    grade_gds = ""
    if clean_text(cells[4]) or clean_text(cells[5]):
        grade_pit, grade_shunter, grade_gds = cells[3], cells[4], cells[5]
    else:
        parts = re.split(r"\s{2,}|\|", cells[3])
        parts = [clean_text(part) for part in parts if clean_text(part)]
        grade_pit = parts[0] if len(parts) > 0 else cells[3]
        grade_shunter = parts[1] if len(parts) > 1 else ""
        grade_gds = parts[2] if len(parts) > 2 else ""
    return grade_pit, grade_shunter, grade_gds


def parse_format_a_rows(document):
    records = []
    for raw_cells in table_rows(document):
        cells = pad(raw_cells, 9)
        if is_header_row(cells) or not plausible_name(cells[0]):
            continue
        grade_pit, grade_shunter, grade_gds = split_format_a_date_made(cells)
        if len(raw_cells) >= 8:
            seniority = cells[7]
            remarks = " ".join(cell for cell in raw_cells[8:] if clean_text(cell))
        else:
            seniority = cells[5]
            remarks = " ".join(cell for cell in raw_cells[6:] if clean_text(cell))
        record = {
            "name_raw": cells[0],
            "dob_raw": cells[1],
            "entry_date_raw": cells[2],
            "entry_year": extract_entry_year(cells[2]),
            "grade_pit_gd_date": grade_pit,
            "grade_shunter_date": grade_shunter,
            "grade_gds_gd_date": grade_gds,
            "seniority_position": seniority,
            "remarks_raw": remarks,
            "locations_mentioned": extract_locations(remarks),
        }
        records.append(record)
    return records


def parse_format_b_rows(document):
    records = []
    for raw_cells in table_rows(document):
        cells = pad(raw_cells, 11)
        if is_header_row(cells) or not plausible_name(cells[0]):
            continue

        remarks = raw_cells[-1] if raw_cells else ""
        from_station, from_date, to_station, to_date = "", "", "", ""
        if len(raw_cells) >= 9:
            from_station, from_date, to_station, to_date = (
                raw_cells[-5],
                raw_cells[-4],
                raw_cells[-3],
                raw_cells[-2],
            )
        elif len(raw_cells) >= 8:
            from_station, from_date, to_station, to_date = cells[4], cells[5], cells[6], cells[7]

        record = {
            "name_raw": cells[0],
            "staff_register_number": cells[1],
            "grade_raw": cells[2],
            "grade_clean": clean_grade(cells[2]),
            "entry_date_raw": cells[3],
            "entry_year": extract_entry_year(cells[3]),
            "from_station": from_station,
            "from_date": from_date,
            "to_station": to_station,
            "to_date": to_date,
            "remarks_raw": remarks,
        }
        records.append(record)
    return records


def fallback_line_rows(document, fmt):
    lines = []
    for page in as_list(document.get("pages")):
        for line in as_list(page.get("lines")):
            text = clean_text(get_value(line, "content", default=""))
            if text and not is_header_row([text]):
                lines.append(text)

    records = []
    for line in lines:
        if not plausible_name(line):
            continue
        parts = re.split(r"\s{2,}|\t+", line)
        if len(parts) < 3:
            continue
        if fmt == "A":
            cells = pad(parts, 8)
            grade_pit, grade_shunter, grade_gds = split_format_a_date_made(cells)
            remarks = " ".join(cells[6:])
            records.append(
                {
                    "name_raw": cells[0],
                    "dob_raw": cells[1],
                    "entry_date_raw": cells[2],
                    "entry_year": extract_entry_year(cells[2]),
                    "grade_pit_gd_date": grade_pit,
                    "grade_shunter_date": grade_shunter,
                    "grade_gds_gd_date": grade_gds,
                    "seniority_position": cells[5],
                    "remarks_raw": remarks,
                    "locations_mentioned": extract_locations(remarks),
                }
            )
        else:
            cells = pad(parts, 10)
            records.append(
                {
                    "name_raw": cells[0],
                    "staff_register_number": cells[1],
                    "grade_raw": cells[2],
                    "grade_clean": clean_grade(cells[2]),
                    "entry_date_raw": cells[3],
                    "entry_year": extract_entry_year(cells[3]),
                    "from_station": cells[-5],
                    "from_date": cells[-4],
                    "to_station": cells[-3],
                    "to_date": cells[-2],
                    "remarks_raw": cells[-1],
                }
            )
    return records


def normalize_record(record, source_file, source_folder, company, fmt):
    row = {column: "NULL" for column in CSV_COLUMNS}
    row.update(
        {
            "source_file": source_file,
            "source_folder": source_folder,
            "company": company,
            "format": fmt,
        }
    )
    for key, value in record.items():
        if key in row:
            row[key] = null_if_blank(value)
    if row["entry_year"] == "NULL":
        row["entry_year"] = extract_entry_year(row.get("entry_date_raw"))
    if fmt == "B" and row["grade_clean"] == "NULL":
        row["grade_clean"] = clean_grade(row.get("grade_raw"))
    if fmt == "A" and row["locations_mentioned"] == "NULL":
        row["locations_mentioned"] = extract_locations(row.get("remarks_raw"))
    return row


def extract_records(document, source_file, source_folder):
    content = clean_text(document.get("content", ""))
    fmt = detect_format(document)
    company = infer_company(source_folder, content)
    raw_records = parse_format_a_rows(document) if fmt == "A" else parse_format_b_rows(document)
    if not raw_records:
        raw_records = fallback_line_rows(document, fmt)
    return [
        normalize_record(record, source_file, source_folder, company, fmt)
        for record in raw_records
    ]


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def print_test_rows(rows):
    if not rows:
        print("  No records extracted.")
        return
    print(f"  Extracted {len(rows)} records:")
    for row in rows:
        compact = {key: row.get(key) for key in CSV_COLUMNS if row.get(key) != "NULL"}
        print(f"    {json.dumps(compact, ensure_ascii=False)}")


def calculate_null_rates(rows):
    rates = {}
    total = len(rows)
    for field in KEY_FIELDS:
        if total == 0:
            rates[field] = 0.0
            continue
        nulls = sum(1 for row in rows if row.get(field) in (None, "", "NULL"))
        rates[field] = nulls / total
    return rates


def process(args):
    client = build_client()
    ensure_csv(args.output_csv)
    done_sources = load_done_sources(args.output_csv)

    rows_to_write = []
    processed_per_folder = Counter()
    skipped_csv = Counter()
    skipped_json = Counter()
    format_counts = Counter()
    extracted_total = 0

    for source_folder, folder in INPUT_FOLDERS:
        if not folder.exists():
            print(f"{source_folder}: input folder not found: {folder}")
            continue

        images = list_images(folder, test=args.test)
        print(f"{source_folder}: {len(images)} image(s) queued")
        for index, image_path in enumerate(images, start=1):
            source_file = image_path.name
            if source_file in done_sources:
                skipped_csv[source_folder] += 1
                print(f"  {index}/{len(images)} {source_file}: skipped (already in CSV)")
                continue

            json_path = analysis_json_path(args.json_dir, source_folder, image_path)
            if json_path.exists():
                skipped_json[source_folder] += 1
                document = load_json(json_path)
                print(f"  {index}/{len(images)} {source_file}: loaded cached JSON")
            else:
                document = analyze_image(client, image_path)
                save_json(json_path, document)
                processed_per_folder[source_folder] += 1
                print(f"  {index}/{len(images)} {source_file}: analyzed with Azure")
                time.sleep(args.sleep)

            rows = extract_records(document, source_file, source_folder)
            rows_to_write.extend(rows)
            done_sources.add(source_file)
            extracted_total += len(rows)
            format_counts.update(row["format"] for row in rows)
            if args.test:
                print_test_rows(rows)

    append_rows(args.output_csv, rows_to_write)
    all_touched = set(processed_per_folder) | set(skipped_json) | set(skipped_csv)

    print()
    print("Summary")
    print("-------")
    for source_folder in sorted(all_touched):
        print(
            f"{source_folder}: Azure processed={processed_per_folder[source_folder]}, "
            f"cached JSON={skipped_json[source_folder]}, skipped CSV={skipped_csv[source_folder]}"
        )
    print(f"Format A records: {format_counts['A']}")
    print(f"Format B records: {format_counts['B']}")
    print(f"Records extracted: {extracted_total}")
    print("Null rates:")
    for field, rate in calculate_null_rates(rows_to_write).items():
        print(f"  {field}: {rate:.1%}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract LNWR/GWR personnel records with Azure Document Intelligence."
    )
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--json-dir", type=Path, default=DEFAULT_JSON_DIR)
    parser.add_argument("--test", action="store_true", help="Process first 5 images per folder.")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Pause after Azure calls to be polite to the service.",
    )
    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
