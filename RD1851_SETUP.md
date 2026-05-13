# 1851 Registration District Setup

This project assigns all locations (accidents, branches, stations) to **1851 Census Registration Districts** for uniform, census-matchable geography.

## Data source: 1851 Registration District boundaries

**England & Wales** (624 registration districts):
- **UK Data Service ReShare**: https://reshare.ukdataservice.ac.uk/852948/
  - Register/login (free for research)
  - Download the shapefile (1851EngWalesRegistrationDistrict.shp or similar)
  - Extract to a folder, e.g. `Processed_Data\1851_RegistrationDistricts\`

- **Campop (Cambridge Group)**: https://www.campop.geog.cam.ac.uk/research/occupations/datasets/catalogues/boundaries/
  - Dataset 7: "1851 England and Wales Census Registration Districts"
  - Filename: `1851EngWalesRegistrationDistrict.shp`
  - Contact Dr Max Satchell for access if needed

**Scotland**: The 1851 RD shapefile covers England & Wales only. Scottish stations will have `rd_name` = NaN. For Scotland, you can use:
- Campop 1851 Scotland counties: `1851ScotCounty.shp`
- Or Cambridge repository: consistent Scottish RDs 1851–1901

## Census matching

1851 and 1861 England & Wales censuses report data at **registration district** level. Merge your RD-level outputs (`rd1851_aggregates.csv`, `accidents_with_rd1851.csv`, etc.) with census tables on the registration district name or code.

Common census sources:
- UK Data Service / Histpop / Vision of Britain for 1851/1861 RD-level statistics
- Campop occupations project has RD-linked census data

## File structure

After setup, your `Processed_Data` folder should have:
```
Processed_Data/
├── 1851_RegistrationDistricts/
│   ├── 1851EngWalesRegistrationDistrict.shp
│   ├── 1851EngWalesRegistrationDistrict.shx
│   ├── 1851EngWalesRegistrationDistrict.dbf
│   └── 1851EngWalesRegistrationDistrict.prj
├── cache_accident_geocoding.csv    # from R pipeline or Merge geocoding
├── cache_union_geocoding.csv
└── ...
```

Update `rd_1851_shp` in Merge.ipynb cell 1 if your path differs.
