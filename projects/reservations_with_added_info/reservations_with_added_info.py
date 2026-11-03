import sys
import json
import os
import csv
import time
import logging
from pathlib import Path
from datetime import time, datetime
from rdflib import Graph, URIRef, Literal, Namespace, RDF

import click
import pandas as pd
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
from modules import wrapper
'''
   Script for retrieving all records and recorddata 

   USAGE:
   python migr_street_to_concept.py --env --data
   
   The following data is needed; 
   * sys.argv[1] adamlink alternative streetnames [HEADER OF FILESHEET NEEDS TO BE ALTERED]
   * On file concept turtle dropped in 'data' directory
   * On file list of uuids dropped in 'data' directory

   Scripts used are: 
   * saa-memorix-nexus/scripts/generic/get_uuids_for_query_to_csv.py
   
   Modules used are:
   * def list_concepts(self, uuid):
   * def get_record(self, uuid, options = {}):
   * def update_record(self, uuid, turtle):

   This script does in order:  
   1) Setup logging and create directories if needed
   2) CONFIRM ENVIRONMENT AND ASK TO PROCEED
   3) Read concept turtle and store needed predicates
   4) Create dataframes from all files
   5) Normalize street from concept and add it to dataframe
   6) Cross reference streets from all dataframes through known street, alt number, alternative writings and fuzzy logic
   7) Build list of alternative names for csv output 
   8) Setup threadpool workload division
   9) Retrieve record from Memorix with a single uuid per iteration divided over max workload number 
   10) Read record turtle and store needed predicates and dismember the migrant street
   11) Normalise street to remove quotations and 1, 2, 3 for First, Second, Third etc.. 
   12) Optional Normalise number addition to change Roman numerals to arabic with a dash added when missing 
   13) Use the created cross reference to find an adamlink
   14) Use the created cross reference to find a concept uuid
   15) Add adamlink location number based on newly found adamlink
   16) Merge dataframes based on adamlink location number
   17) Write weird stuff to an out_csv
   18) Backup original data
   19) Validate concept is not empty or None and fill concept uuid
   20) Validate housenumber is not empty and fill housenumber
   21) Validate housenumber addition is not empty and fill housenumber addition
   22) Optional validation on housenumber addition being normalised and not empty
   23) Upload altered turtle with a single uuid per iteration
   24) Write CSV outputs

   Output files are: 
   * logs/migr_street_to_concept_{current_date}.log
   * files/error_{env}.csv
   * files/errors_{env}.csv
   * files/out_{env}.csv
'''

# -----------------------------------
# SCRIPT VARIABLES
# -----------------------------------
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
project = 'reservations_with_added_info'                            ## PROJECT NAME IS FOLDER NAME FOR ALL DATA. CHANGE NAME IF DESIRED
PREFIX = 'stadsarchief'
env = sys.argv[1]
fund = sys.argv[2]
file = ['D10067005220.tif', 'D10067005221.tif', 'D10067005222.tif'] ## LIST ALL FILES NEEDED FROM SPECIFIED FUND
name = f'{fund}'

# -----------------------------------
# NAMESPACES
# -----------------------------------
SAA = Namespace("https://data.archief.amsterdam/ontology#")
RICO = Namespace("https://www.ica.org/standards/RiC/ontology#")
MEMORIX = Namespace("http://memorix.io/ontology#")
DEED = Namespace(f"{PREFIX}/resources/recordtypes/Deed#")
SCHEMA = Namespace(f"http://schema.org/")
SKOS = Namespace(f"http://www.w3.org/2004/02/skos/core#")
DEED = Namespace (f"{PREFIX}/resources/recordtypes/Deed#")
RT = Namespace(f"{PREFIX}/resources/recordtypes")
IMAGE = Namespace(f"https://{PREFIX}.memorix.io/resources/recordtypes/Image#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

# -----------------------------------
# FILE MANAGEMENT
# -----------------------------------
def check_file_exist(project_name, file, log, file_type='csv'):

    # Check file type, create file and folder and archive old files with date
    sys.path.append(str(HOME_REPO))

    if file_type == 'csv':
        ext = '.csv'
        folder = 'export'
    elif file_type == 'log':
        folder = 'log'
        ext = f'_{str(current_datetime)}.log'
    
    filename = Path(HOME_REPO,'data',project_name, folder,f'{file}{ext}')
    
    os.makedirs(Path(filename.parent), exist_ok=True)
    
    if os.path.exists(filename):
        os.makedirs(Path(HOME_REPO,'data',project_name, folder, 'OLD/'), exist_ok=True)
        old_file = Path(HOME_REPO,'data',project_name, folder, 'OLD/', f'{file}_{current_datetime}{ext}')
        os.rename(filename, old_file)
        log.info(f'Filename {filename} already existed. Archived file with current date timestamp and moved to dir: OLD')
        
    log.info(f'Created the file: {Path(filename)}\n')
    
    return filename

def setup_logging(env, name, project_name):
    
    log = logging.getLogger('organizer')
    log.setLevel(logging.DEBUG)

    logfile = check_file_exist(project_name, f'{name}_{env}_log', log, 'log')
    backup_file = check_file_exist(project_name,f"backup_{name}_{env}", log, 'csv')
    error_file = check_file_exist(project_name,f"error_{name}_{env}", log, 'csv')
    source_file = check_file_exist(project_name,f"original_{name}_{env}", log, 'csv')

    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(fh)
    log.addHandler(ch)

    return log, error_file, backup_file, source_file

# -----------------------------------
# ENVIRONMENT SETUP
# -----------------------------------
def get_settings_file(env):
    if env == "acc":
        return "settings.temp.json"
    if env == "prod":
        return "settings.prod.json"
    raise ValueError("env must be 'acc' or 'prod'")


def get_api(env):
    if env == 'acc':
        PREFIX = 'https://ams-migrate.memorix.io'
        settings_file = Path(WORK_REPO, 'settings.json') 
    elif env == 'prod':
        PREFIX = 'https://stadsarchiefamsterdam.memorix.io'
        settings_file = Path(WORK_REPO, 'settings.prod.json') 
    elif env == 'tst':
        settings_file = print(f'test output')
    else:
        raise ValueError("Environment must be 'acc' or 'prod'")

    settings = saa.readJsonFile(settings_file) 
    #api = memorix.ApiClient(settings)
    return memorix.ApiClient(settings)


def get_helper(env):
    api = get_api(env)
    helper = wrapper.ApiBuildingBlocks(api)
    return api, helper

# -----------------------------------
# SCRIPT UNCTIONS
# -----------------------------------
def files_per_fonds(toegangsnummer, env, output_file):
    # Haalt alle bestanddelen op voor een fonds
    api, helper = get_helper(env)

    if output_file is None:
        output_file = f"{toegangsnummer}_lijst.csv"

    fonds_uuid = helper.find_fonds_uuid(toegangsnummer)
    print(f"Fonds uuid = {fonds_uuid}")

    all_rows = []

    # Eerste pagina ophalen
    response = api.search_files_per_fonds(fonds_uuid=fonds_uuid, limit=10000)
    data = json.loads(response.text)

    while True:
        rows = data.get("rows", [])
        all_rows.extend(rows)
        print(f"{len(rows)} records opgehaald, totaal nu: {len(all_rows)}")

        next_token = data.get("pagination", {}).get("next")
        if not next_token:
            break

        response = api.search_files_per_fonds(
            fonds_uuid=fonds_uuid,
            next=next_token
        )
        data = json.loads(response.text)

    print(f"Totaal aantal gevonden bestanddelen: {len(all_rows)}")

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["uuid", "invnr", "title", "description"]
        writer = csv.DictWriter(
            csvfile,
            fieldnames=fieldnames,
            delimiter=";",
            quotechar='"',
            quoting=csv.QUOTE_NONNUMERIC,
        )
        writer.writeheader()

        for row in all_rows:
            writer.writerow(
                {
                    "uuid": row["recordId"],
                    "invnr": row["meta"]["identifier"],
                    "title": row["title"],
                    "description": row["description"],
                }
            )

    print(f"Bestand klaar: {output_file}")
    return output_file


def get_filename(uuid, asset_file, log):
    # Haalt alle bestanddelen op voor een fonds
    api, helper = get_helper(env)
    

    log.info(f"STARTING WITH UUID: {uuid}")

    try:
        response = api.get_assets_for_record(uuid)
        if response.status_code != 200:
            time.sleep(3)
            response = api.get_assets_for_record(uuid)
                        
            if response.status_code != 200:
                log.error({'errortext': 'failed for uuid', 'uuid': uuid, 'error': response.text})

        data = json.loads(response.content.decode('utf-8'))
        assetname = ""  # initialized before the inner loop
        asset_df = pd.DataFrame({'uuid' : [uuid]})
        asset_df['assetname'] = ''

        for graph_node in data.get('@graph', []):
            if "http://schema.org/name" in graph_node:
                
                assetname = graph_node['http://schema.org/name']
                asset_df['assetname'] = assetname
                
            else:
                continue
        result['asset_rows'].append(asset_df)       
        print(f"Done!")
        
        log.info(f'Got all asset_uuids and assetnames in {Path(asset_file)}')
    
    except Exception as e: 
        log.info(f'FAILED DOING SOMETHING')
        log.error(f'Error while DOING SOMETHING {e}')    

    return result


def main():

    log, error_file, backup_file, out_file = setup_logging(env, name, project)
    g = Graph()
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ANALYZE DATA NOW?\": (Y/N)')

    try: 
        out_file = files_per_fonds(fund, env, out_file)
        log.info(f'Retrieved files and data for fund: {fund}.')

    except Exception as e:
        log.info(f'Failure in the script with error: {e}', exc_info=True) 
        log.error(f'Error in the script of t {type(e).__name__, e}') 
        template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
        message = template.format(type(e).__name__, e.args)
        log.error(message)

    try: 
        out_file = files_per_fonds(fund, env, out_file)
        log.info(f'Retrieved files and data for fund: {fund}.')

    except Exception as e:
        log.info(f'Failure in the script with error: {e}', exc_info=True) 
        log.error(f'Error in the script of t {type(e).__name__, e}') 
        template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
        message = template.format(type(e).__name__, e.args)
        log.error(message)

if __name__ == '__main__':
    main()
