#!/usr/bin/env python3
"""Build Chicago precinct election data GeoJSON for the interactive map."""

import json
import urllib.request
import xlrd

# ── Configuration ──────────────────────────────────────────────────────────────
GEOJSON_URL = "https://data.cityofchicago.org/resource/i8fv-xe4b.geojson?$limit=5000"
OUTPUT_FILE = "chicago_election_data.json"
TURNOUT_FILE = "Chicago Turnout 3-24-26.xls"

# Race definitions: race_key -> (filename, candidate_list)
# Candidate lists match Suburban Cook ordering for consistent coloring
RACES = {
    "race6": ("Senate Chicago 3-24-26.xls", [
        "Juliana Stratton", "Raja Krishnamoorthi", "Robin Kelly", "Kevin Ryan",
        "Sean Brown", "Bryan Maxwell", "Christopher Swann", "Awisi A. Bustos",
        "Jonathan Dean", "Steve Botsford Jr."
    ]),
    "race7": ("Chicago CD 7 3-24-26.xls", [
        "La Shawn K. Ford", "Kina Collins", "Melissa Conyears-Ervin",
        "Anthony Driver, Jr.", "Thomas Fisher", "Jason Friedman",
        "Reed Showalter", "Anabel Mendoza", "Richard R. Boykin",
        "Rory Hoskins", "Jazmin J. Robinson", "David Ehrlich", "Felix Tello"
    ]),
    "race8": ("Chicago CD 2 3-24-26.xls", [
        "Donna Miller", "Eric France", "Robert Peters", "Willie Preston",
        "Jesse Louis Jackson, Jr.", "Yumeka Brown",
        'Patrick J. "PJK" Keating', "Toni C. Brown", "Sidney Moore", "Adal Regis"
    ]),
    "race12": ("Chicago CD 5 3-24-26.xls", [
        "Mike Quigley", "Matthew Conroy", "Anthony Michael Tamez", "Ellen A. Corley"
    ]),
    "race13": ("Chicago CD 6 3-24-26.xls", [
        "Sean Casten", 'Joseph "Joey" Ruzevich'
    ]),
    "race14": ("Chicago CD 8 3-24-26.xls", [
        "Neil Khot", "Yasmeen Bankole", "Kevin B. Morrison", "Dan Tully",
        "Ryan Vetticad", "Melissa L. Bean", "Junaid Ahmed", "Sanjyot Dunung"
    ]),
    "race15": ("Chicago CD 9 3-24-26.xls", [
        "Daniel Biss", "Justin Ford", "Mike Simmons", "Bushra Amiwala",
        "Patricia A. Brown", "Jeff Cohen", "Laura Fine", "Phil Andrew",
        "Nick Pyati", "Kat Abughazaleh", "Sam Polan", "Bethany Johnson",
        "Howard Rosenblum", "Hoan Huynh", "Mark Arnold Fredrickson"
    ]),
}

ALL_RACE_KEYS = ['race6','race7','race8','race9','race10','race11',
                 'race12','race13','race14','race15','race16','race17']


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


def parse_turnout(filename):
    """Parse Chicago turnout XLS into {(ward, precinct): {registered, ballots}}"""
    wb = xlrd.open_workbook(filename, ignore_workbook_corruption=True)
    ws = wb.sheet_by_index(0)
    results = {}
    current_ward = None
    for r in range(ws.nrows):
        cell0 = str(ws.cell_value(r, 0)).strip()
        if cell0.startswith("Ward "):
            try:
                current_ward = int(cell0.replace("Ward ", ""))
            except ValueError:
                pass
            continue
        if cell0 in ("Precinct", "Total", "", "Registered Voters") or current_ward is None:
            continue
        try:
            precinct = int(float(cell0))
        except (ValueError, TypeError):
            continue
        try:
            registered = int(float(ws.cell_value(r, 1)))
        except (ValueError, TypeError):
            registered = 0
        try:
            ballots = int(float(ws.cell_value(r, 2)))
        except (ValueError, TypeError):
            ballots = 0
        results[(current_ward, precinct)] = {"registered": registered, "ballots": ballots}
    return results


def main():
    # ── Parse election results ──────────────────────────────────────────────
    all_results = {}
    for race_key, (filename, candidates) in RACES.items():
        print(f"Parsing {race_key} ({filename})...")
        results = parse_xls(filename)
        all_results[race_key] = results
        print(f"  Found {len(results)} ward-precinct entries")

    # ── Parse turnout data ───────────────────────────────────────────────────
    print(f"\nParsing turnout ({TURNOUT_FILE})...")
    turnout_data = parse_turnout(TURNOUT_FILE)
    print(f"  Found {len(turnout_data)} ward-precinct entries")

    # ── Download precinct boundaries ────────────────────────────────────────
    print("\nDownloading Chicago precinct boundaries...")
    req = urllib.request.Request(GEOJSON_URL, headers={"User-Agent": "Mozilla/5.0"})
    geojson = json.loads(urllib.request.urlopen(req).read())
    print(f"  {len(geojson['features'])} precinct polygons")

    # ── Merge data ──────────────────────────────────────────────────────────
    match_counts = {rk: 0 for rk in RACES}
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

        # Initialize all race flags to False
        for rkey in ALL_RACE_KEYS:
            new_props[f"has_{rkey}"] = False

        # Process each race
        for race_key, (filename, candidates) in RACES.items():
            if key in all_results[race_key]:
                data = all_results[race_key][key]
                new_props[f"has_{race_key}"] = True
                new_props[f"{race_key}_ballots"] = data["total_voters"]
                new_props[f"{race_key}_total"] = data["total_voters"]
                turnout = turnout_data.get(key, {})
                new_props[f"{race_key}_registered"] = turnout.get("registered", 0)

                winner = None
                winner_votes = 0
                for cand in candidates:
                    v = data["votes"].get(cand, 0)
                    new_props[f"{race_key}_{cand}"] = v
                    if v > winner_votes:
                        winner_votes = v
                        winner = cand
                new_props[f"{race_key}_winner"] = winner
                match_counts[race_key] += 1

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

    print(f"\nMatch results ({len(geojson['features'])} total precincts):")
    for race_key in RACES:
        print(f"  {race_key}: {match_counts[race_key]} matched")

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
