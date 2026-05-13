# =============================================================================
# Accidents and Unions: Regression with Fixed Effects (County/Division)
# =============================================================================
# Compares neighboring RDs within the same larger jurisdiction.
#   has_union = alpha_county + beta*has_accident + gamma*log(pop) + epsilon
#
# Fixed effects: Registration County (R_CTY) or Division (R_DIV).
# Population control: log(area) proxy from RD shapefile, or census CSV.
#
# Usage: source("Accidents_Unions_Regression_FE.R")
# =============================================================================

library(tidyverse)
library(sf)
library(fixest)
library(modelsummary)

base_path <- "C:/Users/Keitaro Ninomiya/Box/Research Notes (keitaro2@illinois.edu)/RailwayUnions/Processed_Data"
rd_shp   <- file.path(base_path, "7. 1851 England and Wales Census Registration Districts/1851EngWalesRegistrationDistrict.shp")

# Optional: census CSV with rd_name, population, [pct_ag, pct_urban, ...]
census_csv <- NULL  # file.path(base_path, "census1851_by_rd.csv")

radii <- c(1000, 2000, 5000, 10000, 15000)
labels <- ifelse(radii >= 1000, paste0(radii/1000, "km"), paste0(radii, "m"))

# -----------------------------------------------------------------------------
# 1. Load and merge data
# -----------------------------------------------------------------------------
df <- read_csv(file.path(base_path, "station_multi_radius.csv"), show_col_types = FALSE)
stns_rd <- read_csv(file.path(base_path, "stations_with_rd1851.csv"), show_col_types = FALSE) %>%
  mutate(rd_name = as.character(rd_name))

df <- df %>%
  left_join(select(stns_rd, Id, rd_name), by = "Id") %>%
  filter(!is.na(rd_name))

# RD hierarchy (county, division) from shapefile
rds <- st_read(rd_shp, quiet = TRUE) %>%
  st_drop_geometry() %>%
  select(CEN1, R_CTY, R_DIV) %>%
  distinct() %>%
  mutate(rd_name = as.character(CEN1))

# Population: area proxy or census
if (!is.null(census_csv) && file.exists(census_csv)) {
  pop_df <- read_csv(census_csv, show_col_types = FALSE) %>%
    mutate(rd_name = as.character(rd_name), log_pop = log(pmax(population, 1)))
} else {
  rds_geo <- st_read(rd_shp, quiet = TRUE) %>% st_transform(27700)
  rds_geo$area_km2 <- st_area(rds_geo) %>% as.numeric() / 1e6
  pop_df <- rds_geo %>%
    st_drop_geometry() %>%
    group_by(CEN1) %>%
    summarise(area_km2 = sum(area_km2), .groups = "drop") %>%
    mutate(rd_name = as.character(CEN1), log_pop = log(pmax(area_km2, 0.1) + 1))
}

# Station count by RD (from rd1851_aggregates or computed from stations)
rd_agg_path <- file.path(base_path, "rd1851_aggregates.csv")
if (file.exists(rd_agg_path)) {
  rd_agg <- read_csv(rd_agg_path, show_col_types = FALSE) %>%
    mutate(rd_name = as.character(rd_name), log_stations = log(pmax(station_count, 0) + 1))
} else {
  rd_agg <- stns_rd %>%
    filter(!is.na(rd_name)) %>%
    group_by(rd_name) %>%
    summarise(station_count = n(), .groups = "drop") %>%
    mutate(log_stations = log(station_count + 1))
}

df <- df %>%
  left_join(select(rds, rd_name, R_CTY, R_DIV), by = "rd_name") %>%
  left_join(select(pop_df, rd_name, log_pop), by = "rd_name") %>%
  left_join(select(rd_agg, rd_name, log_stations), by = "rd_name") %>%
  filter(!is.na(log_pop), !is.na(R_CTY), !is.na(log_stations))

message("Stations (Eng/Wales): ", nrow(df))
message("Counties: ", n_distinct(df$R_CTY), " | Divisions: ", n_distinct(df$R_DIV))

# -----------------------------------------------------------------------------
# 2. Run regressions (LPM + pop, with/without FE)
# -----------------------------------------------------------------------------
mods_none <- mods_county <- mods_div <- list()
for (i in seq_along(labels)) {
  lab <- labels[i]
  y_col <- paste0("has_union_", lab)
  x_col <- paste0("has_accident_", lab)
  if (!y_col %in% names(df)) next
  if (sum(df[[y_col]], na.rm = TRUE) == 0 || sum(df[[y_col]], na.rm = TRUE) == nrow(df)) next

  # No FE
  mods_none[[lab]] <- feols(
    as.formula(paste0(y_col, " ~ ", x_col, " + log_pop + log_stations")),
    data = df, vcov = "HC1"
  )
  # County FE
  mods_county[[lab]] <- feols(
    as.formula(paste0(y_col, " ~ ", x_col, " + log_pop + log_stations | R_CTY")),
    data = df, vcov = "HC1"
  )
  # Division FE
  mods_div[[lab]] <- feols(
    as.formula(paste0(y_col, " ~ ", x_col, " + log_pop + log_stations | R_DIV")),
    data = df, vcov = "HC1"
  )
}

# -----------------------------------------------------------------------------
# 3. Table: Coefficient on has_accident
# -----------------------------------------------------------------------------
coef_rename <- setNames(rep("Has accident", length(labels)), paste0("has_accident_", labels))

modelsummary(
  c(mods_none, mods_county, mods_div),
  coef_map = coef_rename,
  stars = c("*" = 0.1, "**" = 0.05, "***" = 0.01),
  title = "Accidents and Union Branches: Fixed Effects by County/Division",
  notes = "HC1 robust SE. Controls: log(area+1), log(stations in RD + 1)."
)

# Save results
res_long <- bind_rows(
  imap_dfr(mods_none, ~ tibble(radius = .y, fe = "None",   beta = coef(.x)[2], se = sqrt(diag(vcov(.x)))[2])),
  imap_dfr(mods_county, ~ tibble(radius = .y, fe = "County", beta = coef(.x)[1], se = sqrt(diag(vcov(.x)))[1])),
  imap_dfr(mods_div, ~ tibble(radius = .y, fe = "Division", beta = coef(.x)[1], se = sqrt(diag(vcov(.x)))[1]))
)
write_csv(res_long, file.path(base_path, "regression_with_FE_R.csv"))
message("Saved: regression_with_FE_R.csv")
