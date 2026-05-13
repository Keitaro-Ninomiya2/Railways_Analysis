import argparse
import csv
import json
import os
import re
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_FOLDER = Path(
    r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\RawData\ASRS\BalanceSheets\1875"
)
DEFAULT_OUTPUT_CSV = SCRIPT_DIR / "asrs_members_claude.csv"
DEFAULT_ERROR_DIR = SCRIPT_DIR / "errors"
MODEL = "claude-haiku-4-5-20251001"
CSV_COLUMNS = [
    "source_file",
    "branch",
    "member_no",
    "name",
    "age",
    "join_date",
    "join_year",
    "occupation",
]

SYSTEM_PROMPT = """You are a precise data extractor for Victorian historical records.
Always return valid JSON only. No explanation, no markdown, no code blocks."""

USER_PROMPT_TEMPLATE = """This is OCR text from an 1875 ASRS membership register page. The original had 
4 columns of members collapsed into one text stream.

Extract every member record. Rules:
- "do" or "do." in occupation = same occupation as the previous member, carry forward
- Dates are DD/MM/YY where YY is 1860s-1875 (e.g. 72 = 1872, 75 = 1875)
- Ignore occupation summary counts in right margin (e.g. "Signalmen 23", "Guards 7")
- Ignore ":selected:" tokens
- Ignore printed headers and footnotes
- Member numbers are integers, occasionally written with spaces (e.g. "3 3" = 33)

Branch name is in the line: "A Register of every Member belonging to the ___ Branch"
Extract only the text between "to the" and "Branch".

Return ONLY this JSON structure:
{
  "branch": "branch name",
  "members": [
    {
      "member_no": 1,
      "name": "Barker George",
      "age": 27,
      "join_date": "26/9/72",
      "join_year": 1872,
      "occupation": "Guard"
    }
  ]
}

If a field is unreadable write null.

OCR TEXT:
{content}"""


def load_done_sources(output_csv):
    if not output_csv.exists():
        return set()
    with output_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return {row["source_file"] for row in reader if row.get("source_file")}


def ensure_csv(output_csv):
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        return
    with output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()


def append_members(output_csv, source_file, response_data):
    branch = response_data.get("branch")
    members = response_data.get("members") or []
    with output_csv.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        for member in members:
            writer.writerow(
                {
                    "source_file": source_file,
                    "branch": null_to_empty(branch),
                    "member_no": null_to_empty(member.get("member_no")),
                    "name": null_to_empty(member.get("name")),
                    "age": null_to_empty(member.get("age")),
                    "join_date": null_to_empty(member.get("join_date")),
                    "join_year": null_to_empty(member.get("join_year")),
                    "occupation": null_to_empty(member.get("occupation")),
                }
            )
    return len(members)


def null_to_empty(value):
    return "" if value is None else value


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


def save_error(error_dir, source_file, raw_text):
    error_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{source_file}.txt"
    (error_dir / safe_name).write_text(raw_text, encoding="utf-8")


def extract_content(path):
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("content") or ""


def call_claude(client, content):
    return client.messages.create(
        model=MODEL,
        max_tokens=12000,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.replace("{content}", content),
            }
        ],
    )


def process_files(input_folder, output_csv, error_dir):
    load_dotenv(SCRIPT_DIR / ".env")
    ensure_csv(output_csv)
    done_sources = load_done_sources(output_csv)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to the environment or to .env in the script directory.")
    client = Anthropic(api_key=api_key)

    json_files = sorted(input_folder.glob("*_analysis.json"))
    register_files = []
    for path in json_files:
        content = extract_content(path)
        if "Register of every Member" in content:
            register_files.append((path, content))

    processed = 0
    skipped = 0
    failed = 0
    total_members = 0

    for index, (path, content) in enumerate(register_files, start=1):
        source_file = path.name
        if source_file in done_sources:
            skipped += 1
            print(f"Processing {index}/{len(register_files)}: {source_file} -> skipped")
            continue

        raw_text = ""
        try:
            message = call_claude(client, content)
            raw_text = get_response_text(message)
            response_data = parse_json_response(raw_text)
            member_count = append_members(output_csv, source_file, response_data)
            done_sources.add(source_file)
            processed += 1
            total_members += member_count
            print(f"Processing {index}/{len(register_files)}: {source_file} -> {member_count} members")
        except Exception as exc:
            failed += 1
            error_text = raw_text or f"{type(exc).__name__}: {exc}"
            save_error(error_dir, source_file, error_text)
            print(f"Processing {index}/{len(register_files)}: {source_file} -> failed")

        time.sleep(0.3)

    print()
    print(f"Files processed: {processed}")
    print(f"Files skipped (already done): {skipped}")
    print(f"Files failed: {failed}")
    print(f"Total members written: {total_members}")


def main():
    parser = argparse.ArgumentParser(description="Extract ASRS member rows from OCR JSON using Claude.")
    parser.add_argument("--input-folder", type=Path, default=DEFAULT_INPUT_FOLDER)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--error-dir", type=Path, default=DEFAULT_ERROR_DIR)
    args = parser.parse_args()

    process_files(args.input_folder, args.output_csv, args.error_dir)


if __name__ == "__main__":
    main()
