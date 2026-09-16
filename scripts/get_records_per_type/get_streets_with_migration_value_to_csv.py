import sys
import json
import csv
from copy import deepcopy

sys.path.append('../../')
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
env = sys.argv[1]  # "acc" or "prod"
out_csv = sys.argv[2] if len(sys.argv) > 2 else f"../data/streets_new_script_test.csv"

# ---------------------------
# Environment
# ---------------------------
if env == "acc":
    settings_file = "../../settings.json"
    prefix = "https://ams-migrate.memorix.io"
elif env == "prod":
    settings_file = "../../settings.prod.json"
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
                                "field": "Deed.saa:isAssociatedWithModernAddress.saa:streetTextualValue",
                                "value": "null"
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
# IMPORTANT: choose the correct API call for "search by query"
# ---------------------------
def search_by_query(next_token=None):
    """
    You may need to adjust this method name to your memorix client.
    Common patterns are:
      - api.search_records(payload, next=...)
      - api.search(payload, next=...)
      - api.search_records(payload, params={'next': ...})
    """
    # ✅ If your client has this:
    # return api.search_records(query_payload, next=next_token)

    # ✅ Or if your client has this:
    # return api.search(query_payload, next=next_token)

    # Fallback: raise a clear error so you know what to change.
    raise AttributeError(
        "No search method configured. Edit search_by_query() to call the correct ApiClient method "
        "for searching by query payload (e.g. api.search_records(...) or api.search(...))."
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
print(f"Fetched: {len(uuids)} / {total}")

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

    total = data.get("pagination", {}).get("total", total)
    print(f"Fetched: {len(uuids)} / {total} / {next_token}")

# ---------------------------
# Write UUIDs to CSV
# ---------------------------
with open(out_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["uuid"])
    for u in uuids:
        writer.writerow([u])

print(f"Done. Wrote {len(uuids)} UUIDs to {out_csv}")