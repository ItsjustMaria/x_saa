import sys
import json
import os
import csv
import time
import logging
from pathlib import Path
from datetime import time, datetime
import time
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
from modules import memorix_urllib3 
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
project_name = 'reservations_with_added_info'                            ## PROJECT NAME IS FOLDER NAME FOR ALL DATA. CHANGE NAME IF DESIRED
PREFIX = 'stadsarchief'
env = sys.argv[1]
test_amount = 1
data = Path(HOME_REPO,'data',project_name, 'source', f'res_export.csv') 


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

def create_csv(my_list, file):

    # Outliers to dataframe 
    csv_df = pd.DataFrame(my_list)

    csv_df.to_csv(
        file,
        mode="w",
        index=False
    )

    return csv_df

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
def files_per_fonds(fund, file_id, env):
    
    api, helper = get_helper(env)

    uuid = helper.find_file_uuid_with_fonds_and_record_nr(fund, file_id, env)
    
    return uuid

def find_fund_uuid(fund,env):

    api, helper = get_helper(env)

    fund_uuid = helper.find_fonds_uuid(fund)
    
    return fund_uuid

def check_rights(uuid):

    api, helper = get_helper(env)

    result = api.get_ar_for_record(uuid)
    
    ''' existing_labels = list(g.objects(file, RICO.hasDocumentaryFormType))
    for existing_label in existing_labels:
        label = g.value(existing_label, SKOS.prefLabel)
        if label == Literal("audiovisueel document"):
            concept_exists = True
            break '''
        
    return result


def get_details(uuid, env, log):
    
    api, helper = get_helper(env)
    # Get Record turtle 
    try:    
        response = api.get_record('6929f22d-87c3-498f-a926-fc477831417e')
        if response.status_code != 200:
            time.sleep(3)
            response = api.get_record('6929f22d-87c3-498f-a926-fc477831417e')
            if response.status_code != 200:
                log.error(f"Reading failed for {uuid}")
                log.error({'errortext': "Record does not exist", 'uuid': uuid})

        g = Graph()
        turtle = g.parse(data= response.text, format='turtle')    
        print(response.text)
        file = URIRef(f"{PREFIX}/resources/records/{uuid}")
        
        for file in g.subjects(RDF.type, MEMORIX.Record):

            rights = check_rights(uuid)
            print(rights)


            
            #rights = g.value(file, MEMORIX.restrictionsExpire)
            print(rights)
        #for inst in g.result = helper.get_details_from_ar(response.text)
        #print(result)
            return rights

    except Exception as e:
        log.info(f'Failure in the script with error: {e}', exc_info=True) 
        log.error(f'Error in the script of t {type(e).__name__, e}') 
        template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
        message = template.format(type(e).__name__, e.args)
        log.error(message)
    
def find_extra_data():
    pass


def main():

    log, error_file, backup_file, out_file = setup_logging(env, project_name, project_name)
    g = Graph()
    backup = []
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ANALYZE DATA NOW?\": (Y/N)')

    df = pd.read_csv(data, sep=",",             
        dtype={ "Fonds Id": str,
                "File Id": str,
    })
  
    try: 
        df.loc[:test_amount-1, 'uuid'] = df.head(test_amount).apply(
            lambda row: files_per_fonds(row['Fonds Id'], row['File Id'], env),
            axis=1
        )
    except Exception as e:
        log.info(f'Failure in the script with error: {e}', exc_info=True) 
        log.error(f'Error in the script of t {type(e).__name__, e}') 
        template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
        message = template.format(type(e).__name__, e.args)
        log.error(message)

    try: 
        df.loc[:test_amount-1, 'fund_uuid'] = df.head(test_amount).apply(
            lambda row: find_fund_uuid(row['Fonds Id'], env),
            axis=1
        )

    except Exception as e:
        log.info(f'Failure in the script with error: {e}', exc_info=True) 
        log.error(f'Error in the script of t {type(e).__name__, e}') 
        template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
        message = template.format(type(e).__name__, e.args)
        log.error(message)

    try: 
        df['details'] = df.head(test_amount).apply(
            lambda row: get_details(row['uuid'], env, log),
            axis=1
        )
        #print(df['details'])
    except Exception as e:
        log.info(f'Failure in the script with error: {e}', exc_info=True) 
        log.error(f'Error in the script of t {type(e).__name__, e}') 
        template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
        message = template.format(type(e).__name__, e.args)
        log.error(message)

    create_csv(df, backup_file)

    #try: 
    #    out_file = files_per_fonds(fund, env, out_file)
    #    log.info(f'Retrieved files and data for fund: {fund}.')
#
    #except Exception as e:
    #    log.info(f'Failure in the script with error: {e}', exc_info=True) 
    #    log.error(f'Error in the script of t {type(e).__name__, e}') 
    #    template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
    #    message = template.format(type(e).__name__, e.args)
    #    log.error(message)

if __name__ == '__main__':
    main()
