#!/usr/bin/env python3
"""Build Kane County precinct election data GeoJSON for the interactive map."""

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Configuration ──────────────────────────────────────────────────────────────
BASE_URL = "https://electionresults.kanecountyil.gov/2026-03-17/Precincts/"
OUTPUT_FILE = "kane_election_data.json"
OUTPUT_MUNI_FILE = "kane_municipalities.json"

# ArcGIS precinct boundaries
PRECINCT_URL = (
    "https://services1.arcgis.com/oRKmdBXD6EbdmVgJ/arcgis/rest/services/"
    "KaneCo_IL_ElectionsPrecincts/FeatureServer/1/query"
    "?where=1%3D1&outFields=*&outSR=4326&f=geojson&resultRecordCount=2000"
)

# ArcGIS municipality boundaries
MUNI_URL = (
    "https://services1.arcgis.com/oRKmdBXD6EbdmVgJ/arcgis/rest/services/"
    "KaneCo_IL_Municipalities/FeatureServer/1/query"
    "?where=1%3D1&outFields=*&outSR=4326&f=geojson&resultRecordCount=500"
)

# Name mapping from website format to RACE_CONFIG format
NAME_MAP = {
    "Kevin Ryan": "Kevin Ryan",
    "Robin Kelly": "Robin Kelly",
    "Juliana Stratton": "Juliana Stratton",
    "Raja Krishnamoorthi": "Raja Krishnamoorthi",
    "Steve Botsford Jr.": "Steve Botsford Jr.",
    "Bryan Maxwell": "Bryan Maxwell",
    "Jonathan Dean": "Jonathan Dean",
    "Sean Brown": "Sean Brown",
    "Awisi A. Bustos": "Awisi A. Bustos",
    "Christopher Swann": "Christopher Swann",
    "Adam Delgado": "Adam Delgado",
    # CD-8 candidates
    "Neil Khot": "Neil Khot",
    "Yasmeen Bankole": "Yasmeen Bankole",
    "Kevin B. Morrison": "Kevin B. Morrison",
    "Dan Tully": "Dan Tully",
    "Ryan Vetticad": "Ryan Vetticad",
    "Melissa L. Bean": "Melissa L. Bean",
    "Junaid Ahmed": "Junaid Ahmed",
    "Sanjyot Dunung": "Sanjyot Dunung",
}

# Race mapping: website title substring -> (race_key, candidate_list)
RACE_DEFS = {
    "UNITED STATES SENATOR": ("race6", [
        "Juliana Stratton", "Raja Krishnamoorthi", "Robin Kelly", "Kevin Ryan",
        "Sean Brown", "Bryan Maxwell", "Christopher Swann", "Awisi A. Bustos",
        "Jonathan Dean", "Steve Botsford Jr.", "Adam Delgado"
    ]),
    "8TH CONGRESSIONAL": ("race14", [
        "Neil Khot", "Yasmeen Bankole", "Kevin B. Morrison", "Dan Tully",
        "Ryan Vetticad", "Melissa L. Bean", "Junaid Ahmed", "Sanjyot Dunung"
    ]),
}

ALL_RACE_KEYS = ['race6', 'race7', 'race8', 'race9', 'race10', 'race11',
                 'race12', 'race13', 'race14', 'race15', 'race16', 'race17']


def fetch_precinct_page(code):
    """Fetch and parse a single precinct page."""
    url = f"{BASE_URL}{code}/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        html = urllib.request.urlopen(req, timeout=30).read().decode()
        return code, html
    except Exception as e:
        print(f"  Error fetching {code}: {e}")
        return code, None


def parse_precinct_html(html):
    """Parse DEM races from a precinct HTML page."""
    results = {}
    contests = re.split(r'<div class="c"', html)
    for c in contests:
        if "DEM" not in c:
            continue
        title_m = re.search(r'<h2>\s*(.*?)\s*<span>\s*-\s*DEM', c, re.DOTALL)
        if not title_m:
            continue
        title = title_m.group(1).strip().upper()

        # Match to our race definitions
        race_key = None
        candidates = None
        for key_str, (rk, cands) in RACE_DEFS.items():
            if key_str in title:
                race_key = rk
                candidates = cands
                break
        if not race_key:
            continue

        # Get registered and ballots for this race
        reg_m = re.search(r'Registered Voters:\s*<b>(\d+)</b>', c)
        bal_m = re.search(r'Ballots Cast:\s*<b>(\d+)</b>', c)
        registered = int(reg_m.group(1)) if reg_m else 0
        ballots = int(bal_m.group(1)) if bal_m else 0

        # Parse candidate votes
        cand_votes = re.findall(
            r'<td class="b">(.*?)\s*\(DEM\)</td>\s*<td>(\d+)</td>', c
        )
        votes = {}
        for name, v in cand_votes:
            name = name.strip()
            mapped = NAME_MAP.get(name, name)
            votes[mapped] = int(v)

        total = sum(votes.values())
        results[race_key] = {
            "registered": registered,
            "ballots": ballots,
            "total": total,
            "votes": votes,
        }

    return results


def download_geojson(url, name):
    """Download GeoJSON from ArcGIS."""
    print(f"Downloading {name}...")
    all_features = []
    offset = 0
    while True:
        page_url = url + f"&resultOffset={offset}"
        req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        features = data.get("features", [])
        if not features:
            break
        all_features.extend(features)
        print(f"  {len(all_features)} features...")
        if len(features) < 2000:
            break
        offset += len(features)
    return {"type": "FeatureCollection", "features": all_features}


def round_coords(geom):
    """Round coordinates to 5 decimal places."""
    if geom["type"] == "MultiPolygon":
        geom["coordinates"] = [
            [[[round(c[0], 5), round(c[1], 5)] for c in ring] for ring in polygon]
            for polygon in geom["coordinates"]
        ]
    elif geom["type"] == "Polygon":
        geom["coordinates"] = [
            [[round(c[0], 5), round(c[1], 5)] for c in ring]
            for ring in geom["coordinates"]
        ]
    return geom


def point_in_polygon(px, py, polygon):
    """Simple ray-casting point-in-polygon test."""
    inside = False
    coords = polygon[0]  # exterior ring
    n = len(coords)
    j = n - 1
    for i in range(n):
        xi, yi = coords[i]
        xj, yj = coords[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def get_centroid(geom):
    """Get approximate centroid of a geometry."""
    if geom["type"] == "Polygon":
        coords = geom["coordinates"][0]
    elif geom["type"] == "MultiPolygon":
        coords = geom["coordinates"][0][0]
    else:
        return None, None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def main():
    # ── Get precinct codes and turnout from main page ────────────────────────
    print("Fetching precinct list...")
    req = urllib.request.Request(BASE_URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req).read().decode()
    rows = re.findall(
        r'<tr>\s*<td><a href="([A-Z]{2}\d{4})/">.*?</a></td>\s*<td>(\d+)</td>\s*<td>(\d+)</td>',
        html, re.DOTALL,
    )
    codes = [r[0] for r in rows]
    print(f"  {len(codes)} precincts found")

    # ── Scrape all precinct pages ────────────────────────────────────────────
    print(f"\nScraping {len(codes)} precinct pages (10 threads)...")
    all_results = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(fetch_precinct_page, c): c for c in codes}
        done = 0
        for f in as_completed(futures):
            code, page_html = f.result()
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(codes)} fetched...")
            if page_html:
                all_results[code] = parse_precinct_html(page_html)

    print(f"  Parsed {len(all_results)} precincts")

    # Count races
    race_counts = {}
    for code, races in all_results.items():
        for rk in races:
            race_counts[rk] = race_counts.get(rk, 0) + 1
    for rk, cnt in sorted(race_counts.items()):
        print(f"  {rk}: {cnt} precincts")

    # ── Download precinct boundaries ─────────────────────────────────────────
    precincts_gj = download_geojson(PRECINCT_URL, "precinct boundaries")
    print(f"  {len(precincts_gj['features'])} precinct polygons")

    # ── Download municipality boundaries ─────────────────────────────────────
    munis_gj = download_geojson(MUNI_URL, "municipality boundaries")
    print(f"  {len(munis_gj['features'])} municipality polygons")

    # ── Build precinct name mapping ──────────────────────────────────────────
    # Need to match precinct codes (AU0001) to GIS precinct features
    # Check GIS properties
    sample = precincts_gj["features"][0]["properties"]
    print(f"\nGIS precinct properties: {list(sample.keys())}")
    print(f"Sample: {sample}")

    # ── Spatial join municipalities to precincts ─────────────────────────────
    print("\nSpatial joining municipalities to precincts...")
    muni_lookup = []
    for mf in munis_gj["features"]:
        mp = mf["properties"]
        geom = mf.get("geometry")
        if not geom:
            continue
        name = None
        for key in ["NAME", "Name", "MUNI_NAME", "MunicipalityName", "Municipality", "MUNICIPALI"]:
            if key in mp and mp[key]:
                name = mp[key]
                break
        if not name:
            for k, v in mp.items():
                if isinstance(v, str) and len(v) > 1:
                    name = v
                    break
        if name:
            muni_lookup.append((name, geom))

    def find_municipality(px, py):
        for name, geom in muni_lookup:
            if geom["type"] == "Polygon":
                if point_in_polygon(px, py, geom["coordinates"]):
                    return name
            elif geom["type"] == "MultiPolygon":
                for poly in geom["coordinates"]:
                    if point_in_polygon(px, py, poly):
                        return name
        return "Unincorporated"

    # ── Merge data ───────────────────────────────────────────────────────────
    print("\nMerging election data with precinct boundaries...")
    features_out = []
    matched = 0
    unmatched_codes = []

    for feature in precincts_gj["features"]:
        props = feature["properties"]
        geom = feature["geometry"]

        # Find precinct code from GIS properties
        # GIS uses "AU01" format, website uses "AU0001" format
        gis_code = str(props.get("PRECINCT", "")).strip()
        # Convert GIS code to website code: AU01 -> AU0001
        m = re.match(r'^([A-Z]{2})(\d+)$', gis_code)
        if m:
            prefix, num = m.groups()
            precinct_code = f"{prefix}{int(num):04d}"
        else:
            precinct_code = gis_code

        # Get centroid for municipality lookup
        cx, cy = get_centroid(geom)
        municipality = find_municipality(cx, cy) if cx else "Unknown"

        # Build display name
        display_name = precinct_code or "UNKNOWN"

        new_props = {
            "name": display_name,
            "municipality": municipality,
            "jurisdiction": "kane",
        }

        # Initialize all race flags
        for rkey in ALL_RACE_KEYS:
            new_props[f"has_{rkey}"] = False

        # Match to election data
        if precinct_code and precinct_code in all_results:
            matched += 1
            for race_key, data in all_results[precinct_code].items():
                race_def = None
                for key_str, (rk, cands) in RACE_DEFS.items():
                    if rk == race_key:
                        race_def = (rk, cands)
                        break
                if not race_def:
                    continue

                rk, candidates = race_def
                new_props[f"has_{rk}"] = True
                new_props[f"{rk}_registered"] = data["registered"]
                new_props[f"{rk}_ballots"] = data["total"]
                new_props[f"{rk}_total"] = data["total"]

                winner = None
                winner_votes = 0
                for cand in candidates:
                    v = data["votes"].get(cand, 0)
                    new_props[f"{rk}_{cand}"] = v
                    if v > winner_votes:
                        winner_votes = v
                        winner = cand

                new_props[f"{rk}_winner"] = winner
                new_props[f"{rk}_winner_pct"] = (
                    round(winner_votes / data["total"] * 100, 1) if data["total"] > 0 else 0
                )
        else:
            if precinct_code:
                unmatched_codes.append(precinct_code)

        features_out.append({
            "type": "Feature",
            "properties": new_props,
            "geometry": round_coords(geom),
        })

    print(f"  {matched}/{len(precincts_gj['features'])} matched to election data")
    if unmatched_codes:
        print(f"  Unmatched codes: {unmatched_codes[:20]}...")

    # ── Write election data ──────────────────────────────────────────────────
    output = {"type": "FeatureCollection", "features": features_out}
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    size_mb = len(json.dumps(output, separators=(",", ":"))) / 1024 / 1024
    print(f"\n  Written to {OUTPUT_FILE} ({size_mb:.1f} MB)")

    # ── Write municipality boundaries ────────────────────────────────────────
    muni_features = []
    for mf in munis_gj["features"]:
        mp = mf["properties"]
        geom = mf.get("geometry")
        if not geom:
            continue
        name = None
        for key in ["NAME", "Name", "MUNI_NAME", "MunicipalityName", "Municipality", "MUNICIPALI"]:
            if key in mp and mp[key]:
                name = mp[key]
                break
        if not name:
            for k, v in mp.items():
                if isinstance(v, str) and len(v) > 1:
                    name = v
                    break
        if name:
            muni_features.append({
                "type": "Feature",
                "properties": {"name": name},
                "geometry": round_coords(mf["geometry"]),
            })

    muni_output = {"type": "FeatureCollection", "features": muni_features}
    with open(OUTPUT_MUNI_FILE, "w") as f:
        json.dump(muni_output, f, separators=(",", ":"))
    print(f"  Written to {OUTPUT_MUNI_FILE} ({len(muni_features)} municipalities)")


if __name__ == "__main__":
    main()
