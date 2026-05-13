"""
Build RD-to-railway-line mapping for line fixed effects.
Spatial join: which 1861 railway line(s) pass through each Registration District?

The randomness of accidents is on the rail line — which stretch had the accident.
Identification: compare RDs on the SAME line (some had accidents, some didn't).

Requires: 1861 England, Wales and Scotland Rail Lines shapefile
  UK Data Service: https://reshare.ukdataservice.ac.uk/852992/
  Download and extract to Processed_Data folder.

Output: rd_line_mapping.csv with rd_name, line_id (primary line per RD)
  Each RD assigned to the line with longest track length within the RD.
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path

BASE_PATH = Path(r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\Processed_Data")
RD_SHP = BASE_PATH / "7. 1851 England and Wales Census Registration Districts/1851EngWalesRegistrationDistrict.shp"
RAIL_LINES_SHP = BASE_PATH / "6. 1861 England Wales and Scotland rail lines/1861EnglandWalesandScotlandraillines.shp"
OUT_CSV = BASE_PATH / "rd_line_mapping.csv"
EPSG_27700 = 27700

# If your rail lines folder/文件名 differs, set it here:
RAIL_LINES_ALTERNATIVE = [
    BASE_PATH / "1861EnglandWalesandScotlandraillines.shp",
    BASE_PATH / "6. 1861 England Wales and Scotland rail lines/1861EngWalesScotRail_Lines.shp",
]


def find_rail_lines_shp():
    """Locate the 1861 rail lines shapefile."""
    if RAIL_LINES_SHP.exists():
        return RAIL_LINES_SHP
    for p in RAIL_LINES_ALTERNATIVE:
        if p.exists():
            return p
    # Search in Processed_Data
    for f in BASE_PATH.rglob("*.shp"):
        if "rail" in f.name.lower() and "line" in f.name.lower():
            return f
    return None


def main():
    if not RD_SHP.exists():
        raise FileNotFoundError(f"RD shapefile not found: {RD_SHP}")

    lines_shp = find_rail_lines_shp()
    if lines_shp is None:
        raise FileNotFoundError(
            "1861 Rail Lines shapefile not found.\n"
            "Download from UK Data Service: https://reshare.ukdataservice.ac.uk/852992/\n"
            "Extract to Processed_Data, e.g. '6. 1861 England Wales and Scotland rail lines/'"
        )

    print(f"RD boundaries: {RD_SHP}")
    print(f"Rail lines: {lines_shp}")

    rds = gpd.read_file(RD_SHP).to_crs(epsg=EPSG_27700)
    rd_name_col = [c for c in rds.columns if c != "geometry" and rds[c].dtype == object][0]

    lines = gpd.read_file(lines_shp).to_crs(epsg=EPSG_27700)
    # Find line identifier column
    line_id_candidates = ["NAME", "LINE", "COMPANY", "id", "ID", "OBJECTID", "FID"]
    line_id_col = None
    for c in line_id_candidates:
        if c in lines.columns:
            line_id_col = c
            break
    if line_id_col is None:
        line_id_col = lines.columns[0]  # fallback to first non-geom

    lines["_length"] = lines.geometry.length
    lines["_line_id"] = lines[line_id_col].astype(str)

    # Spatial join: lines that intersect each RD
    joined = gpd.sjoin(lines[["_line_id", "_length", "geometry"]], rds[[rd_name_col, "geometry"]], how="inner", predicate="intersects")
    joined = joined.rename(columns={rd_name_col: "rd_name"})

    joined["rd_name"] = joined["rd_name"].astype(str)
    # For each RD-line pair, sum length (line may intersect RD in multiple segments)
    rd_line_len = joined.groupby(["rd_name", "_line_id"])["_length"].sum().reset_index()
    # For each RD, pick the line with longest track length (primary line)
    rd_primary = (
        rd_line_len.loc[rd_line_len.groupby("rd_name")["_length"].idxmax()]
        [["rd_name", "_line_id"]]
        .rename(columns={"_line_id": "line_id"})
    )
    rd_primary["rd_name"] = rd_primary["rd_name"].astype(str)

    rd_primary.to_csv(OUT_CSV, index=False)
    print(f"\nSaved: {OUT_CSV}")
    print(f"RDs mapped to lines: {len(rd_primary)}")
    print(f"Unique lines: {rd_primary['line_id'].nunique()}")


if __name__ == "__main__":
    main()
