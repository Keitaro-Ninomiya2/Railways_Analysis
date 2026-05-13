library(tidyverse)
library(sf)
library(fixest)
library(marginaleffects)
library(modelsummary)

# 1. SETUP & DATA PREP
base_path <- "C:/Users/Keitaro Ninomiya/Box/Research Notes (keitaro2@illinois.edu)/RailwayUnions/Processed_Data"

# Load Helper
load_sp <- function(csv, cache, col) {
  raw <- read_csv(file.path(base_path, csv), show_col_types = F) %>% mutate(k = str_trim(str_to_lower(!!sym(col))))
  geo <- read_csv(file.path(base_path, cache), show_col_types = F) %>% mutate(k = str_trim(str_to_lower(location))) %>% distinct(k, .keep_all = T)
  raw %>% left_join(geo %>% select(k, latitude, longitude), by = "k") %>% drop_na(latitude) %>%
    st_as_sf(coords = c("longitude", "latitude"), crs = 4326) 
}

# Load Data
stns_raw <- st_read(file.path(base_path, "5. 1861 England, Wales and Scotland rail stations/1861EngWalesScotRail_Stations.shp"), quiet = T)
acc_raw  <- load_sp("detailed_accidents_data.csv", "cache_accident_geocoding.csv", "location")
uni_raw  <- load_sp("ASRS/BalanceSheets/1875/Results/georeferenced_railway_results.csv", "cache_union_geocoding.csv", "cleaned_loc")

# === CRITICAL FIX: UNIFY CRS TO BRITISH NATIONAL GRID (27700) ===
stns <- st_transform(stns_raw, 27700)
acc  <- st_transform(acc_raw, 27700)
uni  <- st_transform(uni_raw, 27700)

# 2. CREATE REGRESSION DATAFRAME
df_reg <- stns %>%
  mutate(
    # Create Lat/Lon controls (must be from 4326 for meaningful "lat/lon" values)
    lat = scale(st_coordinates(st_transform(., 4326))[,2]),
    lon = scale(st_coordinates(st_transform(., 4326))[,1]),
    lat2 = lat^2, lon2 = lon^2, l_l = lat * lon,
    
    # INDEPENDENT VAR: Accident within 1 MILE (1609 meters)
    # Since 'stns' and 'acc' are both 27700 (meters), this works perfectly
    has_acc_1mi = as.numeric(lengths(st_intersects(st_buffer(., 1609), acc)) > 0),
    
    # DEPENDENT VARS: Varying distances
    has_uni_1km = as.numeric(lengths(st_intersects(st_buffer(., 1000), uni)) > 0),
    has_uni_1mi = as.numeric(lengths(st_intersects(st_buffer(., 1609), uni)) > 0),
    has_uni_5mi = as.numeric(lengths(st_intersects(st_buffer(., 8046), uni)) > 0)
  )

# 3. DEFINE MODELS (Accident = 1 Mile)
specs <- list(
  "(1) 1mi" = list(f = "has_uni_1mi ~ has_acc_1mi", ctrl = "No", dist = "1 mile"),
  "(2) 5mi" = list(f = "has_uni_5mi ~ has_acc_1mi", ctrl = "No", dist = "5 miles"),
  "(3) 1km" = list(f = "has_uni_1km ~ has_acc_1mi", ctrl = "No", dist = "1 km"),
  "(4) 1mi" = list(f = "has_uni_1mi ~ has_acc_1mi + lat + lon + lat2 + lon2 + l_l", ctrl = "Yes", dist = "1 mile")
)

# 4. RUN & TABLE
mfx_list <- map(specs, ~{
  mod <- feglm(as.formula(.x$f), data = df_reg, family = "logit", vcov = "HC1")
  mfx <- avg_slopes(mod, variables = "has_acc_1mi", newdata = st_drop_geometry(df_reg))
  
  y_var <- all.vars(as.formula(.x$f))[1]
  attr(mfx, "glance") <- data.frame(mean_y = mean(df_reg[[y_var]]), nobs = nrow(df_reg))
  return(mfx)
})

custom_rows <- data.frame(
  term = c("Spatial Controls", "Outcome Distance"),
  "(1) 1mi" = c("No",  "1 mile"),
  "(2) 5mi" = c("No",  "5 miles"),
  "(3) 1km" = c("No",  "1 km"),
  "(4) 1mi" = c("Yes", "1 mile"),
  check.names = FALSE
)

modelsummary(
  mfx_list,
  coef_map = c("has_acc_1mi" = "Accident (1 mile)"),
  stars = TRUE,
  add_rows = custom_rows,
  gof_map = list(list("raw"="mean_y", "clean"="Dep. Var. Mean", "fmt"=3),
                 list("raw"="nobs",   "clean"="Observations",   "fmt"=0)),
  title = "Logit Marginal Effects: Impact of Local Accidents (1 Mile) on Unions"
)