import argparse
import os
import re
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_ROOT = Path(os.environ.get("RAILWAY_MAP_CACHE", SCRIPT_DIR / ".map_cache"))
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_ROOT / "matplotlib"))
os.environ.setdefault("CARTOPY_DATA_DIR", str(CACHE_ROOT / "cartopy"))

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D


DEFAULT_ASRS_CSV = SCRIPT_DIR / "asrs_members_claude.csv"
DEFAULT_BRANCH_CSV = SCRIPT_DIR / "branch_accident_intensity.csv"
DEFAULT_ACCIDENT_CSV = Path(
    r"C:\Users\Keitaro Ninomiya\Box\Research Notes (keitaro2@illinois.edu)\RailwayUnions\Processed_Data\accidents_with_rd1851.csv"
)
DEFAULT_BRANCH_PDF = SCRIPT_DIR / "asrs_branch_map.pdf"
DEFAULT_BRANCH_PNG = SCRIPT_DIR / "asrs_branch_map.png"
DEFAULT_ACCIDENT_PDF = SCRIPT_DIR / "accident_map.pdf"
DEFAULT_ACCIDENT_PNG = SCRIPT_DIR / "accident_map.png"
DEFAULT_COMBINED_PDF = SCRIPT_DIR / "combined_map.pdf"
DEFAULT_COMBINED_PNG = SCRIPT_DIR / "combined_map.png"

UK_EXTENT = [-6, 2, 49.5, 56]
RAILWAY_BLUE = "#1F3864"
LAND_GREY = "#F0F0F0"
DARK_GREY = "#333333"
CAUSE_COLORS = {
    "Worker error": "#D62728",
    "Infrastructure/equipment": "#1F77B4",
    "Weather/external": "#2CA02C",
    "Unknown/other": "#999999",
}


def clean_branch(value):
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().split())


def load_branch_data(asrs_csv, branch_csv):
    members = pd.read_csv(asrs_csv)
    branches = pd.read_csv(branch_csv)

    members["branch"] = members["branch"].map(clean_branch)
    branches["branch"] = branches["branch"].map(clean_branch)

    member_counts = (
        members[members["branch"].ne("")]
        .groupby("branch", as_index=False)
        .size()
        .rename(columns={"size": "members"})
    )

    merged = branches.merge(member_counts, on="branch", how="left")
    merged["members"] = merged["members"].fillna(0).astype(int)
    merged["lat"] = pd.to_numeric(merged["lat"], errors="coerce")
    merged["lon"] = pd.to_numeric(merged["lon"], errors="coerce")
    merged["accident_rate"] = pd.to_numeric(merged["accident_rate"], errors="coerce")
    merged["total_accidents"] = pd.to_numeric(merged["total_accidents"], errors="coerce")
    merged = merged.dropna(subset=["lat", "lon"]).copy()
    return keep_uk_extent(merged, "lat", "lon")


def parse_fatalities(value):
    text = "" if pd.isna(value) else str(value).lower()
    match = re.search(r"(\d+)\s*(?:fatal|kill)", text)
    return int(match.group(1)) if match else 0


def cause_category(value):
    text = "" if pd.isna(value) else str(value).lower()
    worker_terms = [
        "driver",
        "signaller",
        "signalman",
        "pointsman",
        "shunter",
        "guard",
        "station staff",
        "site staff",
        "staff error",
    ]
    infrastructure_terms = [
        "infrastructure",
        "equipment",
        "rolling stock",
        "permanent way",
        "track",
        "rail",
        "signal",
        "brake",
        "mechanical",
        "locomotive",
        "wagon",
        "carriage",
        "points failure",
        "bridge",
    ]
    weather_terms = [
        "weather",
        "fog",
        "snow",
        "ice",
        "flood",
        "landslip",
        "external",
        "passenger",
        "trespass",
        "animal",
        "obstruction",
    ]
    if any(term in text for term in worker_terms):
        return "Worker error"
    if any(term in text for term in infrastructure_terms):
        return "Infrastructure/equipment"
    if any(term in text for term in weather_terms):
        return "Weather/external"
    return "Unknown/other"


def load_accident_data(accident_csv):
    accidents = pd.read_csv(accident_csv)
    accidents["year"] = pd.to_numeric(accidents["year"], errors="coerce")
    accidents["latitude"] = pd.to_numeric(accidents["latitude"], errors="coerce")
    accidents["longitude"] = pd.to_numeric(accidents["longitude"], errors="coerce")
    accidents = accidents[accidents["year"].lt(1875)].copy()
    accidents = accidents.dropna(subset=["latitude", "longitude"])
    accidents = accidents[(accidents["latitude"] != 0) & (accidents["longitude"] != 0)].copy()
    accidents = keep_uk_extent(accidents, "latitude", "longitude")
    accidents["fatalities"] = accidents["damage"].map(parse_fatalities)
    accidents["cause_group"] = accidents["primary_causes"].map(cause_category)
    return accidents


def keep_uk_extent(data, lat_col, lon_col):
    return data[
        data[lon_col].between(UK_EXTENT[0], UK_EXTENT[1])
        & data[lat_col].between(UK_EXTENT[2], UK_EXTENT[3])
    ].copy()


def branch_marker_sizes(members):
    return (members * 3).clip(lower=20)


def accident_marker_sizes(fatalities):
    return fatalities.map(lambda value: 15 if value == 0 else 40 if value <= 2 else 80)


def setup_cartopy():
    import cartopy
    import cartopy.crs as ccrs

    cartopy.config["data_dir"] = str(CACHE_ROOT / "cartopy")
    return ccrs.PlateCarree()


def style_cartopy_axis(ax, projection):
    import cartopy.feature as cfeature

    ax.set_extent(UK_EXTENT, crs=projection)
    ax.set_facecolor("white")
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="white", edgecolor="none")
    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor=LAND_GREY, edgecolor="none")
    ax.coastlines(resolution="10m", color=DARK_GREY, linewidth=0.5)
    ax.add_feature(cfeature.BORDERS.with_scale("10m"), edgecolor=DARK_GREY, linewidth=0.5)
    try:
        ax.add_feature(cfeature.RIVERS.with_scale("10m"), edgecolor="#B8C7D9", linewidth=0.35)
    except Exception:
        pass
    ax.set_xticks([])
    ax.set_yticks([])
    ax.spines["geo"].set_visible(False)


def selected_branch_labels(branches, threshold=50):
    return branches[branches["members"] > threshold].copy()


def apply_branch_labels(ax, branches, projection, threshold=50):
    labels = selected_branch_labels(branches, threshold=threshold)
    texts = []
    for _, row in labels.iterrows():
        text = ax.text(
            row["lon"] + 0.05,
            row["lat"] + 0.04,
            row["branch"],
            fontsize=6,
            color=DARK_GREY,
            ha="left",
            va="center",
            transform=projection,
        )
        texts.append(text)

    try:
        from adjustText import adjust_text

        adjust_text(
            texts=texts,
            ax=ax,
            arrowprops={"arrowstyle": "-", "color": DARK_GREY, "lw": 0.3},
            expand_points=(1.2, 1.3),
            expand_text=(1.1, 1.2),
            only_move={"points": "xy", "text": "xy"},
        )
    except Exception:
        pass


def draw_branch_map(ax, branches, projection, show_colorbar=False, title=None):
    style_cartopy_axis(ax, projection)
    norm = Normalize(vmin=0, vmax=max(1.0, branches["accident_rate"].max()))
    scatter = ax.scatter(
        branches["lon"],
        branches["lat"],
        s=branch_marker_sizes(branches["members"]),
        c=branches["accident_rate"],
        cmap="YlOrRd",
        norm=norm,
        edgecolors=DARK_GREY,
        linewidths=0.3,
        alpha=0.85,
        transform=projection,
        zorder=5,
    )
    apply_branch_labels(ax, branches, projection, threshold=50)
    if title:
        ax.set_title(title, fontsize=11, color=RAILWAY_BLUE, loc="left", pad=6)
    if show_colorbar:
        colorbar = ax.figure.colorbar(scatter, ax=ax, orientation="vertical", shrink=0.68, pad=0.02)
        colorbar.set_label("Pre-1875 accident rate (per year)", fontsize=8, color=DARK_GREY)
        colorbar.ax.tick_params(labelsize=7, colors=DARK_GREY, length=2)
        colorbar.outline.set_edgecolor(DARK_GREY)
        colorbar.outline.set_linewidth(0.4)
    return scatter


def draw_accident_map(ax, accidents, branches, projection, title=None, show_legend=True):
    style_cartopy_axis(ax, projection)
    for category, color in CAUSE_COLORS.items():
        subset = accidents[accidents["cause_group"] == category]
        if subset.empty:
            continue
        ax.scatter(
            subset["longitude"],
            subset["latitude"],
            s=accident_marker_sizes(subset["fatalities"]),
            c=color,
            alpha=0.6,
            edgecolors="none",
            transform=projection,
            zorder=3,
            label=category,
        )

    ax.scatter(
        branches["lon"],
        branches["lat"],
        s=30,
        facecolors="none",
        edgecolors="black",
        linewidths=1.2,
        transform=projection,
        zorder=5,
    )
    apply_branch_labels(ax, branches, projection, threshold=60)
    if title:
        ax.set_title(title, fontsize=11, color=RAILWAY_BLUE, loc="left", pad=6)
    if show_legend:
        add_accident_legend(ax)


def add_accident_legend(ax):
    cause_handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="",
            markerfacecolor=color,
            markeredgecolor="none",
            alpha=0.7,
            markersize=6,
            label=label,
        )
        for label, color in CAUSE_COLORS.items()
    ]
    severity_handles = [
        Line2D([0], [0], marker="o", linestyle="", color="#666666", markersize=4, label="no fatalities"),
        Line2D([0], [0], marker="o", linestyle="", color="#666666", markersize=7, label="1-2"),
        Line2D([0], [0], marker="o", linestyle="", color="#666666", markersize=10, label="3+"),
    ]
    first = ax.legend(
        handles=cause_handles,
        title="Accident cause",
        loc="lower left",
        fontsize=7,
        title_fontsize=8,
        frameon=True,
        framealpha=0.92,
        borderpad=0.5,
    )
    ax.add_artist(first)
    ax.legend(
        handles=severity_handles,
        title="Fatalities",
        loc="lower right",
        fontsize=7,
        title_fontsize=8,
        frameon=True,
        framealpha=0.92,
        borderpad=0.5,
    )


def save_figure(fig, output_pdf, output_png):
    fig.savefig(output_pdf, bbox_inches="tight")
    fig.savefig(output_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_branch_figure(branches, output_pdf, output_png):
    projection = setup_cartopy()
    fig = plt.figure(figsize=(8, 7), facecolor="white")
    ax = plt.axes(projection=projection)
    draw_branch_map(ax, branches, projection, show_colorbar=True)
    fig.subplots_adjust(left=0.04, right=0.90, bottom=0.035, top=0.96)
    save_figure(fig, output_pdf, output_png)


def plot_accident_figure(accidents, branches, output_pdf, output_png):
    projection = setup_cartopy()
    fig = plt.figure(figsize=(8, 7), facecolor="white")
    ax = plt.axes(projection=projection)
    draw_accident_map(ax, accidents, branches, projection)
    fig.suptitle(
        "Pre-1875 Railway Accidents and ASRS Branch Locations",
        x=0.08,
        y=0.975,
        ha="left",
        fontsize=14,
        fontweight="bold",
        color=RAILWAY_BLUE,
    )
    ax.set_title(
        "778 accidents (coloured by cause); open circles = 1875 ASRS branches",
        loc="left",
        fontsize=9,
        color=DARK_GREY,
        pad=8,
    )
    fig.subplots_adjust(left=0.04, right=0.96, bottom=0.035, top=0.90)
    save_figure(fig, output_pdf, output_png)


def plot_combined_figure(accidents, branches, output_pdf, output_png):
    import cartopy.crs as ccrs

    projection = setup_cartopy()
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(16, 7),
        facecolor="white",
        subplot_kw={"projection": ccrs.PlateCarree()},
    )
    draw_branch_map(
        axes[0],
        branches,
        projection,
        show_colorbar=True,
        title="ASRS branches: membership and accident intensity",
    )
    draw_accident_map(
        axes[1],
        accidents,
        branches,
        projection,
        title="Pre-1875 accidents and ASRS branch locations",
    )
    fig.suptitle(
        "ASRS Branch Network and Pre-1875 Accident Geography",
        x=0.05,
        y=0.975,
        ha="left",
        fontsize=16,
        fontweight="bold",
        color=RAILWAY_BLUE,
    )
    fig.subplots_adjust(left=0.03, right=0.97, bottom=0.04, top=0.90, wspace=0.07)
    save_figure(fig, output_pdf, output_png)


def main():
    parser = argparse.ArgumentParser(description="Create ASRS branch and accident maps.")
    parser.add_argument("--asrs-csv", type=Path, default=DEFAULT_ASRS_CSV)
    parser.add_argument("--branch-csv", type=Path, default=DEFAULT_BRANCH_CSV)
    parser.add_argument("--accident-csv", type=Path, default=DEFAULT_ACCIDENT_CSV)
    parser.add_argument("--branch-pdf", type=Path, default=DEFAULT_BRANCH_PDF)
    parser.add_argument("--branch-png", type=Path, default=DEFAULT_BRANCH_PNG)
    parser.add_argument("--accident-pdf", type=Path, default=DEFAULT_ACCIDENT_PDF)
    parser.add_argument("--accident-png", type=Path, default=DEFAULT_ACCIDENT_PNG)
    parser.add_argument("--combined-pdf", type=Path, default=DEFAULT_COMBINED_PDF)
    parser.add_argument("--combined-png", type=Path, default=DEFAULT_COMBINED_PNG)
    args = parser.parse_args()

    branches = load_branch_data(args.asrs_csv, args.branch_csv)
    accidents = load_accident_data(args.accident_csv)
    plot_branch_figure(branches, args.branch_pdf, args.branch_png)
    plot_accident_figure(accidents, branches, args.accident_pdf, args.accident_png)
    plot_combined_figure(accidents, branches, args.combined_pdf, args.combined_png)

    print(f"Mapped {len(branches)} ASRS branches.")
    print(f"Mapped {len(accidents)} pre-1875 accidents.")
    print(f"Wrote {args.branch_pdf}")
    print(f"Wrote {args.branch_png}")
    print(f"Wrote {args.accident_pdf}")
    print(f"Wrote {args.accident_png}")
    print(f"Wrote {args.combined_pdf}")
    print(f"Wrote {args.combined_png}")


if __name__ == "__main__":
    main()
