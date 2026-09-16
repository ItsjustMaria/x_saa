#---------------------------
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
turtle = Path(HOME_REPO,'data','turtle', f'rename_file_to_output.ttl')   #### !!!! Location ofturtle
backup = []
errors = []
out = []
test_amount = 18000
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
RICO = Namespace("https://www.ica.org/standards/RiC/ontology#")

# -----------------------------------
# FUNCTIONS
# -----------------------------------

def generate_csv(df, out_file):

    out_df = pd.DataFrame(df, dtype="object")

    df.to_csv(
            out_file,
            mode="a",
            index=False
            )
    
    return 

def main():

    #sys.path.append(HOME_REPO)
    from general import file_and_log_management
    log, error_file, backup_file, out_file = file_and_log_management.setup_logging(env, project_name)

    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')

    # Create dataframe
    df_column = pd.read_csv(source_file, 

        dtype={
            'uuid': str,
            'asset_name' : str,
            'identifier' : str
            
            },
            delimiter=';')
    #Create a helper function for the replacement

    try:
        # mask: only rows where asset_name is actually filled in
        mask = df_column['asset_name'].notna()

        # extract the digits after the leading 010163 + zeros, before .jp2
        extracted = df_column.loc[mask, 'asset_name'].str.extract(r'^0101630+(\d+)\.jp2$')[0]

        # build identifier and assign only into the masked rows
        df_column.loc[mask, 'identifier'] = '10163/' + extracted

        out.append(df_column)

        print(df_column.loc[mask, ['asset_name', 'identifier']].head(10))
        print(df_column['identifier'].notna().sum())  # should be ~3700

    except Exception as e:
            log.info(f'Something went wrong with altering column fields')
            log.error({'Error while altering column data' : e})

    try:

        for idx, row in df_column[4000:].iterrows():

            uuid = row.uuid                      
            
            # Get Record turtle 
            response = api.get_record(uuid)

            if response.status_code != 200:
                time.sleep(3)
                response = api.get_record(uuid)

                if response.status_code != 200:
                    log.error(f"Reading failed for {uuid}")
                    log.error({'errortext': "Record does not exist", 'uuid': uuid})

            # load the graph
            g = Graph()
            turtle = g.parse(data=response.text, format='turtle')  
            
            record = URIRef(f"{PREFIX}/resources/records/{uuid}")

            for record in g.subjects(RDF.type, MEMORIX.Record):

                '''# Logica werkt niet! Hij ziet de NaN duidelijk ook als .notna() Ik weet niet wat
                # er precies in die velden staat, maar hij geeft hem nu door als een aanpassing. 
                # Je moet denk ik echt checken op ""'''     
                #identifier_changed = df_column['asset_name'].notna().iloc[0]
                identifier_changed = df_column['asset_name'].iloc[0] == '' # or df_column['asset_name'].iloc[0] != None
                #number = []
                #number.append(identifier_changed)
                #print(f' This is the amount of changed assets: {len(identifier_changed)}')
                #print(identifier_changed)
                value = df_column['asset_name'].iloc[4000] 
                print(df_column['asset_name'].iloc[4000] == '')
                print(f'I am 4000: { value}')
                print(f'O am identifier changed : {identifier_changed}')
                generate_csv(df_column, out_file)
                identifier = str(g.value(record, RICO.identifier))    
                #print(f'This is the identifier: {identifier}')
                new_identifier = row.identifier
                #print(f'This is the new identifier: {new_identifier}')    

                if identifier_changed:
                    #print('I get in the logic')
                    g.remove((record, RICO.identifier, None))  
                    changed_identifier = g.add((record, RICO.identifier, Literal(new_identifier)))
                    turtle_changed = True   
                    #print(changed_identifier)


                try:
                    if turtle_changed:
                        turtle = g.serialize(format="turtle")
                        #print('I am trying to change')
                        #response = api.update_record(uuid, turtle)
                        if response.status_code == 200:            
                            log.info(f"Turtle succesfully updated for row: {uuid}")  
                            if response.status_code != 200:
                                time.sleep(3)
                                #response = api.get_record(uuid)
                                if response.status_code != 200:
                                    log.error(f"Updating failed for {uuid}")

                        else:            
                            log.error(f"Turtle update failed for row:  {uuid}")
                            log.info(f"Turtle is changed in the script. Check loginfo for details on uuid: {uuid}")


                except Exception as e:
                    log.error(f"Failure in the script for row: {uuid} with error : {e}")
                    log.error({'errortext': "ERROR Main fn, failing transformation or upload", 'uuid': uuid, 'error': str(e)})

    except Exception as e:
        log.error(f"Failure in the script for row: {uuid} with error : {e}")

    try:
        print('I get here')
        #out_csv = file_management.create_csv(out, out_file)

        df_column.to_csv(
                out_file,
                mode="w",
                index=False
            )

    except Exception as e:
        log.info(f'Something went wrong while creating the csv : {Path(out_file)} with error : e')
        log.error({'Error while creating the csv' : e})

if __name__ == '__main__':
    main()