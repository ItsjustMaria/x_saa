# ---------------------------
# IMPORT LIBRARIES
# ---------------------------
import os 
import sys
import tracemalloc
import csv
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
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
from modules import saa_rdf as nrdf
from modules import wrapper
PREFIX = 'stadsarchief'


'''
   Empty script shell for graph alterations and updating functionality
    including logging, file documentation and such
   
   The following data is needed; 
   * give data here

   Scripts used are: 
   * saa-memorix-nexus/scripts/generic/ # Give the py name here
   
   Modules used are:
   * list api modules here

   This script does in order:  
   1) Setup logging and create directories if needed
   2) CONFIRM ENVIRONMENT AND ASK TO PROCEED
   3) Read concept turtle and store needed predicates
   4) Create dataframes from all files
   5) ####################  LIST ANY FURTHER STEPS HERE ####################
   6) Setup threadpool workload division
   7) Retrieve record from Memorix with a single uuid per iteration divided over max workload number 
   8) ####################  LIST ANY FURTHER STEPS HERE ####################

   Output files are: 
   * logs/location_migration{current_date}.log
   * files/errors_{env}.csv
   * files/outliers_{env}.csv
   * files/backup_{env}.csv

'''

# ---------------------------
# CLI ARGS
# ---------------------------
env = sys.argv[1]  # "acc" or "prod"

# -----------------------------------
# DECLARATIONS
# -----------------------------------
vocabulair = 'ec65be65-51ec-4272-e053-b784100a2a55'        #### !!!! uuid of vocabulair            
project_name = 'rename_file_to_image_output'  
source_file = Path(HOME_REPO,'data',project_name, 'export', f'rename_{env}.csv')   #### !!!! Location of uuid from memorix                                        #### !!!! State project name for data collection in file, logs and data folder     
backup = []
errors = []
out = []
test_amount = 10
max_workers= 8
pattern = r'^0(10163)0+(\d+)\.jp2$'

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
SAA = Namespace("https://data.archief.amsterdam/ontology#")
MEMORIX = Namespace("http://memorix.io/ontology#")

# -----------------------------------
# FUNCTIONS
# -----------------------------------
def main():

    sys.path.append(HOME_REPO)
    import file_management
    log, error_file, backup_file, out_file = file_management.setup_logging(env, project_name)
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')

    df_column = pd.read_csv(source_file, 
                                dtype={
                                    'uuid': str,
                                    'asset_name' : str,
                                    'identifier' : str
                                    
                                    },
                                    delimiter=';')
    #Create a helper function for the replacement
    try:

        df_column = pd.read_csv(source_file, 
                        dtype={'uuid': str, 'assetname': str, 'identifier': str},  # Use 'assetname' if that's your column name
                        delimiter=';')

        # Step 2: Rename if necessary
        if 'assetname' in df_column.columns and 'asset_name' not in df_column.columns:
            df_column = df_column.rename(columns={'assetname': 'asset_name'})
        
        # Step 3: Define transformation function
        def fix_identifier(row):
            # Skip rows where identifier already has data
            if pd.notna(row['identifier']) and row['identifier'] != '':
                return row['identifier']
            
            # Try to extract from asset_name
            if pd.notna(row['asset_name']) and row['asset_name'] != '':
                result = re.sub(r'^0(10163)0*(\d+)\.jp2$', r'\1/\2', row['asset_name'])
                # Only use result if pattern matched
                if result != row['asset_name']:
                    return result
            
            # Keep original identifier if no match
            return row['identifier']
        
        # Step 4: Apply
        df_column['identifier'] = df_column.apply(fix_identifier, axis=1)
        
        # Step 5: Verify
        print("\n=== Result ===")
        print(df_column[['asset_name', 'identifier']].head(15))
        print(f"\nProcessed {len(df_column)} rows")
        print(f"Non-empty identifiers: {(df_column['identifier'].notna() & (df_column['identifier'] != '')).sum()}")
        
    except Exception as e:
        log.info(f'Something went wrong with altering column fields')
        log.error({'Error while altering column data' : e})

    #try:
    #    print('I get here')
    #    #out_csv = file_management.create_csv(out, out_file)
#
    #except Exception as e:
    #    log.info(f'Something went wrong while creating the csv : {Path(out_file)} with error : e')
    #    log.error({'Error while creating the csv' : e})

if __name__ == '__main__':
    main()