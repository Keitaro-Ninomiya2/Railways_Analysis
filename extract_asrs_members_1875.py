import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


OUTPUT_COLUMNS = [
    "source_file",
    "branch_name",
    "member_no",
    "name_raw",
    "age",
    "join_date_raw",
    "join_year",
    "occupation_raw",
    "occupation_clean",
    "ocr_confidence",
    "duplicate_flag",
]

FIELDNAMES = ["member_no", "name_raw", "age", "join_date_raw", "occupation_raw"]

PAGE_WIDTH = 6204
GROUP_WIDTH = 1550
ROW_TOLERANCE = 30
GROUP_BOUNDS = [
    (0, 1550),
    (1550, 3100),
    (3100, 4650),
    (4650, PAGE_WIDTH),
]
SUBCOLUMN_BOUNDS = [
    ("member_no_left", 0, 200),
    ("member_no_right", 200, 400),
    ("name_raw", 400, 900),
    ("age", 900, 1100),
    ("join_date_raw", 1100, 1350),
    ("occupation_raw", 1350, 1550),
]

SUMMARY_OCCUPATIONS = {
    "signalmen",
    "signalman",
    "shunters",
    "shunter",
    "guards",
    "guard",
    "porters",
    "porter",
    "firemen",
    "fireman",
    "platelayers",
    "platelayer",
    "foremen",
    "foreman",
    "clerks",
    "clerk",
    "drivers",
    "driver",
    "carmen",
    "carman",
    "pointsmen",
    "pointsman",
}


def clean_text(value):
    if value is None:
        return ""
    value = str(value).replace(":selected:", " ")
    return re.sub(r"\s+", " ", value).strip()


def null_if_blank(value):
    value = clean_text(value)
    return value if value else "NULL"


def normalize_key(value):
    return re.sub(r"[^a-z0-9]+", "", clean_text(value).lower())


def line_bbox(line):
    points = line.get("polygon") or line.get("boundingPolygon") or []
    xs = []
    ys = []
    for point in points:
        if isinstance(point, dict):
            xs.append(float(point.get("x", 0)))
            ys.append(float(point.get("y", 0)))
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def cell_bbox(cell):
    bounding_regions = cell.get("boundingRegions") or cell.get("bounding_regions") or [{}]
    points = cell.get("polygon") or bounding_regions[0].get("polygon") or []
    xs = []
    ys = []
    for point in points:
        if isinstance(point, dict):
            xs.append(float(point.get("x", 0)))
            ys.append(float(point.get("y", 0)))
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def bbox_center(bbox):
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def get_branch_name(document):
    pattern = re.compile(r"belonging\s+to\s+the\s+(.+?)\s+Branch", re.IGNORECASE)
    lines = document.get("pages", [{}])[0].get("lines", [])
    for line in lines[:30]:
        text = clean_text(line.get("content", ""))
        if "belonging" not in text.lower() or "branch" not in text.lower():
            continue
        match = pattern.search(text)
        if match:
            return clean_text(match.group(1))

    content = clean_text(document.get("content", ""))
    match = pattern.search(content)
    if match:
        return clean_text(match.group(1))
    return "NULL"


def parse_member_no(value):
    text = clean_text(value)
    if not text:
        return None
    if not re.search(r"\d", text):
        return None
    text = text.replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    compact = re.sub(r"\s+", "", text)
    match = re.search(r"\d+", compact)
    if not match:
        return None
    number = int(match.group(0))
    return number if 0 < number <= 999 else None


def parse_age(value):
    text = clean_text(value)
    match = re.search(r"\b(\d{1,2})\b", text)
    if not match:
        return None
    age = int(match.group(1))
    return age if 10 <= age <= 99 else None


def parse_join_year(value):
    text = clean_text(value)
    if not text:
        return None

    match = re.search(r"\b(18\d{2}|19\d{2})\b", text)
    if match:
        return int(match.group(1))

    parts = re.findall(r"\d{1,2}", text)
    if not parts:
        return None

    last = int(parts[-1])
    if last == 7 or last == 75:
        return 1875
    if 0 <= last <= 99:
        return 1800 + last
    return None


def clean_occupation(value):
    text = clean_text(value)
    key = normalize_key(text)
    if not key:
        return "NULL"

    mapping = [
        (("platelayer", "platilager", "platlagen", "platlayer", "platelager"), "Platelayer"),
        (("signalman", "signalmen", "signalement", "segnialman", "signalm"), "Signalman"),
        (("guard", "fourmed"), "Guard"),
        (("porter",), "Porter"),
        (("fireman", "firemen"), "Fireman"),
        (("shunter", "thunter", "chunters", "chunter"), "Shunter"),
        (("foreman", "formand"), "Foreman"),
        (("clerk", "click"), "Clerk"),
        (("enginedriver", "engineman", "driver"), "Engine Driver"),
        (("carman", "carmen"), "Carman"),
        (("pointsman", "pointsmen"), "Pointsman"),
    ]
    for variants, canonical in mapping:
        if any(variant in key for variant in variants):
            return canonical
    return text


def is_header_or_boilerplate(values):
    text = normalize_key(" ".join(clean_text(v) for v in values))
    if not text:
        return True
    header_bits = [
        "noonbranchbooks",
        "nameofmember",
        "agelastbirthday",
        "dateofjoining",
        "occupation",
        "registerofeverymember",
        "belongingtothe",
        "amalgamatedsociety",
    ]
    return any(bit in text for bit in header_bits)


def is_summary_count(values):
    values = list(values)
    text = clean_text(" ".join(clean_text(v) for v in values))
    if not text:
        return True
    if parse_member_no(values[0] if values else "") is not None:
        return False
    match = re.fullmatch(r"([A-Za-z][A-Za-z .'-]+)\s+(\d{1,3})", text)
    if not match:
        return False
    return normalize_key(match.group(1)) in SUMMARY_OCCUPATIONS


def is_numeric_only(value):
    text = clean_text(value)
    return bool(text) and bool(re.fullmatch(r"[\d\s.,/%-]+", text))


def is_do_occupation(value):
    return normalize_key(value) in {"do", "ditto"}


def get_confidence_for_spans(document, spans):
    styles = document.get("styles") or []
    if not styles or not spans:
        return None
    scores = []
    targets = []
    for span in spans:
        offset = span.get("offset")
        length = span.get("length")
        if offset is not None and length is not None:
            targets.append((int(offset), int(offset) + int(length)))
    if not targets:
        return None

    for style in styles:
        confidence = style.get("confidence")
        if confidence is None:
            continue
        for style_span in style.get("spans") or []:
            start = int(style_span.get("offset", -1))
            end = start + int(style_span.get("length", 0))
            if any(start < target_end and end > target_start for target_start, target_end in targets):
                scores.append(float(confidence))
                break
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def get_tables(document, page):
    return page.get("tables") or document.get("tables") or []


def page_has_tables(document, page):
    return any((table.get("cells") or []) for table in get_tables(document, page))


def extract_with_tables(document, source_file, branch_name):
    page = document.get("pages", [{}])[0]
    rows = []
    for table in get_tables(document, page):
        cells = table.get("cells") or []
        if not cells:
            continue
        by_row = defaultdict(list)
        for cell in cells:
            by_row[cell.get("rowIndex", cell.get("row_index", 0))].append(cell)

        for _, row_cells in sorted(by_row.items()):
            row_cells = sorted(row_cells, key=lambda c: c.get("columnIndex", c.get("column_index", 0)))
            values = [clean_text(cell.get("content", "")) for cell in row_cells]
            if is_header_or_boilerplate(values) or is_summary_count(values):
                continue

            chunks = split_table_row_into_member_chunks(row_cells)
            for chunk in chunks:
                record = build_record(document, source_file, branch_name, chunk)
                if record:
                    rows.append(record)
    return rows


def extract_records(document, source_file, branch_name):
    spatial_rows = extract_with_spatial_lines(document, source_file, branch_name)
    return spatial_rows


def split_table_row_into_member_chunks(row_cells):
    values = [clean_text(cell.get("content", "")) for cell in row_cells]
    if len(values) <= 5:
        return [make_chunk(row_cells)]

    chunks = []
    for start in range(0, len(row_cells), 5):
        subset = row_cells[start : start + 5]
        if len(subset) >= 2:
            chunks.append(make_chunk(subset))
    return chunks


def make_chunk(cells):
    chunk = {}
    for field, cell in zip(FIELDNAMES, cells):
        chunk[field] = clean_text(cell.get("content", ""))
        chunk[f"{field}_bbox"] = cell_bbox(cell)
        chunk[f"{field}_spans"] = cell.get("spans") or []
    return chunk


def extract_with_spatial_lines(document, source_file, branch_name):
    page = document.get("pages", [{}])[0]
    tokens = get_page_tokens(page)
    rows = []
    previous_occupation = ""
    for row_tokens in group_tokens_by_y(tokens):
        for group in range(4):
            chunk = build_chunk_from_row_tokens(row_tokens, group, previous_occupation)
            if not chunk:
                continue
            if is_header_or_boilerplate(chunk.values()) or is_summary_count(chunk.values()):
                continue
            occupation = clean_text(chunk.get("occupation_raw", ""))
            if occupation and not is_do_occupation(occupation):
                previous_occupation = occupation
            record = build_record(document, source_file, branch_name, chunk)
            if record:
                rows.append(record)
    return rows


def get_page_tokens(page):
    if page.get("words"):
        source_items = page.get("words") or []
        splitter = token_from_word
    else:
        source_items = page.get("lines") or []
        splitter = tokens_from_line

    tokens = []
    for item in source_items:
        tokens.extend(splitter(item))
    return [
        token
        for token in tokens
        if token["cy"] > 1000
        and token["cy"] < 6000
        and not is_header_or_boilerplate([token["text"]])
        and ":selected:" not in token["text"]
    ]


def token_from_word(word):
    text = clean_text(word.get("content", ""))
    bbox = line_bbox(word)
    if not text or not bbox:
        return []
    cx, cy = bbox_center(bbox)
    spans = word.get("spans") or ([word.get("span")] if word.get("span") else [])
    return [{"text": text, "bbox": bbox, "cx": cx, "cy": cy, "spans": spans}]


def tokens_from_line(line):
    text = clean_text(line.get("content", ""))
    bbox = line_bbox(line)
    if not text or not bbox:
        return []
    parts = list(re.finditer(r"\S+", text))
    if not parts:
        return []

    x0, y0, x1, y1 = bbox
    width = max(x1 - x0, 1)
    text_len = max(len(text), 1)
    tokens = []
    for part in parts:
        token_text = part.group(0)
        token_x0 = x0 + width * (part.start() / text_len)
        token_x1 = x0 + width * (part.end() / text_len)
        token_bbox = (token_x0, y0, token_x1, y1)
        cx, cy = bbox_center(token_bbox)
        tokens.append(
            {
                "text": token_text,
                "bbox": token_bbox,
                "cx": cx,
                "cy": cy,
                "spans": line.get("spans") or ([line.get("span")] if line.get("span") else []),
            }
        )
    return tokens


def group_tokens_by_y(tokens):
    rows = []
    for token in sorted(tokens, key=lambda item: item["cy"]):
        if not rows or abs(rows[-1]["y"] - token["cy"]) > ROW_TOLERANCE:
            rows.append({"y": token["cy"], "tokens": [token]})
        else:
            rows[-1]["tokens"].append(token)
            rows[-1]["y"] = sum(item["cy"] for item in rows[-1]["tokens"]) / len(rows[-1]["tokens"])
    return [row["tokens"] for row in rows]


def assign_group(x):
    for index, (left, right) in enumerate(GROUP_BOUNDS):
        if left <= x < right:
            return index
    return None


def assign_subcolumn(x, group):
    if group is None:
        return None
    group_start = GROUP_BOUNDS[group][0]
    rel_x = x - group_start
    for name, left, right in SUBCOLUMN_BOUNDS:
        if left <= rel_x < right:
            return name
    return None


def build_chunk_from_row_tokens(row_tokens, group, previous_occupation):
    fields = {field: [] for field in FIELDNAMES}
    bboxes = {field: [] for field in FIELDNAMES}
    spans = {field: [] for field in FIELDNAMES}

    for token in sorted(row_tokens, key=lambda item: item["cx"]):
        token_group = assign_group(token["cx"])
        if token_group != group:
            continue
        subcolumn = assign_subcolumn(token["cx"], group)
        if subcolumn in {"member_no_left", "member_no_right"}:
            field = "member_no"
        elif subcolumn in FIELDNAMES:
            field = subcolumn
        else:
            continue

        fields[field].append(token["text"])
        bboxes[field].append(token["bbox"])
        spans[field].extend(token.get("spans", []))

    if not fields["name_raw"] or is_numeric_only(" ".join(fields["name_raw"])):
        return None
    if fields["occupation_raw"] and is_numeric_only(" ".join(fields["occupation_raw"])):
        return None

    occupation_raw = clean_text(" ".join(fields["occupation_raw"]))
    if is_do_occupation(occupation_raw):
        fields["occupation_raw"] = [previous_occupation] if previous_occupation else []

    chunk = {}
    for field in FIELDNAMES:
        chunk[field] = clean_text(" ".join(fields[field]))
        chunk[f"{field}_bbox"] = merge_bboxes(bboxes[field])
        chunk[f"{field}_spans"] = spans[field]
    return chunk


def split_leading_member_no(text):
    match = re.match(r"^\s*([0-9OoIl ]{1,7})(?:[.)]?\s+|[.)]\s*)(.*)$", clean_text(text))
    if not match:
        return None, text
    number = parse_member_no(match.group(1))
    if number is None:
        return None, text
    return number, clean_text(match.group(2))


def split_trailing_age(text):
    match = re.match(r"^(.*?)(?:\s+|/)(\d{2})(?:[./,]?)$", clean_text(text))
    if not match:
        return text, None
    age = parse_age(match.group(2))
    if age is None:
        return text, None
    return clean_text(match.group(1)), age


def merge_bboxes(bboxes):
    bboxes = [bbox for bbox in bboxes if bbox]
    if not bboxes:
        return None
    return (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )


def build_record(document, source_file, branch_name, chunk):
    member_no = parse_member_no(chunk.get("member_no", ""))
    if member_no is None or not clean_text(chunk.get("name_raw", "")):
        return None

    raw_values = [chunk.get(field, "") for field in FIELDNAMES]
    if is_header_or_boilerplate(raw_values) or is_summary_count(raw_values):
        return None

    age = parse_age(chunk.get("age", ""))
    join_year = parse_join_year(chunk.get("join_date_raw", ""))
    confidence = get_confidence_for_spans(
        document,
        chunk.get("name_raw_spans") or chunk.get("member_no_spans"),
    )

    return {
        "source_file": source_file,
        "branch_name": null_if_blank(branch_name),
        "member_no": member_no,
        "name_raw": null_if_blank(chunk.get("name_raw", "")),
        "age": age if age is not None else "NULL",
        "join_date_raw": null_if_blank(chunk.get("join_date_raw", "")),
        "join_year": join_year if join_year is not None else "NULL",
        "occupation_raw": null_if_blank(chunk.get("occupation_raw", "")),
        "occupation_clean": clean_occupation(chunk.get("occupation_raw", "")),
        "ocr_confidence": confidence if confidence is not None else "NULL",
        "duplicate_flag": False,
    }


def mark_duplicates(rows):
    counts = Counter(
        (row["source_file"], row["member_no"])
        for row in rows
        if row["member_no"] != "NULL"
    )
    for row in rows:
        row["duplicate_flag"] = row["member_no"] != "NULL" and counts[(row["source_file"], row["member_no"])] > 1
    return rows


def extract_file(path):
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    page = (document.get("pages") or [{}])[0]
    branch_name = get_branch_name(document)
    if branch_name == "NULL":
        return []
    return extract_records(document, path.name, branch_name)


def write_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Extract ASRS 1875 member rows from Azure Document Intelligence JSON.")
    parser.add_argument("input_folder", nargs="?", default="input", help="Folder containing Azure JSON files.")
    parser.add_argument(
        "-o",
        "--output",
        default="asrs_members_1875.csv",
        help="Output CSV path.",
    )
    args = parser.parse_args()

    input_folder = Path(args.input_folder)
    json_files = sorted(path for path in input_folder.rglob("*.json") if path.is_file())
    rows = []
    for path in json_files:
        rows.extend(extract_file(path))
    rows = mark_duplicates(rows)
    write_csv(rows, Path(args.output))
    print(f"Wrote {len(rows)} rows from {len(json_files)} JSON files to {args.output}")


if __name__ == "__main__":
    main()
