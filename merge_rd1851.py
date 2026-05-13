"""
Merge accidents, branches, and stations to 1851 Registration Districts.
Uniform jurisdiction level for census matching (1851, 1861 England & Wales).

Usage: python merge_rd1851.py

Requires:
- 1851 RD shapefile from UK Data Service https://reshare.ukdataservice.ac.uk/852948/
- cache_accident_geocoding.csv, cache_union_geocoding.csv (from R pipeline)
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------
BASE_PATH = r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\Processed_Data"

STATION_SHP = BASE_PATH + r"\5. 1861 England, Wales and Scotland rail stations\1861EngWalesScotRail_Stations.shp"
ACCIDENT_CSV = BASE_PATH + r"\detailed_accidents_data.csv"
BRANCH_CSV = BASE_PATH + r"\ASRS\BalanceSheets\1875\Results\georeferenced_railway_results.csv"

# 1851 Registration Districts (England & Wales)
RD_1851_SHP = BASE_PATH + r"\7. 1851 England and Wales Census Registration Districts\1851EngWalesRegistrationDistrict.shp"

ACCIDENT_GEO_CACHE = BASE_PATH + r"\cache_accident_geocoding.csv"
UNION_GEO_CACHE = BASE_PATH + r"\cache_union_geocoding.csv"

EPSG_27700 = 27700  # British National Grid (meters)


def assign_to_rd(points_gdf, rds_gdf, rd_name_col):
    """Spatial join: assign each point to its containing 1851 Registration District."""
    pts = points_gdf.to_crs(rds_gdf.crs)
    joined = gpd.sjoin(pts, rds_gdf[[rd_name_col, "geometry"]], how="left", predicate="within")
    missing = joined[rd_name_col].isna()
    if missing.any():
        nearest = gpd.sjoin_nearest(
            pts.loc[missing], rds_gdf[[rd_name_col, "geometry"]], how="left", max_distance=5000
        )
        nearest = nearest[~nearest.index.duplicated(keep="first")]
        joined.loc[nearest.index, rd_name_col] = nearest[rd_name_col].values
    return joined.drop(columns=["index_right"], errors="ignore")


def main():
    base = Path(BASE_PATH)

    # 1. Load 1851 Registration District boundaries
    if not Path(RD_1851_SHP).exists():
        raise FileNotFoundError(
            f"1851 RD shapefile not found at {RD_1851_SHP}\n"
            "Download from UK Data Service: https://reshare.ukdataservice.ac.uk/852948/"
        )
    rds = gpd.read_file(RD_1851_SHP).to_crs(epsg=EPSG_27700)
    rd_name_col = [c for c in rds.columns if c != "geometry" and rds[c].dtype == object][0]
    print(f"RD shapefile: using '{rd_name_col}' as identifier")

    # 2. Accidents
    if not Path(ACCIDENT_GEO_CACHE).exists():
        raise FileNotFoundError(f"Accident geocoding cache not found: {ACCIDENT_GEO_CACHE}")
    acc_raw = pd.read_csv(ACCIDENT_CSV)
    acc_raw["_join"] = acc_raw["location"].astype(str).str.lower().str.strip()
    acc_geo = pd.read_csv(ACCIDENT_GEO_CACHE)
    acc_geo["_join"] = acc_geo["location"].astype(str).str.lower().str.strip()
    acc_geo = acc_geo.drop_duplicates(subset=["_join"])
    acc = acc_raw.merge(acc_geo[["_join", "latitude", "longitude"]], on="_join", how="left")
    acc = acc.dropna(subset=["latitude", "longitude"])
    acc_gdf = gpd.GeoDataFrame(
        acc,
        geometry=gpd.points_from_xy(acc["longitude"], acc["latitude"]),
        crs="EPSG:4326",
    ).to_crs(epsg=EPSG_27700)
    acc_with_rd = assign_to_rd(acc_gdf, rds, rd_name_col).rename(columns={rd_name_col: "rd_name"})
    print(f"Accidents: {len(acc_with_rd)}, assigned to RD: {acc_with_rd['rd_name'].notna().sum()}")

    # 3. Branches
    if not Path(UNION_GEO_CACHE).exists():
        raise FileNotFoundError(f"Union geocoding cache not found: {UNION_GEO_CACHE}")
    br_raw = pd.read_csv(BRANCH_CSV).dropna(subset=["cleaned_loc"])
    join_col = "corrected_loc" if "corrected_loc" in br_raw.columns else "cleaned_loc"
    br_raw["_join"] = br_raw[join_col].astype(str).str.lower().str.strip()
    br_geo = pd.read_csv(UNION_GEO_CACHE)
    br_geo["_join"] = br_geo["location"].astype(str).str.lower().str.strip()
    br_geo = br_geo.drop_duplicates(subset=["_join"])
    br = br_raw.merge(br_geo[["_join", "latitude", "longitude"]], on="_join", how="left")
    br = br.dropna(subset=["latitude", "longitude"])
    br_gdf = gpd.GeoDataFrame(
        br,
        geometry=gpd.points_from_xy(br["longitude"], br["latitude"]),
        crs="EPSG:4326",
    ).to_crs(epsg=EPSG_27700)
    br_with_rd = assign_to_rd(br_gdf, rds, rd_name_col).rename(columns={rd_name_col: "rd_name"})
    print(f"Branches: {len(br_with_rd)}, assigned to RD: {br_with_rd['rd_name'].notna().sum()}")

    # 4. Stations
    stns = gpd.read_file(STATION_SHP).to_crs(epsg=EPSG_27700)
    stns_with_rd = assign_to_rd(stns, rds, rd_name_col).rename(columns={rd_name_col: "rd_name"})
    print(f"Stations: {len(stns_with_rd)}, in Eng/Wales: {stns_with_rd['rd_name'].notna().sum()}")

    # 5. RD-level aggregates
    rd_acc = acc_with_rd.dropna(subset=["rd_name"]).groupby("rd_name").size().reset_index(name="accident_count")
    rd_br = br_with_rd.dropna(subset=["rd_name"]).groupby("rd_name").size().reset_index(name="branch_count")
    rd_stn = stns_with_rd.dropna(subset=["rd_name"]).groupby("rd_name").size().reset_index(name="station_count")
    rd_merged = rd_stn.merge(rd_acc, on="rd_name", how="left").merge(rd_br, on="rd_name", how="left")
    rd_merged["accident_count"] = rd_merged["accident_count"].fillna(0).astype(int)
    rd_merged["branch_count"] = rd_merged["branch_count"].fillna(0).astype(int)
    print(f"\nRD-level dataset: {len(rd_merged)} registration districts")

    # 6. Save
    acc_with_rd.drop(columns=["geometry"], errors="ignore").to_csv(base / "accidents_with_rd1851.csv", index=False)
    br_with_rd.drop(columns=["geometry"], errors="ignore").to_csv(base / "branches_with_rd1851.csv", index=False)
    stns_with_rd.drop(columns=["geometry"], errors="ignore").to_csv(base / "stations_with_rd1851.csv", index=False)
    rd_merged.to_csv(base / "rd1851_aggregates.csv", index=False)
    print(f"Saved to {base}")


if __name__ == "__main__":
    main()
