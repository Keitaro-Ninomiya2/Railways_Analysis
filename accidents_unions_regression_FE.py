"""
Accidents and Unions: Regression with Fixed Effects (County/Division).

Compares neighboring RDs within the same larger jurisdiction.
  has_union = alpha_county + beta*has_accident + gamma*log(pop) + delta*composition + epsilon

Controls: population size (census or area proxy), optional composition.
Fixed effects: Registration County (R_CTY, ~55) or Division (R_DIV, 11).

CENSUS_CSV format (optional):
  rd_name, population, [pct_agricultural, pct_urban, ...]
  Merge key: rd_name (matches CEN1 from RD shapefile).

Usage: python accidents_unions_regression_FE.py
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

BASE_PATH = r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\Processed_Data"
STATION_MULTI_RADIUS = Path(BASE_PATH) / "station_multi_radius.csv"
STATIONS_WITH_RD = Path(BASE_PATH) / "stations_with_rd1851.csv"
RD_SHP = Path(BASE_PATH) / r"7. 1851 England and Wales Census Registration Districts\1851EngWalesRegistrationDistrict.shp"

# Census: rd_name, population, [pct_agricultural, pct_urban, ...]
CENSUS_CSV = None  # Path(BASE_PATH) / "census1851_by_rd.csv"

RADII = [1000, 2000, 5000, 10000, 15000]
RADII_LABELS = [f"{r//1000}km" if r >= 1000 else f"{r}m" for r in RADII]


def load_rd_hierarchy():
    """RD -> county, division mapping from shapefile."""
    import geopandas as gpd
    rds = gpd.read_file(RD_SHP)
    h = rds[["CEN1", "R_CTY", "R_DIV", "R_CTRY"]].drop_duplicates()
    h = h.rename(columns={"CEN1": "rd_name"})
    h["rd_name"] = h["rd_name"].astype(str)
    return h


def load_population_control():
    """RD-level population and optional composition."""
    if CENSUS_CSV and Path(CENSUS_CSV).exists():
        cen = pd.read_csv(CENSUS_CSV)
        cen["rd_name"] = cen["rd_name"].astype(str)
        cen["log_pop"] = np.log(cen["population"].clip(lower=1))
        return cen
    import geopandas as gpd
    rds = gpd.read_file(RD_SHP).to_crs(epsg=27700)
    rds["area_km2"] = rds.geometry.area / 1e6
    rds = rds.groupby("CEN1", as_index=False).agg({"area_km2": "sum"})
    rds["log_pop"] = np.log(rds["area_km2"].clip(lower=0.1) + 1)
    rds = rds.rename(columns={"CEN1": "rd_name"})
    rds["rd_name"] = rds["rd_name"].astype(str)
    rds["population"] = rds["area_km2"]  # proxy
    return rds[["rd_name", "log_pop", "population"]]


def main():
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    from statsmodels.discrete.discrete_model import Logit

    df = pd.read_csv(STATION_MULTI_RADIUS)
    stns_rd = pd.read_csv(STATIONS_WITH_RD)
    stns_rd["rd_name"] = stns_rd["rd_name"].astype(str)
    df = df.merge(stns_rd[["Id", "rd_name"]], on="Id", how="left")
    df_ew = df.dropna(subset=["rd_name"]).copy()

    hierarchy = load_rd_hierarchy()
    df_ew = df_ew.merge(hierarchy[["rd_name", "R_CTY", "R_DIV"]], on="rd_name", how="left")

    pop_df = load_population_control()
    df_ew = df_ew.merge(pop_df[["rd_name", "log_pop"]], on="rd_name", how="left")
    comp_cols = [c for c in pop_df.columns if c not in ["rd_name", "log_pop", "population"]]
    if comp_cols:
        df_ew = df_ew.merge(pop_df[["rd_name"] + comp_cols], on="rd_name", how="left")

    df_ew = df_ew.dropna(subset=["log_pop", "R_CTY"])
    df_ew["county"] = df_ew["R_CTY"].astype("category")
    df_ew["division"] = df_ew["R_DIV"].astype("category")

    n_cty = df_ew["county"].nunique()
    n_div = df_ew["division"].nunique()
    print(f"Stations (Eng/Wales): {len(df_ew)}")
    print(f"Counties (R_CTY): {n_cty} | Divisions (R_DIV): {n_div}")
    print(f"Population control: {'census' if CENSUS_CSV and Path(CENSUS_CSV).exists() else 'log(area+1) proxy'}")
    if comp_cols:
        print(f"Composition controls: {comp_cols}")

    results = []

    for label in RADII_LABELS:
        y_col = f"has_union_{label}"
        x_col = f"has_accident_{label}"
        if y_col not in df_ew.columns:
            continue
        y = df_ew[y_col]
        if y.sum() == 0 or y.sum() == len(y):
            continue

        base_vars = f"{x_col} + log_pop"
        comp_str = " + " + " + ".join(comp_cols) if comp_cols else ""

        # (1) LPM + pop (no FE)
        f1 = f"Q('{y_col}') ~ {base_vars}{comp_str}"
        m1 = smf.ols(f1, data=df_ew).fit(cov_type="HC1")
        results.append({"radius": label, "model": "LPM + pop", "fe": "None",
                        "beta": m1.params[x_col], "se": m1.bse[x_col], "p": m1.pvalues[x_col], "r2": m1.rsquared})

        # (2) LPM + pop + County FE
        f2 = f"Q('{y_col}') ~ {base_vars}{comp_str} + C(county)"
        m2 = smf.ols(f2, data=df_ew).fit(cov_type="HC1")
        results.append({"radius": label, "model": "LPM + pop", "fe": "County",
                        "beta": m2.params[x_col], "se": m2.bse[x_col], "p": m2.pvalues[x_col], "r2": m2.rsquared})

        # (3) LPM + pop + Division FE
        f3 = f"Q('{y_col}') ~ {base_vars}{comp_str} + C(division)"
        m3 = smf.ols(f3, data=df_ew).fit(cov_type="HC1")
        results.append({"radius": label, "model": "LPM + pop", "fe": "Division",
                        "beta": m3.params[x_col], "se": m3.bse[x_col], "p": m3.pvalues[x_col], "r2": m3.rsquared})

        # (4) Logit + pop + Division FE (marginal effects; fewer groups than County)
        try:
            f4 = f"Q('{y_col}') ~ {base_vars}{comp_str} + C(division)"
            logit = smf.logit(f4, data=df_ew).fit(disp=0, maxiter=200)
            mfx = logit.get_margeff(at="mean")
            exog_names = list(logit.model.exog_names) if hasattr(logit.model, "exog_names") else list(logit.params.index)
            idx = exog_names.index(x_col) if x_col in exog_names else 1
            results.append({"radius": label, "model": "Logit + pop", "fe": "Division",
                            "beta": mfx.margeff[idx], "se": mfx.margeff_se[idx], "p": mfx.pvalues[idx], "r2": logit.prsquared})
        except Exception:
            results.append({"radius": label, "model": "Logit + pop", "fe": "Division",
                            "beta": np.nan, "se": np.nan, "p": np.nan, "r2": np.nan})

    res_df = pd.DataFrame(results)
    res_df["stars"] = res_df["p"].apply(lambda p: "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else "")

    print("\n" + "=" * 90)
    print("REGRESSION: has_union ~ has_accident + log(pop) + Fixed Effects")
    print("(Comparing neighboring RDs within same county/division)")
    print("=" * 90)

    for fe in ["None", "County", "Division"]:
        sub = res_df[res_df["fe"] == fe]
        if len(sub) == 0:
            continue
        print(f"\n--- Fixed effects: {fe} ---")
        for _, r in sub.iterrows():
            b = f"{r['beta']:.4f}" if not np.isnan(r["beta"]) else "n/a"
            s = f"({r['se']:.4f})" if not np.isnan(r["se"]) else ""
            r2str = f"{r['r2']:.4f}" if not np.isnan(r["r2"]) else "n/a"
            print(f"  {r['radius']:>4} | {r['model']:12} | beta = {b} {s} {r['stars']} | R2 = {r2str}")

    pivot = res_df.pivot_table(index=["model", "fe"], columns="radius", values="beta")
    print("\n" + "-" * 90)
    print("Coefficient on has_accident:")
    print(pivot.round(4).to_string())

    out_path = Path(BASE_PATH) / "regression_with_FE.csv"
    res_df.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
