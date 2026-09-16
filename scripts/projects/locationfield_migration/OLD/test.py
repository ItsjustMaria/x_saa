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
   
   The following data is needed; 
   * concept vocabulair
   * On file list of uuids

   Scripts used are: 
   * saa-memorix-nexus/scripts/generic/get_uuids_for_query_to_csv.py
   
   Modules used are:
   * def get_record(self, uuid, options = {}):
   * def update_record(self, uuid, turtle):

   
   #### !!!! Alteration options mentioned like this  

   This script does in order:  
   1) CONFIRM ENVIRONMENT
   2) Setup logging and create directories if needed
   3) Read concept turtle and store needed predicates
   4) Create fataframes from all files
   5) Normalize street from concept and add it to data
   6) Retrieve record from Memorix with a single uuid per iteration
   7) Read record turtle and store needed predicates and dismember the migrant street
   8) Normalise street to remove quotations and 1, 2, 3 for First, Second, Third etc.. 
   9) Look through file adamlink for alternative ways of writing and link any found adamlink to predicates df
   10) Find concept uuid by mapping all found alternative ways of writing  
   11) Add adamlink location number and add alternative names to outfile
   12) Merge dataframes based on adamlink location number for extra concept verification
   13) Write weird stuff to an out_csv
   14) Validate concept is not empty or None and fill concept uuid
   15) Validate housenumber is not empty and fill housenumber
   16) Validate housenumber addition is not empty and fill housenumber addition
   17) Upload altered turtle with a single uuid per iteration

   Output files are: 
   * logs/migr_street_to_concept_{current_date}.log
   * error/errors.csv
   * data/outliers.csv


   Export UUID's from Memorix using APi. Use these to get information from Memorix. 
   Alter this information. Upload this information back to Memorix.
   
   Call script with CLI and the environment option:

   'python this_script.py pipeline --env [specify tst /acc /prod] data_to_be_used.ext'
'''

# Script variables
errors = []
test_amount = 2000

# User variables
vocabulair = 'ec65be65-51ec-4272-e053-b784100a2a55'        #### !!!! uuid of vocabulair            
record_uuids = r"data/record_uuids_acc.csv"                           #### !!!! Location of uuid from memorixalternatives = r"data/alternatives.csv",               #### !!!! Location of external csv

def setup_logging():
    
    log = logging.getLogger("organizer")
    log.setLevel(logging.DEBUG)

    if not os.path.exists("./files"):     
        os.makedirs("./files")
        log.info(f'Files directory did not exist. Logs directory created') 
    if not os.path.exists("./files/logs"):     
        os.makedirs("./files/logs")
        log.info(f'Error directory did not exist. Error directory created') 
    if not os.path.exists("./files/error"):     
        os.makedirs("./files/error")
        log.info(f'Error directory did not exist. Error directory created') 

    current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    logfile = f'files/logs/migr_street_to_concept {str(current_datetime)}.log'

    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(fh)
    log.addHandler(ch)

    return log



def error_logging(errors):
    
    for item in errors:

        df = pd.DataFrame(item)
        df.to_csv(
            f"files/error/errors.csv",
        mode="a",
        index=False
        )
        

    errors = []


#total_record_uuids = [] 

# CLI 
env = sys.argv[1]
#data = sys.argv[2]

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


def outliers_to_csv(row, first):

    # Outliers to dataframe 
    outliers_df = pd.DataFrame( row)

    outliers_df.to_csv(
        f"files/outliers_{env}.csv",
        mode="a" if first else "a",
        header=first,
        index=False
    )
    first = False

    return outliers_df, first

def backup_to_csv(uuid, description):

    # Outliers to dataframe 
    backup_df = pd.DataFrame( [uuid, description])

    backup_df.to_csv(
        f"files/backup.csv",
        mode="a",
        index=False
    )

    return 


def add_location_bnode(record, g,description, location_description):

    loc_bnode = BNode()
    g.add((record, SAA.isAssociatedWithLocation, loc_bnode))
    g.add((loc_bnode, RDF.type, SAA.Location))
    g.add((loc_bnode, SAA.locationTextualValue, Literal(description)))         
    g.add((loc_bnode, SAA.locationType, location_description))  

    return g, 

def main():

    log = setup_logging()
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')

    count = 0
    g = Graph()
    first = True
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
        errors.append(('Error while creating dataframes' , e))
        error_logging(errors)
        
    for index, row in tqdm(record_df.head(test_amount).iterrows(), total=record_df.shape[0]):
        log.info(f"STARTING WITH UUID: {row.uuid}")
        uuid = row.uuid
        count += 1
        

        try:
            # Get Record turtle 
            response = api.get_record(uuid)
            
            if response.status_code != 200:
                time.sleep(3)
                response = api.get_record(row.uuid)

                if response.status_code != 200:
                    log.error(f"Reading failed for {row.uuid}")
                    errors.append(("Record does not exist",row))
                    error_logging(errors)
                    continue

            # load the graph
            g = Graph()
            turtle = g.parse(data= response.text, format='turtle')       
            
            record = URIRef(f"{PREFIX}/resources/records/{row.uuid}")


            for record in g.subjects(RDF.type, MEMORIX.Record): 

                description = str(g.value(record, SAA.addressDescription))

                location_description = URIRef(f"{PREFIX}/resources/vocabularies/concepts/{vocabulair}")
                
                try: 
                    # Normalize street by lowercasing, removing punctuation and letter prefixes
                    g, = add_location_bnode(record, g, description, location_description)
            
                    location_block = next(
                        g.objects(
                            record,
                            SAA.isAssociatedWithLocation
                        )
                    )

                    backup_to_csv(uuid, description)


                    
                    log.info(f"Concept vocabulair and description: {description} added for row: {row.uuid}")
                except:
                    logging.info(f'Could not create Bnode for row: {row.uuid}')
                    outliers_to_csv(row, first)
                    logging.error(f"FAILED TO ADD location description")
                    errors.append(("ERROR adding location and description",row))
                    error_logging(errors)

                # Add concept URI to saa:street if empty
                if (location_block, SAA.locationTextualValue, Literal(description)) in g:
                    
                    g.remove((record, SAA.addressDescription, None ))     

                    turtle_changed = True
                    log.info(f'UUID: {uuid}') 
                    log.info(f'Migrated location description to new Bnode for uuid: {row.uuid} and description: {description}.')
                else:
                    log.warning(f'Migration of location description failed for uuid: {uuid}')
                    errors.append(('Migration of location description failed', row))
                    error_logging(errors)

            if turtle_changed:
                turtle = g.serialize(format="turtle")
                response = api.update_record(row.uuid, turtle)
                
                if response.status_code == 200:            
                    log.info(f"Turtle succesfully updated for row: {row.uuid}")     
                else:            
                    log.error(f"Turtle update failed for row:  {row.uuid}")
                    errors.append(('Update failed for uuid', [row.uuid, response.text]))
                    error_logging(errors)
                log.info(f"Turtle is changed in the script. Check loginfo for details on uuid: {uuid}")


        except Exception as e:
            log.error(f"Failure in the script for row: {row} with error : {e}")
            errors.append(("ERROR Main fn, failing tranformation or upload", [e, row]))
            error_logging(errors)
    
if __name__ == '__main__':
    main()
