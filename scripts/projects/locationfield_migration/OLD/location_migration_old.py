## Import libraries
import os 
import sys
import tracemalloc
import Levenshtein
import simplejson as json
from datetime import time, datetime
from tqdm import tqdm
from uuid import uuid4
import pandas as pd
import re
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace, RDF, BNode, XSD
from collections import defaultdict
import logging
from rapidfuzz import fuzz
from pathlib import Path
import math, numpy as np
import time
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test/street_to_concept")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
from modules import saa_rdf as nrdf
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
   1) CONFIRM ENVIRONMENT
   2) Setup logging and create directories if needed
   3) Create dataframe from record uuids
   4) Retrieve record from Memorix with a single uuid per iteration
   5) Read record turtle and store needed predicates 
   6) Declare concept URI
   7) Create backup csv with current data
   8) Alter turtle with current data and concept URI by adding Bnode
   9) Create triple block for looping
   9) Look for changed data and remove old
   10) If turtle changed, update through api
   11) Add outliers to outfile

   Output files are: 
   * logs/location_migration{current_date}.log
   * files/errors_{env}.csv
   * files/outliers_{env}.csv
   * files/backup_{env}.csv

'''
# -----------------------------------
# CLI 
# -----------------------------------
env = sys.argv[1]

# -----------------------------------
# Script variables
# -----------------------------------
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
errors = []
backup = []
out = []
test_amount = 10000

# User variables
vocabulair = 'ec65be65-51ec-4272-e053-b784100a2a55'        #### !!!! uuid of vocabulair            
record_uuids = f"data/record_uuids_{env}.csv"              #### !!!! Location of uuid from memorix

def check_file_exist(folder, file, log):

    '''if not os.path.exists(folder):     
        os.makedirs(folder)
        log.info(f'{folder} directory did not exist. {folder} directory created')
    if os.path.exists(f'{folder}_{file}.csv') and 'acc' in file:     
        old_file = f'{file}_{current_datetime}.csv'
        os.rename(file, old_file)
        os.remove(f'{folder}{file}.csv')
        log.info(f'{file} already existed. A date and time was added to indicate it is old')
    if 'log' in file:
        path = f'{folder}{file}_{str(current_datetime)}.log'
        return path'''
    if 'acc' in file:
        filename = f'{folder}{file}.csv'
        if os.path.exists(filename): 
            old_file = f'{folder}{file}_{current_datetime}.csv' 
            os.rename(filename, old_file)   
        os.makedirs(folder, exist_ok=True)
    if 'log' in file:
        filename = f'{folder}{file}_{str(current_datetime)}.log'
        os.makedirs(folder, exist_ok=True)

    return filename


def setup_logging():
    
    log = logging.getLogger("organizer")
    log.setLevel(logging.DEBUG)   

    logfile = check_file_exist('logs/', 'location_migration_log', log)
    backup_file = check_file_exist('files/', f"backup_{env}", log)
    error_file = check_file_exist('files/', f"error_{env}", log)
    out_file = check_file_exist('files/', f"out_{env}", log)

    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(fh)
    log.addHandler(ch)

    return log, error_file, backup_file, out_file



# -----------------------------------
# DECLARATIONS
# -----------------------------------

# Environment setup
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

def create_csv(my_list, file):

    # Outliers to dataframe 
    csv_df = pd.DataFrame(my_list, index=range(len(my_list)))

    csv_df.to_csv(
        file,
        mode="w",
        index=False
    )

    return csv_df


def add_location_bnode(record, g,description, location_description):

    loc_bnode = BNode()
    g.add((record, SAA.isAssociatedWithLocation, loc_bnode))
    g.add((loc_bnode, RDF.type, SAA.Location))
    g.add((loc_bnode, SAA.locationTextualValue, Literal(description)))         
    g.add((loc_bnode, SAA.locationType, location_description))  

    return g, 

def main():

    log, error_file, backup_file, out_file = setup_logging()
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')

    count = 0
    g = Graph()
    turtle_changed = False

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
        errors.append({'errortext' : 'Error while creating dataframes', 'uuid': uuid, 'error' : e})
        
    for index, row in tqdm(record_df.head(test_amount).iterrows(), total=record_df.shape[0]):
        
        uuid = row.uuid
        count += 1
        log.info(f"STARTING WITH UUID: {uuid}")

        try:
            # Get Record turtle 
            response = api.get_record(uuid)
            
            if response.status_code != 200:
                time.sleep(3)
                response = api.get_record(uuid)

                if response.status_code != 200:
                    log.error(f"Reading failed for {uuid}")
                    errors.append({'errortext' : "Record does not exist", 'uuid': uuid, 'error' : response.text})
                    continue

            # load the graph
            g = Graph()
            turtle = g.parse(data= response.text, format='turtle')       
            
            record = URIRef(f"{PREFIX}/resources/records/{uuid}")


            for record in g.subjects(RDF.type, MEMORIX.Record): 

                description = str(g.value(record, SAA.addressDescription))

                location_description = URIRef(f"{PREFIX}/resources/vocabularies/concepts/{vocabulair}")

                # Create backup of current data
                backup.append({'uuid' : uuid, 'description' : description})

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
                    errors.append({'errortext' : "ERROR adding location and description", 'uuid': uuid, 'error' : [e, description]})                                  

                try: 
                    # Look for changed data and remove old
                    if (location_block, SAA.locationTextualValue, Literal(description)) in g:

                        removed_location = g.remove((record, SAA.addressDescription, None ))     

                        turtle_changed = True

                        # Create altered data csv
                        out.append({'uuid' : uuid, 'description': description, 'old description field, this should be empty' : g.value(removed_location)})

                        log.info(f'UUID: {uuid}') 
                        log.info(f'Migrated location description to new Bnode for uuid: {uuid} and description: {description}.')
                    else:
                        log.warning(f'Migration of location description failed for uuid: {uuid}')

                except Exception as e:
                        log.error(('Migration of location description failed', [uuid, e]))
                        errors.append({'errortext' : 'Migration of location description failed', 'uuid': uuid, 'error' : e})

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
                                    errors.append({'errortext' : "Update conncetion timed out for record", 'uuid': uuid, 'error' : response.text})
                                    continue     
                        else:            
                            log.error(f"Turtle update failed for row:  {uuid}")
                            errors.append({'errortext' : 'Update failed for uuid', 'uuid': uuid, 'error' : response.text})

                        log.info(f"Turtle is changed in the script. Check loginfo for details on uuid: {uuid}")

                except Exception as e:
                    log.error(('Updating of turtle failed for row:', [uuid, e]))
                    errors.append({'errortext' : 'Updating of turtle failed for row:', 'uuid': uuid, 'error' : e})
            try: 
                create_csv(errors, error_file)
                create_csv(backup, backup_file)
                create_csv(out, out_file)
            except Exception as e:
                log.error(('Creating of csv failed for row:', [uuid, e]))
                errors.append(('Creating of csv failed for row:', [uuid, e]))

        except Exception as e:
            log.error(f"Failure in the script for row: {uuid} with error : {e}")
            errors.append({'errortext' : "ERROR Main fn, failing tranformation or upload", 'uuid': uuid, 'error' : e})
    
if __name__ == '__main__':
    main()
