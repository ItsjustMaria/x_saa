import sys
import os
import json
import csv
import time
from copy import deepcopy
from pathlib import Path
from datetime import datetime
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa

"""
Script dat op basis van een (Memorix) search query alle record UUIDs ophaalt en naar een CSV schrijft.
Werkt ook voor >10.000 resultaten (via pagination.next).

Usage:
  python get_uuids_for_query_to_csv.py prod
  python get_uuids_for_query_to_csv.py acc
  python get_uuids_for_query_to_csv.py prod output.csv
"""

# ---------------------------
# CLI args
# ---------------------------
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
env = sys.argv[1]  # "acc" or "prod"
project_name = 'location_migration'         
record_uuids = sys.argv[2] if len(sys.argv) > 2 else Path(HOME_REPO,'data' ,project_name, 'source', f'record_uuids_{env}.csv')             #### !!!! Location of uuid from memorix

if os.path.exists(record_uuids):
        os.makedirs(Path(HOME_REPO,'data',project_name, 'source', 'OLD/'), exist_ok=True)
        old_file = Path(HOME_REPO,'data',project_name, 'source', 'OLD/', f'record_uuids_{current_datetime}.csv')
        os.rename(record_uuids, old_file)
        print(f'Filename {record_uuids} already existed. Archived file with current date timestamp and moved to dir: OLD')


# ---------------------------
# Environment
# ---------------------------
if env == "acc":
    settings_file = Path(WORK_REPO, 'settings.json') 
    prefix = "https://ams-migrate.memorix.io"
elif env == "prod":
    settings_file = Path(WORK_REPO, 'settings.prod.json') 
    prefix = "https://stadsarchiefamsterdam.memorix.io"
else:
    print("Invalid env. Use 'acc' or 'prod'.")
    sys.exit(1)

settings = saa.readJsonFile(settings_file)
api = memorix.ApiClient(settings)

# ---------------------------
# Query (default = the one you provided)
# NOTE: we rewrite domain prefixes in values so it works in acc/prod.
# ---------------------------
QUERY = {
    "query": {
        "queries": [
            {
                "queries": [
                    {
                        "queries": [
                            {
                                "type": "FieldQuery",
                                "operator": "notEmpty",
                                "field": "Deed.saa:addressDescription",
                                "value": ""
                            }
                        ],
                        "type": "AndQuery"
                    },
                    {
                        "queries": [
                            {
                                "type": "FieldQuery",
                                "operator": "equals",
                                "field": "recordType.id",
                                "value": "Deed"
                            }
                        ],
                        "type": "OrQuery"
                    }
                ],
                "type": "AndQuery"
            }
        ],
        "type": "AndQuery"
    },
    "facets": [
        {
            "name": "collection.id",
            "field": "collection.id",
            "minCount": 0,
            "size": 1000,
            "order": {
                "value": "asc"
            }
        },
        {
            "name": "recordType.id",
            "field": "recordType.id",
            "minCount": 0,
            "size": 1000,
            "order": {
                "value": "asc"
            }
        }
    ]
}
def fmt_seconds(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

start_time = time.monotonic()

def rewrite_prefixes(obj, from_prefix: str, to_prefix: str):
    """Recursively replace URL prefix in all string values inside a dict/list structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = rewrite_prefixes(v, from_prefix, to_prefix)
        return obj
    if isinstance(obj, list):
        return [rewrite_prefixes(v, from_prefix, to_prefix) for v in obj]
    if isinstance(obj, str):
        return obj.replace(from_prefix, to_prefix)
    return obj

# If env != prod, adjust the hardcoded prod URLs in query values
query_payload = deepcopy(QUERY)
query_payload = rewrite_prefixes(
    query_payload,
    from_prefix="https://stadsarchiefamsterdam.memorix.io",
    to_prefix=prefix,
)

# ---------------------------
# Fetch all UUIDs with pagination
# ---------------------------
uuids = []
seen = set()

# First request
response = api.perform_search(payload=json.dumps(query_payload))
if response.status_code != 200:
    print("API error: " + response.text)
    sys.exit(1)

data = json.loads(response.text)

for row in data.get("rows", []):
    rid = row.get("recordId")
    if rid and rid not in seen:
        seen.add(rid)
        uuids.append(rid)

total = data.get("pagination", {}).get("total", len(uuids))
print(
        f"[elapsed 00:00 | ETA --:--] "
        f"Fetched: {len(uuids)} / {total}"
    )

# Continue while there's a next token
while data.get("pagination", {}).get("next"):
    next_token = data["pagination"]["next"]
    response = api.perform_search(payload=json.dumps(query_payload), next=next_token)
    if response.status_code != 200:
        print("API error: " + response.text)
        break

    data = json.loads(response.text)

    for row in data.get("rows", []):
        rid = row.get("recordId")
        if rid and rid not in seen:
            seen.add(rid)
            uuids.append(rid)

    fetched = len(uuids)
    elapsed = time.monotonic() - start_time

    rate = fetched / elapsed
    remaining = total - fetched
    eta_seconds = remaining / rate if rate > 0 else 0

    print(
        f"[elapsed {fmt_seconds(elapsed)} | ETA {fmt_seconds(eta_seconds)}] "
        f"Fetched: {fetched} / {total}"
    )

# ---------------------------
# Write UUIDs to CSV
# ---------------------------
with open(record_uuids, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["uuid"])
    for u in uuids:
        writer.writerow([u])

print(f"Done. Wrote {len(uuids)} UUIDs to {record_uuids}")