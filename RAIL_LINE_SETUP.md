# Railway Line Fixed Effects

**Identification:** The randomness of accidents is on the rail line — which stretch had the accident. We compare RDs on the **same** railway line: some had accidents, some didn't.

## 1. Get the 1861 Rail Lines shapefile

- **UK Data Service:** https://reshare.ukdataservice.ac.uk/852992/
- Register (free) and download `1861EnglandWalesandScotlandraillines.zip`
- Extract to `Processed_Data`, e.g. in a folder `6. 1861 England Wales and Scotland rail lines/`
- Expected file: `1861EnglandWalesandScotlandraillines.shp` (or similar)

## 2. Build RD–line mapping

```bash
python build_rd_line_mapping.py
```

This creates `rd_line_mapping.csv` with columns:
- `rd_name` — Registration District (must match rd1851_aggregates)
- `line_id` — primary railway line through the RD (longest track length)

## 3. Run RD-level regression with line FE

```r
source("Accidents_Unions_Regression_RD_Level.R")
```

The script automatically loads `rd_line_mapping.csv` when present and adds an **FE: Line** column to the table. Identification is within-line: RDs on the Liverpool & Manchester line are compared to each other; RDs on the London & Birmingham line to each other; etc.
