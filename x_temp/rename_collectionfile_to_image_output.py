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
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace
import logging
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
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
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
env = sys.argv[1]  # "acc" or "prod"
record_uuids = sys.argv[2] if len(sys.argv) > 2 else f"data/record_uuids_{env}.csv"
assets_csv = sys.argv[3] if len(sys.argv) > 3 else f"data/assets_{env}.csv"
total_list = sys.argv[4] if len(sys.argv) > 4 else f"data/total_List_{env}.csv"

# -----------------------------------
# DECLARATIONS
# -----------------------------------
vocabulair = 'ec65be65-51ec-4272-e053-b784100a2a55'        #### !!!! uuid of vocabulair            
test_amount = 500
max_workers = 8

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

def check_file_exist(folder, file, log, file_type='csv'):

    # Check file type, create file and folder and archive old files with date
    if file_type == 'csv':
        ext = '.csv'
    elif file_type == 'log':
        ext = f'_{str(current_datetime)}.log'
    
    filename = f'{folder}{file}{ext}'
    
    os.makedirs(folder, exist_ok=True)
    
    if file_type == 'csv' and os.path.exists(filename):
        old_file = f'{folder}{file}_{current_datetime}.csv'
        os.rename(filename, old_file)
        log.info(f'Old file archived: {old_file}')
    
    return filename


def setup_logging():
    
    log = logging.getLogger("organizer")
    log.setLevel(logging.DEBUG)   

    logfile = check_file_exist('logs/', 'location_migration_log', log)
    backup_file = check_file_exist('files/', f"backup_{env}", log)
    error_file = check_file_exist('files/', f"error_{env}", log)
    out_file = check_file_exist('files/', f"out_{env}", log)
    asset_file = check_file_exist('files/', f"asset_{env}", log)

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

def process_one_uuid(uuid, log):

    result = {
            'uuid': uuid,
            'errors': [],       # local list, merged into global `errors` afterward
            'backup_rows' : [], 
            'out_rows' : [], 
            'status': 'ok',
        }    

    log.info(f"STARTING WITH UUID: {uuid}")

    g = Graph()

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

#################################### COLUMN CHANGE LOGIC ##############################################################

    ######################## SETUP BACKUP #############################

    backup_df = pd.DataFrame()
    result['backup_rows'].append(backup_df)

    ######################## SETUP BACKUP #############################


    print('in')
    uuid = "uuid"
    identifier = "File.rico:identifier"
    ########################     READ FILES    ########################    
    #df_column = pd.read_csv(data)
    df_column = pd.read_csv(data, 
                            sep=';')
    #df_column = pd.DataFrame(df_column)     
    print(df_column)
    #print(df_column[identifier])
    print(df_column[identifier])
    try:
        df_column[identifier] = df_column[identifier].str.replace(r'^0/0100120*(\d+)$', r'\1', regex=True)
        print(df_column[identifier])
        print(df_column)

        df_column.to_csv(out_file, sep=';', index=False)

#################################### COLUMN CHANGE LOGIC ##############################################################


        for graph_node in data.get('@graph', []):
            if "http://schema.org/name" in graph_node:
                assetname = graph_node['http://schema.org/name']
                asset_df = pd.DataFrame({'uuid' : [uuid], 'assetname' : [assetname]})
                print(asset_df)
                result['asset_rows'].append(asset_df)
            else:
                continue
               
        print(f"klaar!")
        
        log.info(f'Got all asset_uuids and assetnames in {Path(total_list)}')
    
    except Exception as e: 
        log.info(f'FAILED DOING SOMETHING')
        log.error(f'Error while DOING SOMETHING {e}')    

    return result

def main():

    log, error_file, backup_file, out_file = setup_logging()
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')    
    
    record_uuids_df = pd.read_csv(record_uuids, dtype={'uuid': str})
    
    # -----------------------------------
    # THREADPOOL FOR WORKLOAD DIVISION
    # -----------------------------------  
    uuids_to_process = record_uuids_df.head(test_amount)['uuid'].tolist()
    errors = []
    backup = []
    out = []
    
    with ThreadPoolExecutor(max_workers) as executor:
    
        # Dictionary that collects all params to run through the threadpool processor
        futures = {
            # All params that are accumulated as variables in the main process and needs to run through are process for loop
            executor.submit(
                process_one_uuid, uuid, log
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
            backup.extend(result['backup_rows'])
            out.extend(result['out_rows'])
    
    # write CSVs once, after everything is done
    create_csv(errors, error_file)
    if backup:
        backup_df = pd.concat(backup, ignore_index=True)
        backup_df.to_csv(backup_file, mode="w", index=False)
        create_csv(backup_df, backup_file)
    if out:
        out_df = pd.concat(out, ignore_index=True)
        out_df.to_csv(out_file, mode="w", index=False)

if __name__ == '__main__':
    main()