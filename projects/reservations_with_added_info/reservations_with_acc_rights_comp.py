import os, sys
import time
import logging
import argparse
import json
from pathlib import Path
from datetime import time, datetime, date
import time
from rdflib import Graph, URIRef, Namespace, RDF
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location


'''
   Requested script for recurrent usage.
   This script retrieves additional accessibility rights applicable to documents
   that have been requested to be reserved for public viewing. 

   USAGE:
   The CLI asks for args parse definition of the environment with --env preceeded by prod or acc or prod 
   The dates refer to the desired period of reservations. Here too the CLI arguments need to be specified
   with --start and --end, followed by a date in format yyyy-mm-dd or yyyymmdd.

   Ex: python reservations_with_acc_components.py --env acc/prod --start 2025-01-01 --end 2025-12-31
   
   The following data is needed 
   * 

   Scripts used are: 
   * 
   
   Modules used are:
   * api.list_reservations(self, begin_date, end_date, page, per_page)
   * api.get_record(uuid)
   * api.get_ar_for_record(self, uuid)

   This script does in order:  
   1) Setup logging and create directories if needed
   2) Confirm environment
   3) Get reservations from api based on start and end date and create a dataframe
   4) Get accessibility components with help of record id listed in reservations response
   5) Create dataframes, apply boolean logic to answers and log missing uuids
   6) Merge reservation information with accessibility rights 
   7) Write CSV output

   Output files are: 
   * logs/{project_name}_{current_date}.log
   * export/errors_{env}.csv
   * export/output_{env}.csv

   User specific [- OPTIONAL -] variables 
   Optional variables can be altered directly below. 
   Optional alterations include
   * Project name -> This will be the name of the folder where the logs and csv file will be stored 
   * Name -> Name of the csv data output file. Default is same as project name
   * HOME_REPO -> Local folder path to store data folder. Default is /saa-nexus-scripts/data 
   * WORK_REPO -> Folder /saa-nexus-scripts where scripts are run from 
'''

# -----------------------------------
# USER OPTIONAL VARIABLES
# -----------------------------------
project_name = 'reservations_with_acc_components'          ## NAME FOR THE FOLDER STORING THE OUTPUT
name = 'reservations_with_acc_components'                  ## NAME OF THE FILE CREATED FOR STORING OUTPUT
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")    ## LOCAL DRIVE WHERE SAA NEXUS FOLDER LIVES
HOME_REPO = Path("/opt/lampp/htdocs")                                             ## LOCAL DRIVE WHERE DATA FOLDER DESIRED TO BE STORED                                                              
# HOME_REPO = Path(HOME_PATH) if HOME_PATH != "" else WORK_REPO 
                    
# -----------------------------------
# SCRIPT VARIABLES
# -----------------------------------
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
from modules import wrapper
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
errors = []
not_found_idx = []
test_amount = 1000000    
max_workers = 8 

# -----------------------------------
# NAMESPACES
# -----------------------------------
MEMORIX = Namespace("http://memorix.io/ontology#")
SCHEMA = Namespace(f"http://schema.org/")
API_PREFIXES = {'acc': 'https://ams-migrate.memorix.io', 'prod': 'https://stadsarchiefamsterdam.memorix.io'}

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
    output_file = check_file_exist(project_name,f"output_{name}_{env}", log, 'csv')
    error_file = check_file_exist(project_name,f"errors_{name}_{env}", log, 'csv')
    checkpoint_file = check_file_exist(project_name,f"checkpoints_{name}_{env}", log, 'csv')

    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(fh)
    log.addHandler(ch)

    return log, output_file, error_file, checkpoint_file


def create_csv(my_list, file, columns=None):

    # Outliers to dataframe 
    csv_df = pd.DataFrame(my_list, columns=columns) if columns and not my_list else pd.DataFrame(my_list)
    csv_df.to_csv(file, mode='w', sep=';', index=False)
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
        PREFIX = API_PREFIXES[env]
        settings_file = Path(WORK_REPO, 'settings.json') 
    elif env == 'prod':
        PREFIX = API_PREFIXES[env]
        settings_file = Path(WORK_REPO, 'settings.prod.json') 
    else:
        raise ValueError("Environment must be 'acc' or 'prod'")

    settings = saa.readJsonFile(settings_file) 

    return memorix.ApiClient(settings)


def get_helper(env):
    api = get_api(env)
    helper = wrapper.ApiBuildingBlocks(api)
    return api, helper

def get_with_retry(api, uuid, log, attempts=4):
    for attempt in range(attempts):
        response = api.get_record(uuid)
        if response.status_code == 200:
            return response
        if response.status_code == 404:      
            return response
        wait = 2 ** attempt                  
        log.warning(f'{uuid}: status {response.status_code}, retry in {wait}s')
        time.sleep(wait)
    return response

# -----------------------------------
# SCRIPT FUNCTIONS
# -----------------------------------
def merge_dataframes(df, rights_df):

    merged = df.merge(rights_df[['record.id', 'Digitaliseren', 
            'Openbaarheidsbeperking', 'Opmerkingen', 'Downloaden', 
            'Reserveren', 'Fysiek aanwezig']], on = 'record.id', how='left')
    
    return merged

def add_server_status(df, failed):
    df = df.copy()
    df['server_status'] = ''
    df.loc[df['record.id'].isin(failed), 'server_status'] = 'uuid not on server'
    return df

def create_df(rights):

    rights_df = pd.DataFrame(rights)  
    rights_df = rights_df.fillna('')
    rights_df = rights_df.replace('None', '')   

    for col in ['Openbaarheidsbeperking', 'Opmerkingen']:
        if col in rights_df:
            rights_df[col] = rights_df[col].ne('')   # True = has a value
    
    return rights_df


def check_rights(uuid, record, api, env):
   
    if record == None or record == 'None' or record == "":
        return None
    else:
        resp = api.get_ar_for_record(uuid)
        gr = Graph()
        turtle = gr.parse(data= resp.text, format='turtle') 
    
        record = URIRef(f"{API_PREFIXES[env]}/resources/records/{uuid}/accessibility_and_rights")

        acc_rights = {
            'record.id': uuid,
            'Digitaliseren' : str(gr.value(record, MEMORIX.accessModeScanningOnDemand)),
            'Openbaarheidsbeperking': str(gr.value(record, MEMORIX.restrictionsExpire)),
            'Opmerkingen' : str(gr.value(record, SCHEMA.copyrightNotice)), 
            'Downloaden': str(gr.value(record, MEMORIX.accessModeDownload)),
            'Reserveren': str(gr.value(record, MEMORIX.accessModeReservation)),        
            'Fysiek aanwezig' : str(gr.value(record, MEMORIX.physicallyAvailable))
        }
        
    return acc_rights


def get_details(df, uuid, api, log, env):
    
    result = {
        'record.id': uuid,
        'errors': [],       
        'rights': [],  
        'failed': [], 
        'status': 'ok',
    }

    try:

        response = get_with_retry(api, uuid, log)
        if response.status_code != 200:
            log.error(f"Reading failed for {uuid} (status {response.status_code})")
            result['failed'].append(uuid)
            result['status'] = f'http_{response.status_code}'
            return result

        g = Graph()
        turtle = g.parse(data= response.text, format='turtle')    
        record = URIRef(f"{API_PREFIXES[env]}/resources/records/{uuid}")

        for record in g.subjects(RDF.type, MEMORIX.Record):
            acc_rights = check_rights(uuid, record, api, env)    
            if acc_rights:           
                result['rights'].append((acc_rights))      

        print(f'Printing from the get_details function{result['rights']}')

        return result
    except Exception as e:
        log.info(f'Failure in the script with error: {e}', exc_info=True) 
        log.error(f'Error in the script of t {type(e).__name__, e}') 
        errors.append({f'Failure creating the output' : f'{type(e).__name__, e}'})
        return result


def get_reservations(start_date, end_date, api, log):

    all_rows = []
    page = 1

    while True:
        response = api.list_reservations(start_date, end_date, page=page, per_page=1000)
        data = response.json()
        rows = data.get("rows", [])

        if not rows:                     
            break
        all_rows.extend(rows)
        log.info(f"Page {page}: fetched {len(rows)} rows (Total : {len(all_rows)})")

        total_pages = data.get("pagination", {}).get("total_pages")  
        if total_pages and page >= total_pages:
            break
        page += 1

    file = pd.json_normalize((all_rows))
    res = Path(HOME_REPO, 'data', project_name, 'source', 'reservations_prod.csv')
    file.to_csv(res,
            mode="w",
            sep=',',
            index=False
            )

    res_df = pd.read_csv(res, dtype={'record.id' : str}, sep=',' )

    return res_df


def main():
    parser = argparse.ArgumentParser(
            description="Flag 'Get reservations and the accessibility rights that apply to the reserved documents' "
        )
    parser.add_argument("--env", required=True, help="Path to the error CSV")
    parser.add_argument("--start", required=True, help="Start date, format: YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, format: YYYY-MM-DD")
    args = parser.parse_args()

    log, output_file, error_file, checkpoint_file = setup_logging(args.env, name, project_name)
    log.info(f'Log and outputfiles created')   


    startd = datetime.strptime(args.start, "%Y-%m-%d").date()
    endd = datetime.strptime(args.end, "%Y-%m-%d").date()
    log.info(f'ENVIRONMENT: {args.env}') 
    api, helper = get_helper(args.env)
    env = args.env 
    
    try:
        df = get_reservations(startd, endd, api, log)
        log.info(f'Reservations retrieved from api and put in a dataframe.')
    except Exception as e:
        log.info(f'Failure getting reservations with error: {e}', exc_info=True) 
        log.error(f'Error getting reservations {type(e).__name__, e}') 
           
    # -----------------------------------
    # THREADPOOL FOR WORKLOAD DIVISION
    # -----------------------------------  
    #df.loc[0, 'record.id'] = str(uuid4()) # PLANT FAKE UUID FOR TESTING
    uuids_to_process = df.head(test_amount)['record.id'].tolist()
    errors = []
    failed = []
    rights = []

    with ThreadPoolExecutor(max_workers) as executor:

        futures = {
            executor.submit(
                get_details, df, uuid, api, log, env 
            ): uuid
            for uuid in uuids_to_process
        }

        processed = 0
        for future in tqdm(as_completed(futures), total=len(futures)):
            
            processed += 1
            if processed % 500 == 0:
                pd.DataFrame(rights).to_csv(checkpoint_file, sep=';', index=False)
                log.info(f'Checkpoint saved at {processed} records')
            uuid = futures[future]
            try:
                res = future.result()
            except Exception as e:
                log.error(f"Unhandled exception for uuid {uuid}: {e}")
                errors.append({'errortext': 'Unhandled exception',
                               'record.id': uuid, 'error': str(e)})
                failed.append(uuid)
                continue

            errors.extend(res['errors'])
            rights.extend(res['rights'])
            failed.extend(res['failed'])

        total = len(rights) + len(failed)
        log.info(f'Collected {len(rights)} rights, {len(failed)} failed, is {total} total records processed')
        log.info(f'There are {len(df)} records in the dataframe and {len(df) - total} records to go')

    create_csv(errors, error_file, columns=['record.id', 'error'])
    if rights:    
        rights_df = create_df(rights)        
    else:
        log.warning('No rights collected, writing reservations only')
        merged = df
    if failed:
        df = add_server_status(df, failed)
    merged = merge_dataframes(df, rights_df)
    create_csv(merged, output_file)

if __name__ == '__main__':
    main()
