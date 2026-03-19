#!/usr/bin/env python3
"""Build Lake County precinct election data GeoJSON for the interactive map."""

import json
import urllib.request
import xml.etree.ElementTree as ET
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.validation import make_valid

# ── Configuration ──────────────────────────────────────────────────────────────
PRECINCT_URL = "https://maps.lakecountyil.gov/arcgis/rest/services/GISMapping/WABPoliticalBoundaries/MapServer/5/query"
MUNI_URL = "https://maps.lakecountyil.gov/arcgis/rest/services/GISMapping/WABBoundaries/MapServer/1/query"
DETAIL_FILE = "lake_data/detailwithoutvotetypes.xls"
OUTPUT_FILE = "lake_election_data.json"
MUNI_OUTPUT_FILE = "lake_municipalities.json"

# XML spreadsheet sheet indices for DEM races
# From Table of Contents: 11=Senate, 17=CD-5, 19=CD-9, 21=CD-10
RACE_SHEETS = {
    "race6":  {"sheet_idx": 11, "title": "Senate"},
    "race12": {"sheet_idx": 17, "title": "CD-5"},
    "race15": {"sheet_idx": 19, "title": "CD-9"},
    "race16": {"sheet_idx": 21, "title": "CD-10"},
}

ALL_RACE_KEYS = ['race6','race7','race8','race9','race10','race11',
                 'race12','race13','race14','race15','race16','race17']


def download_geojson(base_url, max_records=1000):
    """Download all features from an ArcGIS MapServer layer as GeoJSON."""
    count_url = f"{base_url}?where=1%3D1&returnCountOnly=true&f=json"
    resp = urllib.request.urlopen(count_url)
    total = json.loads(resp.read())["count"]
    print(f"  Total features: {total}")

    all_features = []
    offset = 0
    while offset < total:
        url = (f"{base_url}?where=1%3D1&outFields=*&outSR=4326&f=geojson"
               f"&resultRecordCount={max_records}&resultOffset={offset}")
        resp = urllib.request.urlopen(url)
        data = json.loads(resp.read())
        features = data.get("features", [])
        all_features.extend(features)
        print(f"  Downloaded {len(all_features)}/{total}")
        offset += max_records
        if len(features) == 0:
            break

    return {"type": "FeatureCollection", "features": all_features}


def parse_xml_sheet(tree, sheet_idx):
    """Parse an XML spreadsheet sheet into {precinct_number: {candidate: votes}}.

    Format: Row 1=race title, Row 2=candidate names, Row 3=headers, Row 4+=data
    Data rows: col0=precinct_name (e.g. "Antioch 1"), col1=registered, col2+=votes
    """
    ns = {'s': 'urn:schemas-microsoft-com:office:spreadsheet'}
    sheets = tree.findall('.//s:Worksheet', ns)
    sheet = sheets[sheet_idx]

    rows = sheet.findall('.//s:Row', ns)

    # Row 2 (index 1): candidate names
    cand_row = rows[1]
    cand_cells = cand_row.findall('.//s:Cell/s:Data', ns)
    candidates = [c.text.strip() for c in cand_cells if c.text and c.text.strip()]

    # Data rows start at index 3
    results = {}
    for row in rows[3:]:
        cells = row.findall('.//s:Cell/s:Data', ns)
        vals = [c.text for c in cells]
        if not vals or not vals[0]:
            continue
        precinct_name = vals[0].strip()
        if precinct_name in ("Total:", "Total", ""):
            continue

        # Extract precinct number from "Township N"
        parts = precinct_name.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        try:
            prec_num = int(parts[1])
        except ValueError:
            continue

        # vals[1] = registered voters, vals[2:] = candidate votes
        try:
            registered = int(float(vals[1])) if len(vals) > 1 and vals[1] else 0
        except (ValueError, TypeError):
            registered = 0

        votes = {}
        total = 0
        for i, cand in enumerate(candidates):
            try:
                v = int(float(vals[2 + i])) if len(vals) > 2 + i and vals[2 + i] else 0
            except (ValueError, TypeError):
                v = 0
            votes[cand] = v
            total += v

        results[prec_num] = {
            "precinct_name": precinct_name,
            "registered": registered,
            "votes": votes,
            "total": total
        }

    return candidates, results


def round_coords(geom):
    """Round geometry coordinates to 5 decimal places."""
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
    return geom


def main():
    # ── Download precinct boundaries ────────────────────────────────────────
    print("Downloading Lake County precinct boundaries...")
    precincts_gj = download_geojson(PRECINCT_URL)

    # ── Download municipality boundaries ────────────────────────────────────
    print("\nDownloading Lake County municipality boundaries...")
    munis_gj = download_geojson(MUNI_URL)

    # ── Spatial join: assign municipality to each precinct ──────────────────
    print("\nAssigning municipalities to precincts...")
    muni_shapes = []
    for mf in munis_gj["features"]:
        name = mf["properties"].get("MUNI_NAME", "")
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

    # ── Build precinct number lookup ──────────────────────────────────────
    precinct_map = {}  # precinct_number -> index
    for i, feat in enumerate(precincts_gj["features"]):
        prec_num = feat["properties"]["PRECINCT"]
        precinct_map[prec_num] = i

    # ── Parse election results ──────────────────────────────────────────────
    print(f"\nParsing {DETAIL_FILE}...")
    tree = ET.parse(DETAIL_FILE)

    all_results = {}
    all_candidates = {}
    for race_key, info in RACE_SHEETS.items():
        print(f"  {race_key} ({info['title']}, sheet idx {info['sheet_idx']})...")
        candidates, results = parse_xml_sheet(tree, info["sheet_idx"])
        all_results[race_key] = results
        all_candidates[race_key] = candidates
        print(f"    {len(candidates)} candidates, {len(results)} precincts")

    # ── Build output features ───────────────────────────────────────────────
    print("\nMerging data...")
    features_out = []
    match_counts = {rk: 0 for rk in RACE_SHEETS}

    for feat in precincts_gj["features"]:
        p = feat["properties"]
        prec_num = p["PRECINCT"]
        muni = p.get("_municipality", "Unincorporated")

        new_props = {
            "name": f"LAKE {prec_num}",
            "municipality": muni,
            "jurisdiction": "lake"
        }

        # Initialize all race flags
        for rk in ALL_RACE_KEYS:
            new_props[f"has_{rk}"] = False

        # Merge election results
        for race_key, info in RACE_SHEETS.items():
            if prec_num in all_results[race_key]:
                data = all_results[race_key][prec_num]
                new_props[f"has_{race_key}"] = True
                new_props[f"{race_key}_registered"] = data["registered"]
                new_props[f"{race_key}_ballots"] = data["total"]
                new_props[f"{race_key}_total"] = data["total"]

                winner = max(data["votes"], key=data["votes"].get) if data["total"] > 0 else None
                if winner:
                    new_props[f"{race_key}_winner"] = winner
                    new_props[f"{race_key}_winner_pct"] = round(
                        data["votes"][winner] / data["total"] * 100, 1
                    ) if data["total"] > 0 else 0
                    new_props[f"{race_key}_winner_votes"] = data["votes"][winner]

                for cand, votes in data["votes"].items():
                    new_props[f"{race_key}_{cand}"] = votes

                match_counts[race_key] += 1

        features_out.append({
            "type": "Feature",
            "properties": new_props,
            "geometry": round_coords(feat["geometry"])
        })

    print(f"\nMatch results ({len(precincts_gj['features'])} total precincts):")
    for rk in RACE_SHEETS:
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
        name = mf["properties"].get("MUNI_NAME", "")
        if not name:
            continue
        muni_features.append({
            "type": "Feature",
            "properties": {"name": name.title()},
            "geometry": round_coords(mf["geometry"])
        })

    muni_output = {"type": "FeatureCollection", "features": muni_features}
    with open(MUNI_OUTPUT_FILE, "w") as f:
        json.dump(muni_output, f, separators=(",", ":"))
    print(f"Written to {MUNI_OUTPUT_FILE} ({len(muni_features)} municipalities)")

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n=== SUMMARY ===")
    for race_key, info in RACE_SHEETS.items():
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
        print(f"\n{race_key} ({info['title']}):")
        for c in ranked:
            pct = totals[c] / grand * 100 if grand > 0 else 0
            wins = winner_counts.get(c, 0)
            print(f"  {c}: {totals[c]:,} ({pct:.1f}%), {wins} precincts won")


if __name__ == "__main__":
    main()
