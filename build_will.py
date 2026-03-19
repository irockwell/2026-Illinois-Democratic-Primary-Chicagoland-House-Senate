#!/usr/bin/env python3
"""Build Will County precinct election data GeoJSON for the interactive map."""

import json
import urllib.request
from shapely.geometry import shape, mapping
from shapely.validation import make_valid

# ── Configuration ──────────────────────────────────────────────────────────────
PRECINCT_URL = "https://gis.willcountyillinois.com/hosting/rest/services/PoliticalLayers/Precincts/MapServer/0/query"
MUNI_URL = "https://gis.willcountyillinois.com/hosting/rest/services/Hosted/Municipalities/FeatureServer/0/query"
DETAIL_FILE = "will_txt/detail.txt"
OUTPUT_FILE = "will_election_data.json"
MUNI_OUTPUT_FILE = "will_municipalities.json"

# Map ALL CAPS names to Title Case matching RACE_CONFIG
NAME_MAP = {
    # Senate
    "JULIANA STRATTON": "Juliana Stratton",
    "RAJA KRISHNAMOORTHI": "Raja Krishnamoorthi",
    "ROBIN KELLY": "Robin Kelly",
    "KEVIN RYAN": "Kevin Ryan",
    "SEAN BROWN": "Sean Brown",
    "BRYAN MAXWELL": "Bryan Maxwell",
    "CHRISTOPHER SWANN": "Christopher Swann",
    "AWISI A. BUSTOS": "Awisi A. Bustos",
    "JONATHAN DEAN": "Jonathan Dean",
    "STEVE BOTSFORD JR.": "Steve Botsford Jr.",
    "ADAM DELGADO": "Adam Delgado",
    # CD-2
    "DONNA MILLER": "Donna Miller",
    "ERIC FRANCE": "Eric France",
    "ROBERT PETERS": "Robert Peters",
    "WILLIE PRESTON": "Willie Preston",
    "JESSE LOUIS JACKSON, JR.": "Jesse Louis Jackson, Jr.",
    "YUMEKA BROWN": "Yumeka Brown",
    'PATRICK J. "PJK" KEATING': 'Patrick J. "PJK" Keating',
    "TONI C. BROWN": "Toni C. Brown",
    "SIDNEY MOORE": "Sidney Moore",
    "ADAL REGIS": "Adal Regis",
}

def normalize_name(name):
    return NAME_MAP.get(name, name)

ALL_RACE_KEYS = ['race6','race7','race8','race9','race10','race11',
                 'race12','race13','race14','race15','race16','race17']

# Democratic race sections in detail.txt
# race_key -> (title_text_to_match, is_democratic_section)
RACE_DEFS = {
    "race6": "FOR UNITED STATES SENATOR",
    "race8": "FOR REPRESENTATIVE IN CONGRESS 2ND CONGRESSIONAL DISTRICT",
}


def download_geojson(base_url, max_records=2000):
    """Download all features from an ArcGIS layer as GeoJSON."""
    url = f"{base_url}?where=1%3D1&outFields=*&outSR=4326&f=geojson&resultRecordCount={max_records}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=60).read())
    features = data.get("features", [])
    print(f"  Downloaded {len(features)} features")
    return {"type": "FeatureCollection", "features": features}


def parse_detail_txt(filename):
    """Parse Will County detail.txt for Democratic race results.

    The file has both Republican and Democratic results.
    Format: fixed-width columns, 30 chars each.
    Candidate header row has names at every 4th column group (Election Day, Early Voting, Vote by Mail, Choice Total).
    """
    with open(filename) as f:
        lines = f.readlines()

    # Find all Democratic race sections
    # The Democratic section comes after the Republican section
    # We identify it by finding the second occurrence of each race title
    # that has Democratic candidates (e.g., JULIANA STRATTON for Senate)

    race_sections = {}  # race_key -> (start_line, candidates)

    # First, find all race title lines
    title_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        for race_key, title_match in RACE_DEFS.items():
            if stripped.startswith(title_match) and "(Vote For" in stripped:
                title_lines.append((i, race_key, stripped))

    # For each race, we need the Democratic version (second occurrence)
    # We can verify by checking candidate names
    race_occurrences = {}
    for line_num, race_key, title in title_lines:
        if race_key not in race_occurrences:
            race_occurrences[race_key] = []
        race_occurrences[race_key].append(line_num)

    for race_key, line_nums in race_occurrences.items():
        # Check each occurrence for Democratic candidates
        for start in line_nums:
            cand_line = lines[start + 1].strip()
            # Check if it has Democratic candidate names
            is_dem = False
            if race_key == "race6" and "JULIANA STRATTON" in cand_line.upper():
                is_dem = True
            elif race_key == "race8" and "DONNA MILLER" in cand_line.upper():
                is_dem = True

            if is_dem:
                race_sections[race_key] = start
                break

    # Parse each race section
    all_results = {}
    all_candidates = {}

    for race_key, start_line in race_sections.items():
        print(f"  Parsing {race_key} starting at line {start_line}...")

        # Parse candidate names from the candidate header line
        cand_line = lines[start_line + 1]
        # Candidates are separated by spaces, each occupying ~30 char columns
        # Parse by splitting on multiple spaces
        candidates = []
        # The candidate line has names at positions corresponding to "Choice Total" columns
        # Each candidate block is 4 columns x 30 chars = 120 chars
        # But the first two columns are Precinct (30) and Registered Voters (30)
        # So candidates start at position 60

        # Split the candidate line by finding non-space sequences
        parts = []
        i = 0
        in_word = False
        word_start = 0
        while i < len(cand_line):
            if cand_line[i] != ' ' and cand_line[i] != '\n':
                if not in_word:
                    word_start = i
                    in_word = True
            else:
                if in_word:
                    # Check if this is just a space within a name (less than 4 spaces)
                    next_non_space = i
                    while next_non_space < len(cand_line) and cand_line[next_non_space] == ' ':
                        next_non_space += 1
                    gap = next_non_space - i
                    if gap < 4 and next_non_space < len(cand_line) and cand_line[next_non_space] != '\n':
                        # Part of the same name
                        i = next_non_space
                        continue
                    else:
                        parts.append((word_start, cand_line[word_start:i].strip()))
                        in_word = False
            i += 1
        if in_word:
            parts.append((word_start, cand_line[word_start:].strip()))

        # Filter out empty parts and "Unassigned write-ins"
        candidates = []
        for pos, name in parts:
            name = name.strip()
            if name and "Unassigned" not in name and "write-in" not in name.lower():
                candidates.append(normalize_name(name))

        print(f"    Candidates: {candidates}")

        # Parse column header line to find "Choice Total" positions
        header_line = lines[start_line + 2]
        # Find all "Choice Total" column positions
        choice_total_positions = []
        search_start = 0
        while True:
            pos = header_line.find("Choice Total", search_start)
            if pos == -1:
                break
            choice_total_positions.append(pos)
            search_start = pos + 1

        # Also find "Registered Voters" position
        reg_pos = header_line.find("Registered Voters")

        print(f"    Choice Total columns at positions: {choice_total_positions}")
        print(f"    Registered Voters at position: {reg_pos}")

        # Parse data rows
        results = {}
        for r in range(start_line + 3, len(lines)):
            line = lines[r]
            stripped = line.strip()
            if not stripped or stripped.startswith("Totals:") or stripped.startswith("FOR "):
                break

            # Parse precinct name (first 30 chars)
            precinct_name = line[:30].strip()
            if not precinct_name:
                continue

            # Parse registered voters
            try:
                reg_str = line[reg_pos:reg_pos+30].strip()
                registered = int(reg_str) if reg_str else 0
            except (ValueError, IndexError):
                registered = 0

            # Parse each candidate's Choice Total
            votes = {}
            total = 0
            for ci, cand in enumerate(candidates):
                if ci < len(choice_total_positions):
                    pos = choice_total_positions[ci]
                    try:
                        val_str = line[pos:pos+30].strip()
                        v = int(val_str) if val_str else 0
                    except (ValueError, IndexError):
                        v = 0
                    votes[cand] = v
                    total += v
                else:
                    votes[cand] = 0

            results[precinct_name] = {
                "registered": registered,
                "votes": votes,
                "total": total
            }

        all_results[race_key] = results
        all_candidates[race_key] = candidates
        print(f"    {len(results)} precincts parsed")

    return all_results, all_candidates


def main():
    # ── Download precinct boundaries ────────────────────────────────────────
    print("Downloading Will County precinct boundaries...")
    precincts_gj = download_geojson(PRECINCT_URL)

    # ── Download municipality boundaries ────────────────────────────────────
    print("\nDownloading Will County municipality boundaries...")
    munis_gj = download_geojson(MUNI_URL)

    # ── Spatial join: assign municipality to each precinct ──────────────────
    print("\nAssigning municipalities to precincts...")
    muni_shapes = []
    for mf in munis_gj["features"]:
        name = mf["properties"].get("name", "")
        if not name:
            continue
        s = shape(mf["geometry"])
        if not s.is_valid:
            s = make_valid(s)
        muni_shapes.append((name.title(), s.buffer(0)))
    print(f"  {len(muni_shapes)} municipality polygons")

    assigned = 0
    for feat in precincts_gj["features"]:
        geom = shape(feat["geometry"])
        centroid = geom.representative_point()
        feat["properties"]["_municipality"] = "Unincorporated"
        for mname, mshape in muni_shapes:
            if mshape.contains(centroid):
                feat["properties"]["_municipality"] = mname
                assigned += 1
                break
    print(f"  Assigned: {assigned}/{len(precincts_gj['features'])} precincts")

    # ── Parse election results ──────────────────────────────────────────────
    print(f"\nParsing {DETAIL_FILE}...")
    all_results, all_candidates = parse_detail_txt(DETAIL_FILE)

    # ── Build precinct name lookup ──────────────────────────────────────────
    # GIS NAME format: "CUSTER PCT 001"
    # TXT precinct format: "CUSTER PCT 001"
    # They should match directly

    # ── Build output features ───────────────────────────────────────────────
    print("\nMerging data...")
    features_out = []
    match_counts = {rk: 0 for rk in RACE_DEFS}

    for feat in precincts_gj["features"]:
        p = feat["properties"]
        precinct_name = p.get("NAME", "")
        muni = p.get("_municipality", "Unincorporated")

        new_props = {
            "name": precinct_name,
            "municipality": muni,
            "jurisdiction": "will"
        }

        # Initialize all race flags
        for rk in ALL_RACE_KEYS:
            new_props[f"has_{rk}"] = False

        # Merge election results
        for race_key in RACE_DEFS:
            if race_key in all_results and precinct_name in all_results[race_key]:
                data = all_results[race_key][precinct_name]
                new_props[f"has_{race_key}"] = True
                new_props[f"{race_key}_registered"] = data["registered"]
                new_props[f"{race_key}_ballots"] = data["total"]
                new_props[f"{race_key}_total"] = data["total"]

                winner = None
                winner_votes = 0
                for cand, votes in data["votes"].items():
                    new_props[f"{race_key}_{cand}"] = votes
                    if votes > winner_votes:
                        winner_votes = votes
                        winner = cand

                if winner:
                    new_props[f"{race_key}_winner"] = winner
                    new_props[f"{race_key}_winner_pct"] = round(
                        winner_votes / data["total"] * 100, 1
                    ) if data["total"] > 0 else 0

                match_counts[race_key] += 1

        # Round coordinates
        geom = feat["geometry"]
        if geom["type"] == "MultiPolygon":
            geom["coordinates"] = [
                [[[round(c[0], 5), round(c[1], 5)] for c in ring]
                 for ring in polygon]
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

    print(f"\nMatch results ({len(precincts_gj['features'])} total precincts):")
    for rk in RACE_DEFS:
        print(f"  {rk}: {match_counts[rk]} matched")

    # ── Write election data ─────────────────────────────────────────────────
    output = {"type": "FeatureCollection", "features": features_out}
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    size_mb = len(json.dumps(output, separators=(",", ":"))) / 1024 / 1024
    print(f"\nWritten to {OUTPUT_FILE} ({size_mb:.1f} MB)")

    # ── Write municipality boundaries ───────────────────────────────────────
    muni_features = []
    for mf in munis_gj["features"]:
        name = mf["properties"].get("name", "")
        if not name:
            continue
        geom = mf["geometry"]
        if geom["type"] == "MultiPolygon":
            geom["coordinates"] = [
                [[[round(c[0], 5), round(c[1], 5)] for c in ring]
                 for ring in polygon]
                for polygon in geom["coordinates"]
            ]
        elif geom["type"] == "Polygon":
            geom["coordinates"] = [
                [[round(c[0], 5), round(c[1], 5)] for c in ring]
                for ring in geom["coordinates"]
            ]
        muni_features.append({
            "type": "Feature",
            "properties": {"name": name.title()},
            "geometry": geom
        })

    muni_output = {"type": "FeatureCollection", "features": muni_features}
    with open(MUNI_OUTPUT_FILE, "w") as f:
        json.dump(muni_output, f, separators=(",", ":"))
    print(f"Written to {MUNI_OUTPUT_FILE} ({len(muni_features)} municipalities)")

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n=== SUMMARY ===")
    for race_key in RACE_DEFS:
        if race_key not in all_candidates:
            continue
        candidates = all_candidates[race_key]
        results = all_results[race_key]
        totals = {c: 0 for c in candidates}
        winner_counts = {}
        for data in results.values():
            for c, v in data["votes"].items():
                totals[c] += v
            if data["total"] > 0:
                w = max(data["votes"], key=data["votes"].get)
                winner_counts[w] = winner_counts.get(w, 0) + 1

        grand = sum(totals.values())
        ranked = sorted(candidates, key=lambda c: totals[c], reverse=True)
        print(f"\n{race_key} ({RACE_DEFS[race_key]}):")
        for c in ranked:
            pct = totals[c] / grand * 100 if grand > 0 else 0
            wins = winner_counts.get(c, 0)
            print(f"  {c}: {totals[c]:,} ({pct:.1f}%), {wins} precincts won")


if __name__ == "__main__":
    main()
