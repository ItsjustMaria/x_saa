# ---------------------------
# IMPORT LIBRARIES
# ---------------------------
import os 
import sys
from functools import wraps
from datetime import time, datetime
import pandas as pd
from rdflib import Graph, URIRef, Namespace, RDF
import logging
from pathlib import Path
import time
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
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
env = sys.argv[1]  # "acc" or "prod"

# -----------------------------------
# DECLARATIONS
# -----------------------------------
vocabulair = 'ec65be65-51ec-4272-e053-b784100a2a55'        #### !!!! uuid of vocabulair  
project_name = 'rename_file_to_image_output'          #### !!!! State project name for data collection in file, logs and data folder     
asset_uuids = Path(HOME_REPO,'data',project_name, 'source', f'assets_{env}.csv')              #### !!!! Location of uuid from memorix       
test_amount = 18000
max_workers = 8
retry_attempts = 3


# -----------------------------------
# FILE MANAGEMENT
# -----------------------------------
def check_file_exist(file, log, file_type='csv'):

    # Check file type, create file and folder and archive old files with date
    sys.path.append(str(HOME_REPO))

    if file_type == 'csv':
        ext = 'csv'
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
# NAMESPACES
# -----------------------------------
# Namespaces 
SAA = Namespace("https://data.archief.amsterdam/ontology#")
RICO = Namespace("https://www.ica.org/standards/RiC/ontology#")
MEMORIX = Namespace("http://memorix.io/ontology#")
DEED = Namespace(f"{PREFIX}/resources/recordtypes/Deed#")
SCHEMA = Namespace(f"http://schema.org/")
SKOS = Namespace(f"http://www.w3.org/2004/02/skos/core#")
DEED = Namespace (f"{PREFIX}/resources/recordtypes/Deed#")
RT = Namespace(f"{PREFIX}/resources/recordtypes")
IMAGE = Namespace(f"https://{PREFIX}.memorix.io/resources/recordtypes/Image#")
FILE = Namespace(f'https://stadsarchiefamsterdam.memorix.io/resources/recordtypes/File#')

# -----------------------------------
# FUNCTIONS
# -----------------------------------
# -----------------------------------------------------------
# RETRY DECORATOR WITH EXPONENTIAL BACKOFF
# -----------------------------------------------------------
def retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=10.0):
    """Retry decorator for functions that may fail transiently"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = base_delay
            
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        time.sleep(delay)
                        delay = min(delay * 2, max_delay)  # Exponential backoff
            
            raise last_exception  # All attempts failed
        return wrapper
    return decorator

def read_asset_turtle(record, g, uuid, asset_name, assets):

    assets.append({
          'uuid': uuid,
          'asset_name' : asset_name,
          'identifier': str(g.value(record, RICO.identifier)),
          'description': str(g.value(record, RICO.title)),
          'old_numbers' : str(g.value(record, FILE.oldNumbers))
    })

    assets_df = pd.DataFrame(assets)
    
    return assets_df

@retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=10.0)
def process_one_uuid(uuid, asset_name, out_file, log, retry_attempts):

    result = {
            'uuid': uuid,
            'errors': [],       # local list, merged into global `errors` afterward
            'backup_rows' : [], 
            'out_rows' : [], 
            'status': 'ok',
    }    

    assets = []
    turtle_changed = False

    log.info(f"STARTING WITH UUID: {uuid}")

    try:
        response = api.get_record(uuid)
        if response.status_code != 200:
            time.sleep(3)
            response = api.get_record(uuid)
                        
            if response.status_code != 200:
                log.error(f"Failed getting assets for uuid: {uuid}")
                result['errors'].append({'errortext': 'failed for uuid', 'uuid': uuid, 'error': response.text})
                result['status'] = 'failed'
                return result

        g = Graph()
        turtle = g.parse(data=response.text, format='turtle')   

        record = URIRef(f"https://{PREFIX}/resources/records/{uuid}")

        for record in g.subjects(RDF.type, MEMORIX.Record):

            '''for s,p,o in g:
                print(s,p,o)
                #input('pauze')'''

            log.info(f'This is the asset uuid : {uuid} and the asset name: {asset_name}')

            asset_df = read_asset_turtle(record, g, uuid, asset_name, assets)

            backup_df = pd.DataFrame(asset_df)
            result['backup_rows'].append(backup_df)
            
            #'''print('in')
            #uuid = "uuid"
            #identifier = "File.rico:identifier"
            #########################     READ FILES    ########################    
            ##df_column = pd.read_csv(data)
            #df_column = pd.read_csv(data, 
            #                        sep=';')
            ##df_column = pd.DataFrame(df_column)     
            #print(df_column)
            ##print(df_column[identifier])
            #print(df_column[identifier])
            #try:
            #    df_column[identifier] = df_column[identifier].str.replace(r'^0/0100120*(\d+)$', r'\1', regex=True)
            #    print(df_column[identifier])
            #    print(df_column)
#
            #    df_column.to_csv(out_file, sep=';', index=False)'''
    
#################################### COLUMN CHANGE LOGIC ##############################################################


        '''for graph_node in data.get('@graph', []):
            if "http://schema.org/name" in graph_node:
                assetname = graph_node['http://schema.org/name']
                asset_df = pd.DataFrame({'uuid' : [uuid], 'assetname' : [assetname]})
                print(asset_df)
                result['asset_rows'].append(asset_df)
            else:
                continue
               
        print(f"klaar!")'''
        
        log.info(f'Got all asset_uuids and assetnames in {Path(out_file)}')
    
    except Exception as e: 
        log.info(f'FAILED DOING SOMETHING')
        log.error(f'Error while DOING SOMETHING {e}')    

    return result

def main():

    log, error_file, backup_file, out_file = setup_logging()
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')    

    # -----------------------------------
    # THREADPOOL FOR WORKLOAD DIVISION
    # -----------------------------------  
    asset_uuids_df = pd.read_csv(asset_uuids, dtype={'uuid': str, 'assetname' : str})
    uuids_to_process = asset_uuids_df.head(test_amount)
    
    #print(Path.cwd())
    sys.path.append(HOME_REPO)
    import threadpool_executor
    #uuids_to_process = asset_uuids_df.head(test_amount)['uuid'].tolist()
    errors = []
    backup = []
    attempts = []
    retried = []
    out = []
    start_time = time.time()
    #print("Sample mappings:")
    #print(uuids_to_process[['uuid', 'assetname']].head())

    threadpool_executor.execute_threadpool(
        max_workers, 
        uuids_to_process, 
        process_one_uuid, 
        log, 
        errors,
        backup,
        retried,
        attempts,
        out,
        create_csv,
        error_file,
        backup_file,
        out_file,
        start_time,
        retry_attempts,
        api
        )
    

if __name__ == '__main__':
    main()