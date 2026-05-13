import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PERSONNEL_CSV = SCRIPT_DIR / "personnel_claude.csv"
DEFAULT_ASRS_CSV = SCRIPT_DIR / "asrs_members_claude.csv"
DEFAULT_ACCIDENT_CSV = SCRIPT_DIR / "branch_accident_intensity.csv"
DEFAULT_OUTPUT_CSV = SCRIPT_DIR / "station_analysis.csv"

STATION_MAP = {
    "LNER_Birmingham": {
        "station": "Birmingham",
        "lat": 52.4800,
        "lon": -1.8950,
        "company": "LNWR",
    },
    "GWR_BirminghamStation_Sample_1898_1913": {
        "station": "BirminghamStation",
        "lat": 52.5667,
        "lon": -2.0833,
        "company": "GWR",
    },
    "GWR_BirminghamStation_Sample_1910_1915": {
        "station": "BirminghamStation",
        "lat": 52.5667,
        "lon": -2.0833,
        "company": "GWR",
    },
    "GWR_AylesburyStation": {
        "station": "AylesburyStation",
        "lat": 51.8168,
        "lon": -0.8044,
        "company": "GWR",
    },
}

OUTPUT_COLUMNS = [
    "source_file",
    "source_folder",
    "station",
    "company",
    "name",
    "entry_year",
    "grade",
    "promoted",
    "years_to_promotion",
    "union_within_10km",
    "union_within_20km",
    "nearest_branch_km",
    "nearest_branch_name",
    "branch_members_10km",
    "instrument_accident_rate",
]

PROMOTION_DATE_FIELDS = [
    "grade_pit_gd_date",
    "grade_shunter_date",
    "grade_gds_gd_date",
]


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def parse_int(value):
    text = clean_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_float(value):
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_year_from_date(value, entry_year=None):
    text = clean_text(value)
    if not text:
        return None

    tokens = []
    current = ""
    for char in text:
        if char.isdigit():
            current += char
        elif current:
            tokens.append(current)
            current = ""
    if current:
        tokens.append(current)

    if not tokens:
        return None

    for token in tokens:
        if len(token) == 4 and token.startswith(("18", "19")):
            return int(token)

    year_token = tokens[-1]
    if len(year_token) <= 2:
        two_digit_year = int(year_token)
        candidates = []
        if 60 <= two_digit_year <= 99:
            candidates.append(1800 + two_digit_year)
        if 0 <= two_digit_year <= 29:
            candidates.append(1900 + two_digit_year)

        candidates = [year for year in candidates if 1860 <= year <= 1929]
        if entry_year is not None:
            candidates = [year for year in candidates if year >= entry_year]
        return candidates[0] if candidates else None
    return None


def haversine_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def read_csv(path):
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_branch_members(asrs_csv):
    members = Counter()
    for row in read_csv(asrs_csv):
        branch = clean_text(row.get("branch"))
        if branch:
            members[branch] += 1
    return members


def load_branches(accident_csv, branch_members):
    branches = []
    for row in read_csv(accident_csv):
        branch = clean_text(row.get("branch"))
        lat = parse_float(row.get("lat"))
        lon = parse_float(row.get("lon"))
        if not branch or lat is None or lon is None:
            continue
        branches.append(
            {
                "branch": branch,
                "lat": lat,
                "lon": lon,
                "accident_rate": parse_float(row.get("accident_rate")),
                "members": branch_members.get(branch, 0),
            }
        )
    return branches


def station_treatment(station_info, branches):
    distances = []
    for branch in branches:
        distance = haversine_km(
            station_info["lat"], station_info["lon"], branch["lat"], branch["lon"]
        )
        distances.append((distance, branch))

    if not distances:
        return {
            "union_within_10km": 0,
            "union_within_20km": 0,
            "nearest_branch_km": "",
            "nearest_branch_name": "",
            "branch_members_10km": 0,
            "instrument_accident_rate": "",
        }

    nearest_distance, nearest_branch = min(distances, key=lambda item: item[0])
    branches_10km = [(distance, branch) for distance, branch in distances if distance <= 10]
    branches_20km = [(distance, branch) for distance, branch in distances if distance <= 20]
    instrument_branch = None
    if branches_20km:
        instrument_branch = max(
            branches_20km,
            key=lambda item: item[1]["accident_rate"]
            if item[1]["accident_rate"] is not None
            else float("-inf"),
        )[1]

    return {
        "union_within_10km": 1 if branches_10km else 0,
        "union_within_20km": 1 if branches_20km else 0,
        "nearest_branch_km": f"{nearest_distance:.3f}",
        "nearest_branch_name": nearest_branch["branch"],
        "branch_members_10km": sum(branch["members"] for _, branch in branches_10km),
        "instrument_accident_rate": ""
        if instrument_branch is None or instrument_branch["accident_rate"] is None
        else instrument_branch["accident_rate"],
    }


def build_station_treatments(branches):
    return {
        source_folder: station_treatment(station_info, branches)
        for source_folder, station_info in STATION_MAP.items()
    }


def has_value(value):
    return clean_text(value).lower() not in {"", "null", "none", "nan"}


def promotion_outcome(row):
    promoted = 1 if has_value(row.get("grade_gds_gd_date")) or has_value(row.get("grade_shunter_date")) else 0
    entry_year = parse_int(row.get("entry_year"))
    promotion_year = parse_year_from_date(row.get("grade_gds_gd_date"), entry_year)
    years_to_promotion = ""
    if entry_year is not None and promotion_year is not None:
        years_to_promotion = promotion_year - entry_year
    return promoted, years_to_promotion


def build_rows(personnel_csv, station_treatments):
    output_rows = []
    for row in read_csv(personnel_csv):
        source_folder = clean_text(row.get("source_folder"))
        station_info = STATION_MAP.get(source_folder)
        if station_info is None:
            continue

        entry_year = parse_int(row.get("entry_year"))
        if entry_year is None:
            continue

        promoted, years_to_promotion = promotion_outcome(row)
        treatment = station_treatments[source_folder]
        output_rows.append(
            {
                "source_file": clean_text(row.get("source_file")),
                "source_folder": source_folder,
                "station": station_info["station"],
                "company": station_info["company"],
                "name": clean_text(row.get("name")),
                "entry_year": entry_year,
                "grade": clean_text(row.get("grade")),
                "promoted": promoted,
                "years_to_promotion": years_to_promotion,
                "union_within_10km": treatment["union_within_10km"],
                "union_within_20km": treatment["union_within_20km"],
                "nearest_branch_km": treatment["nearest_branch_km"],
                "nearest_branch_name": treatment["nearest_branch_name"],
                "branch_members_10km": treatment["branch_members_10km"],
                "instrument_accident_rate": treatment["instrument_accident_rate"],
            }
        )
    return output_rows


def write_rows(output_csv, rows):
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def mean(values):
    values = list(values)
    if not values:
        return None
    return sum(values) / len(values)


def print_summary(rows, station_treatments, personnel_csv):
    personnel_rows = read_csv(personnel_csv)
    workers_with_promotion_data = 0
    for row in personnel_rows:
        source_folder = clean_text(row.get("source_folder"))
        if source_folder not in STATION_MAP or parse_int(row.get("entry_year")) is None:
            continue
        if any(has_value(row.get(field)) for field in PROMOTION_DATE_FIELDS):
            workers_with_promotion_data += 1
    print()
    print("Summary")
    print("-------")
    print(f"Total workers: {len(rows)}")
    print(f"Workers with promotion data: {workers_with_promotion_data}")
    print("Station-level union treatment rates:")
    for source_folder, treatment in station_treatments.items():
        station = STATION_MAP[source_folder]["station"]
        company = STATION_MAP[source_folder]["company"]
        print(
            f"  {source_folder} ({station}, {company}): "
            f"10km={treatment['union_within_10km']}, "
            f"20km={treatment['union_within_20km']}, "
            f"nearest={treatment['nearest_branch_name']} "
            f"({treatment['nearest_branch_km']} km), "
            f"members_10km={treatment['branch_members_10km']}, "
            f"instrument={treatment['instrument_accident_rate']}"
        )

    by_treatment = defaultdict(list)
    for row in rows:
        by_treatment[row["union_within_20km"]].append(row["promoted"])
    print("Mean promotion rate by union_within_20km:")
    for treatment_value in [0, 1]:
        rate = mean(by_treatment.get(treatment_value, []))
        if rate is None:
            print(f"  {treatment_value}: no workers")
        else:
            print(f"  {treatment_value}: {rate:.3f}")


def main():
    parser = argparse.ArgumentParser(description="Build worker-level station treatment analysis file.")
    parser.add_argument("--personnel-csv", type=Path, default=DEFAULT_PERSONNEL_CSV)
    parser.add_argument("--asrs-csv", type=Path, default=DEFAULT_ASRS_CSV)
    parser.add_argument("--accident-csv", type=Path, default=DEFAULT_ACCIDENT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    args = parser.parse_args()

    branch_members = load_branch_members(args.asrs_csv)
    branches = load_branches(args.accident_csv, branch_members)
    station_treatments = build_station_treatments(branches)
    rows = build_rows(args.personnel_csv, station_treatments)
    write_rows(args.output_csv, rows)
    print(f"Wrote {len(rows)} rows to {args.output_csv}")
    print_summary(rows, station_treatments, args.personnel_csv)


if __name__ == "__main__":
    main()
