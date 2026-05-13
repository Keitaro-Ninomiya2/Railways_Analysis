# Railway Union Data Compile

Preliminary analysis for the Victorian railway unions project.

## Main outputs

- `Slide/railway_union_slides.pdf`: current presentation deck.
- `Slide/railway_union_slides.tex`: Beamer source for the deck.
- `combined_map.png`, `asrs_branch_map.png`, `accident_map.png`: lightweight map images used in the deck.
- `station_analysis_clean_dismissals.csv`: cleaned personnel/register analysis data.
- `branch_accident_intensity.csv`: ASRS branch-level pre-1875 accident intensity.

## Rebuild the slides

From the `Slide/` directory:

```powershell
latexmk -pdf -interaction=nonstopmode -halt-on-error railway_union_slides.tex
```

The deck intentionally uses PNG map images rather than vector PDFs to keep the shared PDF small.
