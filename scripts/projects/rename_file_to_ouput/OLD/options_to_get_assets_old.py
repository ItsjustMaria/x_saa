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


'''
Script om links naar afbeeldingen te fabriceren op basis van een csv met daarin de invnrs.
De csv moet ; gescheiden zijn en één kolom bevatten met de naam INVENTARISNUMMER.
De csv moet opgeslagen zijn in de data/temp/ map.
Voorbeeld prompt:

pyhton get_image_uris.py voorbeeld.csv 5075 prod
''' 


df = pd.read_csv(file, delimiter=';', na_filter=False)

fonds_uuid = helper.find_fonds_uuid(toegangsnr)

get_uuid = lambda row: (
    print(f"uuid ophalen voor {toegangsnr} {row['INVENTARISNUMMER']}"), 
    helper.find_file_uuid_with_fonds_uuid(fonds_uuid, str(row['INVENTARISNUMMER']), env=f'{env}'))[1]

df['RESPONSE'] = df.apply(get_uuid, axis=1)

page = 1
per_page = 1000

# maak csv_bestand voor hetvolk
hetvolk = []

for uuid, inventarisnummer in zip(df['RESPONSE'], df['INVENTARISNUMMER']):
    page = 1
    while page > 0:
        response = api.get_assets_for_record(uuid, page, per_page)
        data = json.loads(response.text)
    
        if (page == 1):
            for item in data.get('@graph', []):
                if '@type' in item and 'http://memorix.io/ontology#Pagination' in item['@type'] and 'http://memorix.io/ontology#total' in item:
                    total = int(item['http://memorix.io/ontology#total']['@value'])

            print(f'Er zijn {total} scans')
        
        if total < per_page:
            page = 0
            #break
        else :
            total = total - per_page
            print(f'Meer dan {per_page} resulatten. Nog ophalen {total}')    
            page += 1
        
        for item in data['@graph']:
            if 'http://memorix.io/ontology#digitalDocumentId' in item:
                assetid = item['http://memorix.io/ontology#digitalDocumentId']
                name = item['http://schema.org/name']
                filename = f'{name}'
                url = f'{prefix}/resources/records/media/{uuid}/iiif/3/{assetid}/full/max/0/default.jpg'
                hetvolk.append({'toegangs_nr':toegangsnr, 'inv_nr':inventarisnummer, 'file_uuid':uuid, 'filename': filename, 'asset_id': assetid, 'image_url': url})


df = pd.DataFrame(hetvolk)
file_to_write = saa.file_to_write(file, msg='uris')
df.to_csv(file_to_write)
#print(df)
print(f"All done, zie: {file_to_write}")