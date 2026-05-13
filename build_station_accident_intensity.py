import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


DEFAULT_INPUT = Path(
    r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\Processed_Data\accidents_with_rd1851.csv"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "station_accident_intensity.csv"

WORKER_CAUSES = {
    "Driver error",
    "Signaller error",
    "Pointsman error",
    "Shunter error",
    "Guard error",
    "Station staff error",
}

OUTPUT_COLUMNS = [
    "rd_name",
    "total_accidents",
    "total_fatalities",
    "total_injuries",
    "worker_cause_accidents",
    "years_covered",
    "accident_rate",
]


def parse_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_damage(damage):
    text = str(damage or "").lower()
    fatalities = 0
    injuries = 0

    fatal_match = re.search(r"\b(\d+)\s+fatalit(?:y|ies)\b", text)
    if fatal_match:
        fatalities = int(fatal_match.group(1))

    injury_match = re.search(r"\b(\d+)\s+injured\b", text)
    if injury_match:
        injuries = int(injury_match.group(1))

    return fatalities, injuries


def is_worker_cause(primary_causes):
    causes = {part.strip() for part in str(primary_causes or "").split(",")}
    return bool(causes & WORKER_CAUSES)


def aggregate(input_path):
    groups = defaultdict(
        lambda: {
            "total_accidents": 0,
            "total_fatalities": 0,
            "total_injuries": 0,
            "worker_cause_accidents": 0,
            "years": [],
        }
    )

    with input_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            year = parse_int(row.get("year"))
            rd_name = str(row.get("rd_name") or "").strip()
            if year is None or year >= 1875 or not rd_name:
                continue

            fatalities, injuries = parse_damage(row.get("damage"))
            group = groups[rd_name]
            group["total_accidents"] += 1
            group["total_fatalities"] += fatalities
            group["total_injuries"] += injuries
            group["worker_cause_accidents"] += int(is_worker_cause(row.get("primary_causes")))
            group["years"].append(year)

    rows = []
    for rd_name, values in groups.items():
        min_year = min(values["years"])
        max_year = max(values["years"])
        years_covered = max_year - min_year + 1
        total_accidents = values["total_accidents"]
        rows.append(
            {
                "rd_name": rd_name,
                "total_accidents": total_accidents,
                "total_fatalities": values["total_fatalities"],
                "total_injuries": values["total_injuries"],
                "worker_cause_accidents": values["worker_cause_accidents"],
                "years_covered": years_covered,
                "accident_rate": total_accidents / years_covered if years_covered else 0,
            }
        )

    return sorted(rows, key=lambda row: row["rd_name"])


def write_output(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Aggregate pre-1875 railway accident intensity by rd_name.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = aggregate(args.input)
    write_output(rows, args.output)
    print(f"Wrote {len(rows)} rd_name rows to {args.output}")


if __name__ == "__main__":
    main()
