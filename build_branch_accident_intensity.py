import argparse
import csv
import math
import re
from pathlib import Path


DEFAULT_INPUT = Path(
    r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\Processed_Data\accidents_with_rd1851.csv"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "branch_accident_intensity.csv"
EARTH_RADIUS_KM = 6371.0088
DISTANCE_CUTOFF_KM = 10

branch_locations = {
    'Newport': (51.5842, -2.9977),
    'Preston': (53.7632, -2.7031),
    'Peterborough': (52.5695, -0.2405),
    'New England': (52.5695, -0.2405),
    'Oxford': (51.7520, -1.2577),
    'Bath': (51.3781, -2.3597),
    'Battersea': (51.4785, -0.1450),
    'Kings Cross': (51.5308, -0.1238),
    'Guildford': (51.2362, -0.5704),
    'Watford': (51.6565, -0.3956),
    'Doncaster': (53.5228, -1.1286),
    'Barnsley': (53.5526, -1.4797),
    'Durham': (54.7761, -1.5733),
    'Grimsby': (53.5675, -0.0798),
    'Huddersfield': (53.6458, -1.7850),
    'Oldham': (53.5409, -2.1114),
    'Stockport': (53.4083, -2.1494),
    'Stratford': (51.5423, -0.0035),
    'Enfield': (51.6521, -0.0807),
    'Plymouth': (50.3755, -4.1427),
    'Salisbury': (51.0693, -1.7944),
    'Rochester': (51.3885, 0.5067),
    'Northwich': (53.2592, -2.5182),
    'Southport': (53.6452, -3.0056),
    'Kettering': (52.3995, -0.7295),
    'Dudley': (52.5120, -2.0810),
    'St Helens': (53.4540, -2.7370),
    'Tredegar': (51.7770, -3.2427),
    'Highbridge': (51.2160, -2.9720),
    'Merthyr Tydfil': (51.7430, -3.3785),
    'Newcastle': (54.9783, -1.6178),
    'Openshaw': (53.4750, -2.1700),
    'Miles Platting': (53.4940, -2.1900),
    'Gorton': (53.4680, -2.1650),
    'London Road Manchester': (53.4772, -2.2309),
    'Salford': (53.4875, -2.2901),
    'Guide Bridge': (53.4780, -2.0800),
    'Crystal Palace': (51.4215, -0.0731),
    'Portsmouth': (50.8058, -1.0872),
    'Warrington': (53.3900, -2.5970),
    'New Wortley': (53.7967, -1.5670),
    'Taunton': (51.0150, -3.1000),
    'Grantham': (52.9135, -0.6407),
    'Liverpool North End': (53.4084, -2.9916),
    'Sandhills': (53.4200, -2.9800),
    'Ipswich': (52.0567, 1.1482),
    'Ardwick': (53.4730, -2.2070),
    'Ambergate Junction': (53.0640, -1.4740),
    'Staveley': (53.2680, -1.3500),
    'Pontypridd': (51.6020, -3.3420),
    'Victoria London': (51.4965, -0.1438),
    'Nottingham': (52.9548, -1.1581),
    'Battersea No2': (51.4785, -0.1450),
    'South Eastern': (51.5074, -0.1278),
    'Bedford': (52.1386, -0.4667),
    'Marlborough': (51.4200, -1.7300),
    'Peterborough New England': (52.5800, -0.2420),
    'Blaenavon': (51.7730, -3.0850),
    'Ruabon': (52.9900, -3.0430),
}

WORKER_CAUSES = {
    "Driver error",
    "Signaller error",
    "Pointsman error",
    "Shunter error",
    "Guard error",
    "Station staff error",
}

OUTPUT_COLUMNS = [
    "branch",
    "lat",
    "lon",
    "total_accidents",
    "total_fatalities",
    "total_injuries",
    "worker_cause_accidents",
    "first_accident_year",
    "accident_rate",
]


def parse_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_damage(damage):
    text = str(damage or "")
    lower = text.lower()

    fatal_match = re.search(r"\b(\d+)\s+fatalit", lower)
    injury_match = re.search(r"\b(\d+)\s+injur", lower)

    fatalities = int(fatal_match.group(1)) if fatal_match else 0
    injuries = int(injury_match.group(1)) if injury_match else 0

    if "unknown" in lower:
        if "unknown fatal" in lower:
            fatalities = -1
        if "unknown number of injured" in lower or "unknown injur" in lower:
            injuries = -1

    return fatalities, injuries


def is_worker_cause(primary_causes):
    text = str(primary_causes or "")
    return any(cause in text for cause in WORKER_CAUSES)


def haversine_km(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def load_accidents(input_path):
    accidents = []
    with input_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            year = parse_int(row.get("year"))
            lat = parse_float(row.get("latitude"))
            lon = parse_float(row.get("longitude"))
            if year is None or year >= 1875 or lat is None or lon is None:
                continue

            fatalities, injuries = parse_damage(row.get("damage"))
            accidents.append(
                {
                    "year": year,
                    "lat": lat,
                    "lon": lon,
                    "fatalities": fatalities,
                    "injuries": injuries,
                    "worker_cause": is_worker_cause(row.get("primary_causes")),
                }
            )
    return accidents


def aggregate_by_branch(accidents):
    rows = []
    for branch, (branch_lat, branch_lon) in branch_locations.items():
        nearby = [
            accident
            for accident in accidents
            if haversine_km(branch_lat, branch_lon, accident["lat"], accident["lon"]) <= DISTANCE_CUTOFF_KM
        ]

        total_accidents = len(nearby)
        first_year = min((accident["year"] for accident in nearby), default="")
        total_fatalities = sum(accident["fatalities"] for accident in nearby if accident["fatalities"] != -1)
        total_injuries = sum(accident["injuries"] for accident in nearby if accident["injuries"] != -1)
        worker_cause_accidents = sum(1 for accident in nearby if accident["worker_cause"])

        if total_accidents > 0:
            accident_rate = total_accidents / (1874 - first_year + 1)
        else:
            accident_rate = 0

        rows.append(
            {
                "branch": branch,
                "lat": branch_lat,
                "lon": branch_lon,
                "total_accidents": total_accidents,
                "total_fatalities": total_fatalities,
                "total_injuries": total_injuries,
                "worker_cause_accidents": worker_cause_accidents,
                "first_accident_year": first_year,
                "accident_rate": accident_rate,
            }
        )
    return rows


def write_output(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Build branch-level pre-1875 accident intensity within 10km.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    accidents = load_accidents(args.input)
    rows = aggregate_by_branch(accidents)
    write_output(rows, args.output)

    branches_with_accidents = sum(1 for row in rows if row["total_accidents"] > 0)
    total_accidents_matched = sum(row["total_accidents"] for row in rows)
    print(f"Loaded {len(accidents)} pre-1875 accidents")
    print(f"Wrote {len(rows)} branch rows to {args.output}")
    print(f"Branches with accidents within {DISTANCE_CUTOFF_KM}km: {branches_with_accidents}")
    print(f"Total branch-accident matches: {total_accidents_matched}")


if __name__ == "__main__":
    main()
