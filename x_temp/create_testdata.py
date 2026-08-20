## Import libraries
import os 
import sys
from datetime import time, datetime
from tqdm import tqdm
import pandas as pd
import re
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace
from collections import defaultdict
import logging
from rapidfuzz import process, fuzz
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\") # Adjust base path based on location
#HOME_REPO = Path("/opt/lampp/htdocs/test/")
#WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
# from modules import saa_rdf as nrdf
PREFIX = 'stadsarchief'

'''
   Script for updating migration street fields [CAN BE ADJUSTED] to a concept URI

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
# ---------------------------
# CLI ARGS
# ---------------------------
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
env = sys.argv[1]  # "acc" or "prod"
data = saa.readTurtleFromFile("C:\\Users\\swart053\\Downloads\\file.Turtle(17).ttl")

# -----------------------------------
# DECLARATIONS
# -----------------------------------
vocabulair = 'a4863c0c-d9e5-3902-831a-d0960e381a41'        #### !!!! uuid of vocabulair            
concept_turtle = r"data/concept_turtle.ttl"                #### !!!! Location of street turtle
record_uuids = f"data/record_uuids_{env}.csv"                           #### !!!! Location of uuid from work_apialternatives = r"data/alternatives.csv",               #### !!!! Location of external csv
pattern = r'^(?P<street>.*?)(?:\s+(?P<number>\d+)(?P<add>.*))?$'
concept_list =  []
total_concept_uuids = []
test_amount = 20
threshold=92
max_workers= 8

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

collection_uuid = '5f2d39ad-3283-40ab-9db7-fdda3ed25323'

for i in range (1,3):
    response = api.create_record(collection_uuid, data)
    print(f"record created: {response.text}")