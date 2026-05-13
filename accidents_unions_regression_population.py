"""
Accidents and Unions: Regression with population control.

Estimating: has_union = α + β·has_accident + γ·log(population) + X'δ + ε

Population is measured at the 1851 Registration District level.
Uses RD area (sq km) as population proxy if no census population file provided.
To use actual 1851 census population, provide a CSV with columns: rd_name, population

Usage: python accidents_unions_regression_population.py
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

BASE_PATH = r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\Processed_Data"
STATION_MULTI_RADIUS = Path(BASE_PATH) / "station_multi_radius.csv"
STATIONS_WITH_RD = Path(BASE_PATH) / "stations_with_rd1851.csv"
RD_AGGREGATES = Path(BASE_PATH) / "rd1851_aggregates.csv"
RD_SHP = Path(BASE_PATH) / r"7. 1851 England and Wales Census Registration Districts\1851EngWalesRegistrationDistrict.shp"

# Optional: 1851 census population by RD. Columns: rd_name, population
POPULATION_CSV = None  # e.g. Path(BASE_PATH) / "census1851_population_by_rd.csv"

RADII = [1000, 2000, 5000, 10000, 15000]
RADII_LABELS = [f"{r//1000}km" if r >= 1000 else f"{r}m" for r in RADII]


def load_population_control():
    """Load population/area at RD level. Returns df with rd_name, log_pop."""
    if POPULATION_CSV and Path(POPULATION_CSV).exists():
        pop = pd.read_csv(POPULATION_CSV)
        pop["rd_name"] = pop["rd_name"].astype(str)
        pop["log_pop"] = np.log(pop["population"].clip(lower=1))
        return pop[["rd_name", "log_pop", "population"]]
    # Fallback: use RD area (sq km) from shapefile as size proxy
    import geopandas as gpd
    rds = gpd.read_file(RD_SHP).to_crs(epsg=27700)
    rds["area_km2"] = rds.geometry.area / 1e6  # m^2 -> km^2
    # Aggregate by CEN1 (one RD can have multiple polygons)
    rds = rds.groupby("CEN1", as_index=False).agg({"area_km2": "sum"})
    rds["log_pop"] = np.log(rds["area_km2"].clip(lower=0.1) + 1)
    rds = rds.rename(columns={"CEN1": "rd_name"})
    rds["rd_name"] = rds["rd_name"].astype(str)
    return rds[["rd_name", "log_pop"]].assign(population=rds["area_km2"])


def main():
    # Load station-level data
    df = pd.read_csv(STATION_MULTI_RADIUS)
    stns_rd = pd.read_csv(STATIONS_WITH_RD)
    stns_rd["rd_name"] = stns_rd["rd_name"].astype(str)
    df = df.merge(stns_rd[["Id", "rd_name"]], on="Id", how="left")

    # Restrict to England & Wales (have RD)
    df_ew = df.dropna(subset=["rd_name"]).copy()
    print(f"Stations in England & Wales: {len(df_ew)} (excluded {len(df)-len(df_ew)} Scotland)")

    # Load population/area control
    pop_df = load_population_control()
    pop_df["rd_name"] = pop_df["rd_name"].astype(str)
    df_ew = df_ew.merge(pop_df[["rd_name", "log_pop"]], on="rd_name", how="left")
    missing_pop = df_ew["log_pop"].isna()
    if missing_pop.any():
        df_ew = df_ew.dropna(subset=["log_pop"])
        print(f"Dropped {missing_pop.sum()} stations with missing pop/area: {len(df_ew)} remaining")
    print(f"Population control: log(area_km2+1) from RD shapefile (or census if provided)")

    # Scale lat/lon for stability
    df_ew["lat"] = (df_ew["latitude"] - df_ew["latitude"].mean()) / df_ew["latitude"].std()
    df_ew["lon"] = (df_ew["longitude"] - df_ew["longitude"].mean()) / df_ew["longitude"].std()
    df_ew["lat2"] = df_ew["lat"] ** 2
    df_ew["lon2"] = df_ew["lon"] ** 2
    df_ew["lat_lon"] = df_ew["lat"] * df_ew["lon"]

    try:
        import statsmodels.api as sm
        from statsmodels.discrete.discrete_model import Logit
    except ImportError:
        print("statsmodels required: pip install statsmodels")
        return

    print("\n" + "=" * 80)
    print("REGRESSION: has_union ~ has_accident + log(population) + spatial controls")
    print("=" * 80)

    results = []
    for label in RADII_LABELS:
        y_col = f"has_union_{label}"
        x_col = f"has_accident_{label}"
        if y_col not in df_ew.columns:
            continue
        y = df_ew[y_col].values
        if y.sum() == 0 or y.sum() == len(y):
            continue

        # (1) Baseline: no controls
        X1 = sm.add_constant(df_ew[[x_col]])
        m1 = sm.OLS(y, X1).fit(cov_type="HC1")
        results.append({"radius": label, "model": "LPM (no controls)", "beta": m1.params[x_col],
                        "se": m1.bse[x_col], "p": m1.pvalues[x_col], "r2": m1.rsquared})

        # (2) + population
        X2 = sm.add_constant(df_ew[[x_col, "log_pop"]])
        m2 = sm.OLS(y, X2).fit(cov_type="HC1")
        results.append({"radius": label, "model": "LPM + pop", "beta": m2.params[x_col],
                        "se": m2.bse[x_col], "p": m2.pvalues[x_col], "r2": m2.rsquared})

        # (3) + spatial
        X3 = sm.add_constant(df_ew[[x_col, "log_pop", "lat", "lon", "lat2", "lon2", "lat_lon"]])
        m3 = sm.OLS(y, X3).fit(cov_type="HC1")
        results.append({"radius": label, "model": "LPM + pop + spatial", "beta": m3.params[x_col],
                        "se": m3.bse[x_col], "p": m3.pvalues[x_col], "r2": m3.rsquared})

        # (4) Logit + pop + spatial
        try:
            X4 = sm.add_constant(df_ew[[x_col, "log_pop", "lat", "lon", "lat2", "lon2", "lat_lon"]])
            logit = Logit(y, X4).fit(disp=0, maxiter=100)
            mfx = logit.get_margeff(at="mean")
            results.append({"radius": label, "model": "Logit + pop + spatial (ME)", "beta": mfx.margeff[0],
                            "se": mfx.margeff_se[0], "p": mfx.pvalues[0], "r2": logit.prsquared})
        except Exception:
            pass

    res_df = pd.DataFrame(results)
    res_df["beta_se"] = res_df.apply(lambda r: f"{r['beta']:.4f}\n({r['se']:.4f})", axis=1)
    res_df["stars"] = res_df["p"].apply(lambda p: "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else "")

    # Pivot for display
    print("\nCoefficient on has_accident (HC1 robust SE):\n")
    for model in ["LPM (no controls)", "LPM + pop", "LPM + pop + spatial", "Logit + pop + spatial (ME)"]:
        sub = res_df[res_df["model"] == model]
        if len(sub) == 0:
            continue
        row = sub.set_index("radius")["beta_se"]
        stars = sub.set_index("radius")["stars"]
        print(f"  {model}:")
        for lbl in RADII_LABELS:
            if lbl in row.index:
                print(f"    {lbl:>4}: {row[lbl]} {stars.get(lbl,'')}")
        print()

    # Summary table
    pivot_beta = res_df.pivot(index="model", columns="radius", values="beta")
    pivot_se = res_df.pivot(index="model", columns="radius", values="se")
    print("\n" + "-" * 80)
    print("Full results (beta):")
    print(pivot_beta.round(4).to_string())
    print("\nStandard errors:")
    print(pivot_se.round(4).to_string())

    out_path = Path(BASE_PATH) / "regression_with_population.csv"
    res_df.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
