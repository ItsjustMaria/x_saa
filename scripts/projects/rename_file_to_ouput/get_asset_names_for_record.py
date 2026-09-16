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
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
from modules import wrapper
PREFIX = 'stadsarchief'


'''
   Empty script shell for graph alterations and updating functionality
    including logging, file documentation and such
   
   The following data is needed; 
   * CSV file of record uuid's 

   Scripts used are: 
   * saa-memorix-nexus/scripts/generic/get_uuids_for_query_to_csv.py
   
   Modules used are:
   * api.get_assets_for_record(uuid)

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
vocabulair = 'ec65be65-51ec-4272-e053-b784100a2a55'        #### !!!! uuid of vocabulair  
project_name = 'rename_file_to_image_output'          #### !!!! State project name for data collection in file, logs and data folder     
record_uuids = Path(HOME_REPO,'data',project_name, 'source', f'record_uuids_{env}.csv')              #### !!!! Location of uuid from memorix       
test_amount = 18000
max_workers = 1

# -----------------------------------
# FILE MANAGEMENT
# -----------------------------------
def check_file_exist(file, log, file_type='csv'):

    # Check file type, create file and folder and archive old files with date
    sys.path.append(str(HOME_REPO))

    if file_type == 'csv':
        ext = '.csv'
        folder = 'export'
    elif file_type == 'log':
        folder = 'log'
        ext = f'_{str(current_datetime)}.log'
    
    filename = Path(HOME_REPO,'data',project_name, folder,f'{file}.{ext}')
    
    os.makedirs(Path(filename.parent), exist_ok=True)
    
    if os.path.exists(filename):
        os.makedirs(Path(HOME_REPO,'data',project_name, folder, 'OLD/'), exist_ok=True)
        old_file = Path(HOME_REPO,'data',project_name, folder, 'OLD/', f'{file}_{current_datetime}{ext}')
        os.rename(filename, old_file)
        log.info(f'Filename {filename} already existed. Archived file with current date timestamp and moved to dir: OLD')
        
    log.info(f'Created the file: {Path(filename)}\n')
    
    return filename

def setup_logging():
    
    log = logging.getLogger("organizer")
    log.setLevel(logging.DEBUG)   

    logfile = check_file_exist('migr_str_to_cnpt_log', log, 'log')
    backup_file = check_file_exist(f"backup_{env}", log, 'csv')
    error_file = check_file_exist(f"error_{env}", log, 'csv')
    out_file = check_file_exist(f"out_{env}", log, 'csv')
    
    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(fh)
    log.addHandler(ch)

    return log, error_file, backup_file, out_file

def create_csv(my_list, file):

    # Outliers to dataframe 
    csv_df = pd.DataFrame(my_list, index=range(len(my_list)))

    csv_df.to_csv(
        file,
        mode="w",
        index=False
    )

    return csv_df

# -----------------------------------
# ENVIRONMENT SETUP
# -----------------------------------
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
api = memorix.ApiClient(settings)
helper = wrapper.ApiBuildingBlocks(api)

# -----------------------------------
# FUNCTIONS
# -----------------------------------
def process_one_uuid(uuid, asset_file, log):

    result = {
            'uuid': uuid,
            'errors': [],       # local list, merged into global `errors` afterward
            'asset_rows' : [], 
            'status': 'ok',
        }    

    log.info(f"STARTING WITH UUID: {uuid}")

    try:
        response = api.get_assets_for_record(uuid)
        if response.status_code != 200:
            time.sleep(3)
            response = api.get_record(uuid)
                        
            if response.status_code != 200:
                log.error(f"Failed getting assets for uuid: {uuid}")
                result['errors'].append({'errortext': 'failed for uuid', 'uuid': uuid, 'error': response.text})
                result['status'] = 'failed'
                return result

        data = json.loads(response.content.decode('utf-8'))
        assetname = ""  # initialized before the inner loop
        asset_df = pd.DataFrame({'uuid' : [uuid]})
        asset_df['assetname'] = ''

        for graph_node in data.get('@graph', []):
            if "http://schema.org/name" in graph_node:
                print('I get in the node')
                assetname = graph_node['http://schema.org/name']
                asset_df['assetname'] = assetname
                print(asset_df)
                
            else:
                continue
        result['asset_rows'].append(asset_df)       
        print(f"klaar!")
        
        log.info(f'Got all asset_uuids and assetnames in {Path(asset_file)}')
    
    except Exception as e: 
        log.info(f'FAILED DOING SOMETHING')
        log.error(f'Error while DOING SOMETHING {e}')    

    return result

def main():

    log, error_file, asset_file = setup_logging(project_name)
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')    
    
    record_uuids_df = pd.read_csv(record_uuids, dtype={'uuid': str, 'assetname' : str})
    
    # -----------------------------------
    # THREADPOOL FOR WORKLOAD DIVISION
    # -----------------------------------  
    uuids_to_process = record_uuids_df.head(test_amount)['uuid'].tolist()
    errors = []
    asset = []
    
    with ThreadPoolExecutor(max_workers) as executor:
    
        # Dictionary that collects all params to run through the threadpool processor
        futures = {
            # All params that are accumulated as variables in the main process and needs to run through are process for loop
            executor.submit(
                process_one_uuid, uuid, asset_file, log
            ): uuid
            # Execution of the former for loop on the df with the new variable for loop
            for uuid in uuids_to_process
        }
    
        # All executed runs are collected in a tqdm list with the total length of the executed uuid loops [e.g. based on your test_amount then]
        for future in tqdm(as_completed(futures), total=len(futures)):
    
            #Setting the uuid as the identifier for each ran process in the accumulated list
            uuid = futures[future]
            try:
                # Apply a [builtin ? ] method to identify the information accumulated in the result dictionary
                result = future.result()
            except Exception as e:
                # this only fires if process_one_uuid itself crashed unexpectedly
                log.error(f"Unhandled exception for uuid {uuid}: {e}")
                errors.append({'errortext': 'Unhandled exception', 'uuid': uuid, 'error': str(e)})
                continue
    
            # merge the identified uuid's result into the shared lists 
            # this code only ever runs in the main thread, one future at a time
            errors.extend(result['errors'])
            asset.extend(result['asset_rows'])
    
    # write CSVs once, after everything is done

    create_csv(errors, error_file)
    if asset:
        asset_df = pd.concat(asset, ignore_index=True)
        asset_df.to_csv(asset_file, mode="w", index=False)
        create_csv(asset_df, asset_file)


if __name__ == '__main__':
    main()