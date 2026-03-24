# 2026 Illinois Democratic Primary - Chicagoland Interactive Map

Interactive precinct-level results map for the 2026 Democratic primary across Chicagoland (Cook County and the collar counties), built with Leaflet.js.

## Features

- Precinct-level election results with hover tooltips and click details (click to pin results, click again to unpin and reenable hover)
- Race selector for U.S. Senate and 7 Congressional districts (CD-2, 5, 6, 7, 8, 9, 10)
- County toggles to show/hide regions
- Municipality, Chicago ward, and community area boundary overlays
- Split precinct handling for precincts straddling congressional district boundaries

## Data Sources

- [Chicago Board of Elections](https://chicagoelections.gov)
- [Cook County Clerk](https://results326.cookcountyclerkil.gov)
- DuPage, Kane, Lake, McHenry, and Will county clerk offices
- Precinct boundaries from county ArcGIS services and the City of Chicago data portal

## Building the Data

Requires Python 3 with `shapely`, `xlrd`, `requests`, and `openpyxl`.

Each county has its own build script:

| Script | Description |
|--------|-------------|
| `build_chicago.py` | Chicago precinct results from XLS files and city boundary API |
| `build_map.py` | Suburban Cook County results from Excel files |
| `build_dupage.py` | DuPage County results via ArcGIS and Excel |
| `build_lake.py` | Lake County results via ArcGIS and XML spreadsheets |
| `build_kane.py` | Kane County results via election website scraping |
| `build_mchenry.py` | McHenry County results via ArcGIS and Excel |
| `build_will.py` | Will County results via ArcGIS and text detail files |
| `clip_precincts.py` | Clips split precincts to congressional district boundaries using Census blocks |

## Deployment

Hosted on GitHub Pages from the `gh-pages` branch. The `index.html` and JSON data files are served directly.

## AI Disclosure

Built with Claude Code.
