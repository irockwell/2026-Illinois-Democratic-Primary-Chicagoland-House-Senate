#!/usr/bin/env python3
"""Build Chicago precinct election data GeoJSON for the interactive map."""

import json
import urllib.request
import xlrd

# ── Configuration ──────────────────────────────────────────────────────────────
SENATE_FILE = "Chicago Dem Senate.xls"
CD7_FILE = "Chicago CD 7.xls"
GEOJSON_URL = "https://data.cityofchicago.org/resource/i8fv-xe4b.geojson?$limit=5000"
OUTPUT_FILE = "chicago_election_data.json"

# Candidate lists (same order as Suburban Cook for consistent coloring)
SENATE_CANDIDATES = [
    "Juliana Stratton", "Raja Krishnamoorthi", "Robin Kelly", "Kevin Ryan",
    "Sean Brown", "Bryan Maxwell", "Christopher Swann", "Awisi A. Bustos",
    "Jonathan Dean", "Steve Botsford Jr."
]
CD7_CANDIDATES = [
    "La Shawn K. Ford", "Kina Collins", "Melissa Conyears-Ervin",
    "Anthony Driver, Jr.", "Thomas Fisher", "Jason Friedman",
    "Reed Showalter", "Anabel Mendoza", "Richard R. Boykin",
    "Rory Hoskins", "Jazmin J. Robinson", "David Ehrlich", "Felix Tello"
]


def parse_xls(filename):
    """Parse Chicago election XLS into {(ward, precinct): {candidate: votes, ...}}"""
    wb = xlrd.open_workbook(filename, ignore_workbook_corruption=True)
    ws = wb.sheet_by_index(0)

    # Get candidate columns from header row (row 4)
    header = [str(ws.cell_value(4, c)) for c in range(ws.ncols)]
    # Find candidate columns (skip Precinct, Total Voters, and % columns)
    cand_cols = {}
    for c, name in enumerate(header):
        if name and name not in ("Precinct", "Total Voters", "%", ""):
            cand_cols[c] = name

    results = {}
    current_ward = None

    for r in range(ws.nrows):
        cell0 = str(ws.cell_value(r, 0)).strip()

        # Detect ward header
        if cell0.startswith("Ward "):
            try:
                current_ward = int(cell0.replace("Ward ", ""))
            except ValueError:
                pass
            continue

        # Skip header rows, totals, empty rows
        if cell0 in ("Precinct", "Total", "", "Total Votes") or current_ward is None:
            continue

        # Try to parse precinct number
        try:
            precinct = int(float(cell0))
        except (ValueError, TypeError):
            continue

        # Read total voters
        try:
            total_voters = int(float(ws.cell_value(r, 1)))
        except (ValueError, TypeError):
            total_voters = 0

        # Read candidate votes
        votes = {}
        for c, cand_name in cand_cols.items():
            try:
                votes[cand_name] = int(float(ws.cell_value(r, c)))
            except (ValueError, TypeError):
                votes[cand_name] = 0

        results[(current_ward, precinct)] = {
            "total_voters": total_voters,
            "votes": votes
        }

    return results


def main():
    # ── Parse election results ──────────────────────────────────────────────
    print("Parsing Senate results...")
    senate_results = parse_xls(SENATE_FILE)
    print(f"  Found {len(senate_results)} ward-precinct entries")

    print("Parsing CD-7 results...")
    cd7_results = parse_xls(CD7_FILE)
    print(f"  Found {len(cd7_results)} ward-precinct entries")

    # ── Download precinct boundaries ────────────────────────────────────────
    print("Downloading Chicago precinct boundaries...")
    req = urllib.request.Request(GEOJSON_URL, headers={"User-Agent": "Mozilla/5.0"})
    geojson = json.loads(urllib.request.urlopen(req).read())
    print(f"  {len(geojson['features'])} precinct polygons")

    # ── Merge data ──────────────────────────────────────────────────────────
    matched_senate = 0
    matched_cd7 = 0
    features_out = []

    for feature in geojson["features"]:
        props = feature["properties"]
        ward = int(props["ward"])
        precinct = int(props["precinct"])
        key = (ward, precinct)

        new_props = {
            "name": f"CHICAGO {ward}-{precinct}",
            "municipality": "Chicago",
            "jurisdiction": "chicago"
        }

        # Senate data
        if key in senate_results:
            sr = senate_results[key]
            new_props["has_race6"] = True
            new_props["race6_ballots"] = sr["total_voters"]
            new_props["race6_registered"] = 0  # Not in this dataset

            winner = None
            winner_votes = 0
            for cand in SENATE_CANDIDATES:
                v = sr["votes"].get(cand, 0)
                col_name = f"race6_{cand}"
                new_props[col_name] = v
                if v > winner_votes:
                    winner_votes = v
                    winner = cand
            new_props["race6_winner"] = winner
            matched_senate += 1
        else:
            new_props["has_race6"] = False

        # CD-7 data
        if key in cd7_results:
            cr = cd7_results[key]
            new_props["has_race7"] = True
            new_props["race7_ballots"] = cr["total_voters"]
            new_props["race7_registered"] = 0

            winner = None
            winner_votes = 0
            for cand in CD7_CANDIDATES:
                v = cr["votes"].get(cand, 0)
                col_name = f"race7_{cand}"
                new_props[col_name] = v
                if v > winner_votes:
                    winner_votes = v
                    winner = cand
            new_props["race7_winner"] = winner
            matched_cd7 += 1
        else:
            new_props["has_race7"] = False

        # Round coordinates to 5 decimal places for smaller file
        geom = feature["geometry"]
        if geom["type"] == "MultiPolygon":
            geom["coordinates"] = [
                [[
                    [round(c[0], 5), round(c[1], 5)] for c in ring
                ] for ring in polygon]
                for polygon in geom["coordinates"]
            ]
        elif geom["type"] == "Polygon":
            geom["coordinates"] = [
                [[round(c[0], 5), round(c[1], 5)] for c in ring]
                for ring in geom["coordinates"]
            ]

        features_out.append({
            "type": "Feature",
            "properties": new_props,
            "geometry": geom
        })

    print(f"\n  Senate matched: {matched_senate}/{len(geojson['features'])}")
    print(f"  CD-7 matched: {matched_cd7}/{len(geojson['features'])}")

    # ── Write output ────────────────────────────────────────────────────────
    output = {
        "type": "FeatureCollection",
        "features": features_out
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    size_mb = len(json.dumps(output, separators=(",", ":"))) / 1024 / 1024
    print(f"\n  Written to {OUTPUT_FILE} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
