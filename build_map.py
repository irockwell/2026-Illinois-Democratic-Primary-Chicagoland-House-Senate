import json
import re
import pandas as pd
from shapely.geometry import shape, Point

# --- Configuration ---
# Maps internal race key -> (file, district label)
RACE_FILES = {
    'race6':  ('Suburban Cook 3-24-26 Senate.xlsx',  'Senator, U.S.'),
    'race7':  ('CD 7 Suburban Cook 3-24-26.xlsx',  'U.S. Representative, 7th District'),
    'race8':  ('CD 2 Suburban Cook 3-24-26.xlsx',  'U.S. Representative, 2nd District'),
    'race9':  ('ElectionResults-9.xlsx',  'U.S. Representative, 1st District'),
    'race10': ('ElectionResults-10.xlsx', 'U.S. Representative, 3rd District'),
    'race11': ('ElectionResults-11.xlsx', 'U.S. Representative, 4th District'),
    'race12': ('CD 5 Suburban Cook 3-24-26.xlsx', 'U.S. Representative, 5th District'),
    'race13': ('CD 6 Suburban Cook 3-24-26.xlsx', 'U.S. Representative, 6th District'),
    'race14': ('CD 8 Suburban Cook 3-24-26.xlsx', 'U.S. Representative, 8th District'),
    'race15': ('CD 9 Suburban Cook 3-24-26.xlsx', 'U.S. Representative, 9th District'),
    'race16': ('CD 10 Suburban Cook 3-24-26.xlsx', 'U.S. Representative, 10th District'),
    'race17': ('ElectionResults-17.xlsx', 'U.S. Representative, 11th District'),
}

# --- Load precinct boundaries ---
with open('Precinct.geojson') as f:
    geojson = json.load(f)

# --- Parse election data ---
def parse_election_df(df):
    candidates = [str(c) for c in df.iloc[0, 3:-1].tolist()]
    results = {}
    for _, row in df.iloc[1:].iterrows():
        name = str(row.iloc[0])
        if name == 'Suburban Cook County':
            continue
        votes = {}
        total = 0
        for i, c in enumerate(candidates):
            v = int(row.iloc[3 + i])
            votes[c] = v
            total += v
        registered = int(row.iloc[1])
        ballots = int(row.iloc[2])
        results[name] = {'votes': votes, 'total': total, 'registered': registered, 'ballots': ballots}
    return candidates, results

# --- Build name mapping: Excel name -> GeoJSON name ---
def excel_to_geojson_name(excel_name):
    excel_name = excel_name.strip()
    ward_match = re.match(r'(.+?)\s+Ward\s+(\d+)\s+Precinct\s+(\d+)', excel_name)
    if ward_match:
        township = ward_match.group(1).upper()
        ward = ward_match.group(2)
        precinct = ward_match.group(3)
        return f"{township} {ward}-{precinct}"
    simple_match = re.match(r'(.+?)\s+Precinct\s+(\d+)', excel_name)
    if simple_match:
        township = simple_match.group(1).upper()
        precinct = simple_match.group(2)
        return f"{township} {precinct}"
    return excel_name.upper()

# --- Spatial join: assign municipality to each precinct ---
print("Loading municipalities for spatial join...")
with open('municipalities.json') as f:
    munis = json.load(f)

from shapely.validation import make_valid
muni_shapes = []
for mf in munis['features']:
    try:
        name = mf['properties'].get('name', '')
        if not name:
            continue  # Skip empty-name polygons (unincorporated areas)
        s = shape(mf['geometry'])
        if not s.is_valid:
            s = make_valid(s)
        muni_shapes.append((name, s.buffer(0)))
    except Exception:
        pass
print(f"  {len(muni_shapes)} municipality polygons")

print("Assigning municipalities to precincts...")
assigned = 0
for feat in geojson['features']:
    geom = shape(feat['geometry'])
    centroid = geom.representative_point()
    feat['properties']['municipality'] = 'Unincorporated'
    for mname, mshape in muni_shapes:
        if mshape.contains(centroid):
            feat['properties']['municipality'] = mname
            assigned += 1
            break
print(f"  Assigned: {assigned}/{len(geojson['features'])} precincts")

# --- Manual municipality overrides (centroid falls outside boundary) ---
MUNI_OVERRIDES = {
    'PROVISO 8': 'Forest Park',
}
for feat in geojson['features']:
    name = feat['properties']['name']
    if name in MUNI_OVERRIDES:
        feat['properties']['municipality'] = MUNI_OVERRIDES[name]
        print(f"  Override: {name} -> {MUNI_OVERRIDES[name]}")

# --- Build GeoJSON name lookup ---
gj_name_map = {}
for i, feat in enumerate(geojson['features']):
    gj_name_map[feat['properties']['name']] = i

# --- Clean up properties and initialize race flags ---
KEEP_PROPS = {'name', 'municipality'}
for feat in geojson['features']:
    props = feat['properties']
    for key in list(props.keys()):
        if key not in KEEP_PROPS:
            del props[key]
    for race_key in RACE_FILES:
        props[f'has_{race_key}'] = False

# --- Process each race ---
all_candidates = {}
all_results = {}

for race_key, (filename, label) in RACE_FILES.items():
    print(f"\nProcessing {race_key}: {label} ({filename})")
    df = pd.read_excel(filename, sheet_name='Precinct', header=None)
    candidates, results = parse_election_df(df)
    all_candidates[race_key] = candidates
    all_results[race_key] = results

    matched = 0
    for excel_name, data in results.items():
        gj_name = excel_to_geojson_name(excel_name)
        if gj_name in gj_name_map:
            idx = gj_name_map[gj_name]
            props = geojson['features'][idx]['properties']
            props[f'has_{race_key}'] = True
            props[f'{race_key}_registered'] = data['registered']
            props[f'{race_key}_ballots'] = data['ballots']
            props[f'{race_key}_total'] = data['total']
            winner = max(data['votes'], key=data['votes'].get)
            props[f'{race_key}_winner'] = winner
            props[f'{race_key}_winner_votes'] = data['votes'][winner]
            props[f'{race_key}_winner_pct'] = round(data['votes'][winner] / data['total'] * 100, 1) if data['total'] > 0 else 0
            for c, v in data['votes'].items():
                props[f'{race_key}_{c}'] = v
            matched += 1
        else:
            pass  # Suppress unmatched output

    print(f"  Matched: {matched}/{len(results)} precincts")
    print(f"  Candidates: {candidates}")

# --- Save enriched geojson ---
with open('election_data.json', 'w') as f:
    json.dump(geojson, f)

# --- Print summary ---
print("\n\n=== SUMMARY ===")
for race_key, (filename, label) in RACE_FILES.items():
    candidates = all_candidates[race_key]
    results = all_results[race_key]

    # Rank candidates by total votes
    totals = {c: 0 for c in candidates}
    for data in results.values():
        for c, v in data['votes'].items():
            totals[c] += v
    ranked = sorted(candidates, key=lambda c: totals[c], reverse=True)

    # Count precinct winners
    winner_counts = {}
    for data in results.values():
        w = max(data['votes'], key=data['votes'].get)
        winner_counts[w] = winner_counts.get(w, 0) + 1

    print(f"\n{race_key} ({label}):")
    print(f"  Candidates ({len(candidates)}):")
    for c in ranked:
        pct = totals[c] / sum(totals.values()) * 100 if sum(totals.values()) > 0 else 0
        wins = winner_counts.get(c, 0)
        print(f"    {c}: {totals[c]:,} votes ({pct:.1f}%), {wins} precincts won")
