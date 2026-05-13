library(tidyverse)
library(sf)
library(leaflet)

# 1. SETUP & DATA LOAD
base_path <- "C:/Users/Keitaro Ninomiya/Box/Research Notes (keitaro2@illinois.edu)/RailwayUnions/Processed_Data"

# Helper for loading
load_web_sp <- function(csv, cache, col) {
  raw <- read_csv(file.path(base_path, csv), show_col_types = F) %>% mutate(k = str_trim(str_to_lower(!!sym(col))))
  geo <- read_csv(file.path(base_path, cache), show_col_types = F) %>% mutate(k = str_trim(str_to_lower(location))) %>% distinct(k, .keep_all = T)
  raw %>% left_join(geo %>% select(k, latitude, longitude), by = "k") %>% drop_na(latitude) %>%
    st_as_sf(coords = c("longitude", "latitude"), crs = 4326) 
}

# Load Data
stns <- st_read(file.path(base_path, "5. 1861 England, Wales and Scotland rail stations/1861EngWalesScotRail_Stations.shp"), quiet = T) %>% st_transform(4326)
acc  <- load_web_sp("detailed_accidents_data.csv", "cache_accident_geocoding.csv", "location")
uni  <- load_web_sp("ASRS/BalanceSheets/1875/Results/georeferenced_railway_results.csv", "cache_union_geocoding.csv", "cleaned_loc")

# 2. JITTER THE POINTS
# This slightly moves dots so they don't sit perfectly on top of each other
# factor = 0.001 is roughly 100 meters, enough to separate visual overlap
stns_j <- st_jitter(stns, amount = 0.01)
acc_j  <- st_jitter(acc, amount = 0.002) # Slightly more jitter for events
uni_j  <- st_jitter(uni, amount = 0.002)

# 3. INTERACTIVE MAP
leaflet() %>%
  addProviderTiles(providers$CartoDB.Positron) %>%
  
  # Layer 1: Stations (Black, Jittered)
  addCircleMarkers(data = stns_j,
                   radius = 1.5,      # Smaller
                   color = "black",   # Black
                   stroke = FALSE,
                   fillOpacity = 0.5,
                   group = "Stations") %>%
  
  # Layer 2: Accidents (Blue, Smaller, Jittered)
  addCircleMarkers(data = acc_j,
                   radius = 3,        # Reduced from 5 to 3
                   color = "#2980b9",
                   stroke = TRUE, 
                   weight = 1,
                   fillOpacity = 0.7,
                   popup = ~paste0("<b>Accident:</b> ", location),
                   group = "Accidents") %>%
  
  # Layer 3: Unions (Red, Smaller, Jittered)
  addCircleMarkers(data = uni_j,
                   radius = 4,        # Reduced from 6 to 4
                   color = "#c0392b",
                   stroke = TRUE,
                   weight = 1,
                   fillOpacity = 0.8,
                   popup = ~paste0("<b>Union:</b> ", cleaned_loc),
                   group = "Unions") %>%
  
  addLayersControl(
    overlayGroups = c("Unions", "Accidents", "Stations"),
    options = layersControlOptions(collapsed = FALSE)
  ) %>%
  addScaleBar(position = "bottomleft")