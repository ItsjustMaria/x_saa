# ---------------------------
# IMPORT LIBRARIES
# ---------------------------
import os 
import sys
import csv
import simplejson as json
from datetime import time, datetime
from tqdm import tqdm
import pandas as pd
import re
import logging
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
from modules import wrapper
PREFIX = 'stadsarchief'


'''
   Script for removing linked assets from groups through the memorix api. 
   All data is output to a csv.
   
   The following data is needed; 
   * CSV file of record uuid's 

   Scripts used are: 
   * 
   
   Modules used are:
   * api.get_assets_for_record(uuid)
   * api.unlink_asset_from_record(self, UUID, asset_id)

   This script does in order:  
   1) Setup logging and create directories if needed
   2) CONFIRM ENVIRONMENT AND ASK TO PROCEED
   3) Create dataframes from record uuid's
   4) Setup threadpool workload division
   5) Retrieve record from Memorix with a single uuid per iteration divided over max workload number 
   6) Read record and find asset with assetname
   7) Write CSV outputs

   Output files are: 
   * logs/location_migration{current_date}.log
   * files/errors_{env}.csv
   * files/assets_{env}.csv

'''

# ---------------------------
# CLI ARGS
# ---------------------------
env = sys.argv[1]  # "acc" or "prod"

# -----------------------------------
# DECLARATIONS
# -----------------------------------
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
project_name = 'unlink_assets'          #### !!!! State project name for data collection in file, logs and data folder     
name = 'unlink_assets'
record_uuids = Path(HOME_REPO,'data',project_name, 'source', f'record_uuids_{env}.csv')              #### !!!! Location of uuid from memorix       
test_amount = 1
max_workers = 1

# -----------------------------------
# FILE MANAGEMENT
# -----------------------------------
def check_file_exist(project_name, file, log, file_type='csv'):

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
             
    return filename


def setup_logging(env, name, project_name):
    
    log = logging.getLogger('organizer')
    log.setLevel(logging.DEBUG)

    logfile = check_file_exist(project_name, f'{name}_{env}_log', log, 'log')
    backup_file = check_file_exist(project_name,f"backup_{name}_{env}", log, 'csv')
    asset_file = check_file_exist(project_name,f"assets_{name}_{env}", log, 'csv')
    output_file = check_file_exist(project_name,f"output_{name}_{env}", log, 'csv')

    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(fh)
    log.addHandler(ch)

    return log, backup_file, asset_file, output_file


def create_csv(my_list, file):

    # Outliers to dataframe 
    #csv_df = pd.DataFrame(my_list)

    my_list.to_csv(
        file,
        mode="w",
        sep=';',
        index=False
    )

    return file

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

    return memorix.ApiClient(settings)


def get_helper(env):
    api = get_api(env)
    helper = wrapper.ApiBuildingBlocks(api)
    return api, helper

# -----------------------------------
# FUNCTIONS
# -----------------------------------
def get_assets(uuid, asset_df, api, log):

    assets = []
    #uuid = row['uuid']
    log.info(f"STARTING WITH UUID: {uuid}")

    
    response = api.get_assets_for_record(uuid)
    if response.status_code != 200:
        time.sleep(3)
        response = api.get_record(uuid)
                    
        if response.status_code != 200:
            log.error(f"Failed getting assets for uuid: {uuid}")
            log.error({'errortext': 'failed for uuid', 'uuid': uuid, 'error': response.text})


    data = json.loads(response.content.decode('utf-8'))
    #assetname = ""  # initialized before the inner loop
    #asset_df = pd.DataFrame({'uuid' : [uuid]})
    #asset_df['assetname'] = ''

    for graph_node in data.get('@graph', []):
        if "http://schema.org/name" in graph_node:
            print('I get in the node')
            assetname = graph_node['http://schema.org/name']
            #asset_df['assetname'] = assetname
            assets.append(assetname)
            return assetname # asset_df['assetname']
                
        else:
            continue
        #assets.append(asset_df)         


def find_asset_id(api, input_file, output_file, max_retries, ambiguous_output_file=None):
    
    if not Path(input_file).is_file():
            raise FileNotFoundError(f"File not found: {input_file}")
    
    df = pd.read_csv(input_file, delimiter=";", na_filter=False, dtype=str)

    if "filename" not in df.columns:
        raise ValueError("Input CSV must contain a 'filename' column.")

    results = []
    ambiguous_records = []

    for _, row in df.iterrows():
        filename = str(row["filename"]).strip()

        record_id = ""
        if "record_id" in df.columns:
            record_id = row["record_id"]
        elif "uuid" in df.columns:
            record_id = row["uuid"]

        print(f"Searching DAM for filename: {filename}")

        found = False

        for attempt in range(max_retries):
            try:
                response = api.search_dam(filename)

                if response.status_code != 200:
                    print(
                        f"API error while searching for '{filename}' "
                        f"(Attempt {attempt + 1}/{max_retries}): {response.text}"
                    )
                    time.sleep(1)
                    continue

                data = json.loads(response.text)
                entries = data.get("entries", [])

                if not entries:
                    print(f"No assets found for filename '{filename}'")

                    results.append(
                        {
                            "record_id": record_id,
                            "filename": filename,
                            "asset_id": "",
                        }
                    )

                    found = True
                    break

                exact_matches = [
                    asset
                    for asset in entries
                    if os.path.basename(asset.get("path", "")).strip() == filename
                ]

                match_count = len(exact_matches)

                if match_count == 0:
                    print(
                        f"No exact filename match found for '{filename}' "
                        f"among {len(entries)} DAM entries"
                    )

                    results.append(
                        {
                            "record_id": record_id,
                            "filename": filename,
                            "asset_id": "",
                        }
                    )

                    found = True
                    break

                if match_count == 1:
                    asset = exact_matches[0]
                    asset_id = str(asset.get("uid", ""))

                    print(f"Single exact match found for '{filename}': Asset ID = {asset_id}")

                    results.append(
                        {
                            "record_id": record_id,
                            "filename": filename,
                            "asset_id": asset_id,
                        }
                    )

                    found = True
                    break

                print(f"Multiple exact matches found for '{filename}': {match_count}")

                ambiguous_record = {
                    "record_id": record_id,
                    "filename": filename,
                    "match_count": match_count,
                    "matched_uids": ";".join(str(a.get("uid", "")) for a in exact_matches),
                    "matched_paths": ";".join(a.get("path", "") for a in exact_matches),
                }
                ambiguous_records.append(ambiguous_record)

                for asset in exact_matches:
                    print(
                        f" - UID: {asset.get('uid')}, "
                        f"path: {asset.get('path', '')}"
                    )

                # Keep main output safe for possible linking:
                # ambiguous rows get an empty asset_id
                results.append(
                    {
                        "record_id": record_id,
                        "filename": filename,
                        "asset_id": "",
                    }
                )

                found = True
                break

            except Exception as e:
                print(
                    f"Error while searching for '{filename}' "
                    f"(Attempt {attempt + 1}/{max_retries}): {e}"
                )
                time.sleep(1)

        if not found:
            print(f"Failed to retrieve asset for '{filename}' after {max_retries} attempts.")

            results.append(
                {
                    "record_id": record_id,
                    "filename": filename,
                    "asset_id": "",
                }
            )

        output_df = pd.DataFrame(results)

        column_order = ["record_id", "filename", "asset_id"]
        output_df = output_df[column_order]
    
        output_df.to_csv(output_file, index=False, sep=";", quoting=csv.QUOTE_ALL)
        print(f"Output written to {output_file}")
    
        if ambiguous_output_file is None:
            output_path = Path(output_file)
            ambiguous_output_file = str(
                output_path.with_name(f"{output_path.stem}_ambiguous{output_path.suffix}")
            )
    
        create_csv(ambiguous_records, ambiguous_output_file)
    
        return output_df

def unlink_assets(api, row, log):

    api.unlink_asset_from_record(row['uuid'], row['asset_id'])
    log.info(f'uuid {row['uuid']} unlinked from asset_id: {row['asset_id']}')

    return 

    
def main():

    log, backup_file, asset_file, output_file = setup_logging(env, name, project_name)
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')    
    asset_df = pd.read_csv(record_uuids, dtype={'uuid': str})
    api, helper = get_helper(env) 
    assets = []    

    try:
        uuid = asset_df['uuid']
        #assets_df = df['uuid'].apply(lambda x: get_assets(api, uuid, asset_file, assets, log))
        asset_df['assetname'] = asset_df['uuid'].apply(lambda x: get_assets(x, asset_df, api, log))
        #for idx, row in asset_df.iterrows():
        #    assets = get_assets(api, uuid, asset_file, assets, log)
        log.info(f'Got all asset_uuids and assetnames in {Path(asset_file)}')
    except Exception as e:
        log.info(f'FAILED while getting assets with  error : {e}', exc_info=True) 
        log.error(f'Error while getting assets {type(e).__name__, e}') 
        template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
        message = template.format(type(e).__name__, e.args)
        log.error(message)
    
    try: 

        asset_file = create_csv(asset_df, asset_file)
        log.info(f'backup created at : {Path(asset_file)}')
    except Exception as e:
            log.info(f'FAILED getting turtle data with  error : {e}', exc_info=True) 
            log.error(f'Error while getting turtle data {type(e).__name__, e}') 
            template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
            message = template.format(type(e).__name__, e.args)
            log.error(message)
    
    try:
        output_df = find_asset_id(api, asset_file, output_file, 3)
        log.info('asset_ids added to dataframe')
        print(asset_df)       
    except Exception as e:
            log.info(f'FAILED getting turtle data with  error : {e}', exc_info=True) 
            log.error(f'Error while getting turtle data {type(e).__name__, e}') 
            template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
            message = template.format(type(e).__name__, e.args)
            log.error(message)
    print(output_df)
    #try:
    #    for _, row in asset_df.iterrows():
    #        api.unlink_asset_from_record(row['uuid'], row['asset_id'])
    #        log.info(f'uuid {row['uuid']} unlinked from asset_id: {row['asset_id']}')           
    #except Exception as e:
    #        log.info(f'FAILED getting turtle data with  error : {e}', exc_info=True) 
    #        log.error(f'Error while getting turtle data {type(e).__name__, e}') 
    #        template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
    #        message = template.format(type(e).__name__, e.args)
    #        log.error(message)

if __name__ == '__main__':
    main()