import sys
import json
import csv
import os
from datetime import datetime
from pathlib import Path
import pandas as pd
import shutil
import requests
# WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa

 
'''
Script om afbeeldingen op te halen uit Memorix op basis van een csv lijst met invnrs
'''

# ---------------------------
# CLI args
# ---------------------------
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
env = sys.argv[1]  # "acc" or "prod"
# Ensure the output folder exists
'''data_folder = r'data/' 
os.makedirs(data_folder, exist_ok=True)
filename = os.path.join(assets_csv)'''

if not os.path.exists("./data"):     
        os.makedirs("./data")
        print(f'Data directory did not exist. Data directory created') 
env = sys.argv[1]
file = sys.argv[2] if len(sys.argv) > 2 else f"data/record_uuids_{env}.csv"
assets_csv = sys.argv[3] if len(sys.argv) > 3 else f"data/assets_{env}.csv"
total_list = sys.argv[4] if len(sys.argv) > 4 else f"data/total_List_{env}.csv"
test_amount = 50

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

settings = saa.readJsonFile(f'{settings_file}')
api = memorix.ApiClient(settings)

# Assuming 'file' is defined and points to the CSV file
df = pd.read_csv(file, dtype={'uuid': str})

with open(assets_csv, 'w', encoding='utf-8', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(["uuid", "filename"])

    for index, row in df.head(test_amount).iterrows():
        uuid = row['uuid']
        
        response = api.get_assets_for_record(uuid)
        data = json.loads(response.text)
        filename = None  # initialized before the inner loop
        print(response.text,  file=open(total_list, 'a', encoding='utf-8'))
        for graph_node in data['@graph']:
            if 'http://schema.org/name' in graph_node:
                filename = graph_node['http://schema.org/name']
                break  # found it — no need to keep iterating

        writer.writerow([uuid, filename or ''])

print(f"klaar!")


# optie get_all_assets_for_search
# get asset details     
# download asset hierna??? 