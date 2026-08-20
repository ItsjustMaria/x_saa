## Import libraries
import os 
import sys
from datetime import time, datetime
from tqdm import tqdm
import pandas as pd
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace, RDF, BNode
import logging
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test/")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
PREFIX = 'stadsarchief'

'''
   Script for migrating location description data to a separate Bnode field. 
   The location concept 'description' needs to be added to this same NEW bnode field.
   
   USAGE:
   python migr_street_to_concept.py --env 

   The following data is needed; 
   * concept vocabulair
   * On file list of uuids

   Scripts used are: 
   * saa-memorix-nexus/scripts/generic/get_uuids_for_query_to_csv.py
   
   Modules used are:
   * def get_record(self, uuid, options = {}):
   * def update_record(self, uuid, turtle):

   This script does in order:  
   1) Setup logging and create directories if needed
   2) CONFIRM ENVIRONMENT AND ASK TO PROCEED   
   3) Create dataframe from record uuids
   4) Setup threadpool workload division
   5) Retrieve record from Memorix with a single uuid per iteration divided over max workload number 
   6) Read record turtle and store needed predicates 
   7) Backup original data
   8) Alter turtle with current data and concept URI by adding Bnode
   9) Create triple block for alteration verification
   9) Verify changed data and remove old
   10) If turtle changed, update through api
   11) Create out files

   Output files are: 
   * logs/location_migration{current_date}.log
   * files/errors_{env}.csv
   * files/backup_{env}.csv

'''

# -----------------------------------
# CLI 
# -----------------------------------
env = sys.argv[1]

# -----------------------------------
# DECLARATIONS
# -----------------------------------
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
vocabulair = 'ec65be65-51ec-4272-e053-b784100a2a55'        #### !!!! uuid of vocabulair   
project_name = 'location_migration'         
record_uuids = Path(HOME_REPO,'data',project_name, 'source', f'record_uuids_{env}.csv')             #### !!!! Location of uuid from memorix
test_amount = 190000
max_workers= 8

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
SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")

# -----------------------------------
# FUNCTIONS
# -----------------------------------
def add_location_bnode(record, g,description, location_description):

    loc_bnode = BNode()
    g.add((record, SAA.isAssociatedWithLocation, loc_bnode))
    g.add((loc_bnode, RDF.type, SAA.Location))
    g.add((loc_bnode, SAA.locationTextualValue, Literal(description)))         
    g.add((loc_bnode, SAA.locationType, location_description))  

    return g, 

    # for index, row in tqdm(record_df.head(test_amount).iterrows(), total=record_df.shape[0]):

def process_one_uuid(uuid, log):
        
    """
    Runs the full pipeline for a single uuid.
    Returns a dict describing what happened — nothing is written to shared
    lists or files from inside this function.
    """
    result = {
        'uuid': uuid,
        'errors': [],       # local list, merged into global `errors` afterward
        'backup_rows': [],  # local list of predicates_df copies
        'outlier_rows': [], # local list for out_file
        'status': 'ok',
    }    

    turtle_changed = False
    log.info(f"STARTING WITH UUID: {uuid}")

    try:
        # Get Record turtle 
        response = api.get_record(uuid)
            
        if response.status_code != 200:
            time.sleep(3)
            response = api.get_record(uuid)

            if response.status_code != 200:
                log.error(f"Reading failed for {uuid}")
                result['errors'].append({'errortext': "Record does not exist", 'uuid': uuid})
                result['status'] = 'failed'
                return result

        # load the graph
        g = Graph()
        turtle = g.parse(data= response.text, format='turtle')       
        
        record = URIRef(f"{PREFIX}/resources/records/{uuid}")


        for record in g.subjects(RDF.type, MEMORIX.Record): 

            description = str(g.value(record, SAA.addressDescription))
            location_description = URIRef(f"{PREFIX}/resources/vocabularies/concepts/{vocabulair}")

            # Create backup of current data
            backup_df = pd.DataFrame({'uuid': [uuid], 'description': [description]})
            result['backup_rows'].append(backup_df)

            try:                           
                # Add bnode and current data to new repeatable block
                g, = add_location_bnode(record, g, description, location_description)

                # Create triple block for looping
                location_block = next(
                    g.objects(
                        record,
                        SAA.isAssociatedWithLocation
                    )
                )
                                    
                log.info(f"Concept vocabulair and description: {description} added for row: {uuid}")

            except Exception as e:
                log.info(f'Could not create Bnode for row: {uuid}')
                log.error(f"FAILED TO ADD location description", e)

            try: 
                # Look for changed data and remove old
                if (location_block, SAA.locationTextualValue, Literal(description)) in g:

                    removed_location = g.remove((record, SAA.addressDescription, None ))     

                    turtle_changed = True

                    # Create altered data csv
                    outlier_df = pd.DataFrame({'uuid' : [uuid], 'description': [description], 'old description field, this should be empty' : [g.value(removed_location)]})
                    result['outlier_rows'].append(outlier_df)

                    log.info(f'UUID: {uuid}') 
                    log.info(f'Migrated location description to new Bnode for uuid: {uuid} and description: {description}.')
                else:
                    log.warning(f'There is no description present for uuid: {uuid}')

            except Exception as e:
                    log.error(('Migration of location description failed for uuid:', [uuid, e]))

            try: 
                if turtle_changed:
                    turtle = g.serialize(format="turtle")
                    response = api.update_record(uuid, turtle)

                    if response.status_code == 200:            
                        log.info(f"Turtle succesfully updated for uuid: {uuid}")
                        if response.status_code != 200:
                            time.sleep(3)
                            response = api.get_record(uuid)
                            
                            if response.status_code != 200:
                                log.error(f"Updating failed for {uuid}")
                                result['errors'].append({'errortext': 'Update failed for uuid', 'uuid': uuid, 'error': response.text})
                                result['status'] = 'failed'       

                    else:            
                        log.error(f"Turtle update failed for row:  {uuid}")

                    log.info(f"Turtle is changed in the script. Check loginfo for details on uuid: {uuid}")
                else:
                    log.info(f"Turtle has no changes on uuid: {uuid}")    

            except Exception as e:
                log.error(('Updating of turtle failed for row:', [uuid, e]))

    except Exception as e:
        log.error(f"Failure in the script for row: {uuid} with error : {e}")

    return result

def main():

    log, error_file, backup_file, out_file = setup_logging()
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')

    g = Graph()
    

    try: 
        #Creating dataframe
        record_df = pd.read_csv(record_uuids, 
        sep=";",             
        dtype={ "uuid": str
           })

        log.info(f'UUID DF CREATED WITH : {len(record_df)} rows')

    except Exception as e: 
        log.info(f'FAILED CREATING DATAFRAME: {record_df}')
        log.error(f'Error while creating dataframe {e}')    
           
    # -----------------------------------
    # THREADPOOL FOR WORKLOAD DIVISION
    # -----------------------------------  
    uuids_to_process = record_df.head(test_amount)['uuid'].tolist()
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
            out.extend(result['outlier_rows'])
    
    # write CSVs once, after everything is done
    create_csv(errors, error_file)
    if backup:
        backup_df = pd.concat(backup, ignore_index=True)
        create_csv(backup_df, backup_file)
    if out:
        out_df = pd.concat(out, ignore_index=True)
        out_df.to_csv(out_file, mode="w", index=False)

if __name__ == '__main__':
    main()
