# Factory / Industry Data by Registration District

To control for industry structure (number of factories per region), add a CSV with factory counts by 1851 Registration District.

## CSV format

Required columns:
- **rd_name** — must match the RD names in `rd1851_aggregates.csv` (e.g. from CEN1 in the shapefile)
- **factory_count** (or **n_factories** or **factories**) — number of factories in the RD

Example:
```csv
rd_name,factory_count
"Abingdon",12
"Basingstoke",8
...
```

Save as `factories_by_rd1851.csv` in `Processed_Data`, then in `Accidents_Unions_Regression_RD_Level.R` set:
```r
factory_csv <- file.path(base_path, "factories_by_rd1851.csv")
```

## Data sources

Possible sources for factory/manufacturing counts by 1851 RD:

- **1851 Census occupational data** — Registration District occupational tables (e.g. workers in manufacturing). CESSDA: https://datacatalogue.cessda.eu/ (search "1851 Census Registration District Occupational")
- **Campop (Cambridge Group)** — https://www.campop.geog.cam.ac.uk/research/occupations/datasets/ — RD-linked occupational and industrial statistics
- **UK Data Service / Vision of Britain** — Historical statistics by RD
- **Factory/workshop directories** — If digitized and geocoded, aggregate to RD via spatial join

The 1851 census used occupational classifications (e.g. mineral, vegetable, animal industries). You may need to define "factory" as establishments or workers in manufacturing; aggregate to RD and ensure `rd_name` matches your shapefile.
