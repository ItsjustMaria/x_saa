## Import libraries
import sys
from pathlib import Path
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
import os 
import tracemalloc
import click
import simplejson as json
from datetime import time, datetime
from tqdm import tqdm
from modules import memorix
from modules import saa
import pandas as pd
import re
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace, RDF, BNode, XSD
import logging
from rapidfuzz import fuzz

## Declare script variables
env = sys.argv[1]

######################## DECLARE EXPORT VARIABLES ########################
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
logfile = f'../logs/get concept streetnames {str(current_datetime)}.log'
print (logfile)


############################# my_log SETUP ###############################
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
    
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(logfile, mode='w')]
)
my_log = logging.getLogger()


# MN acc = acceptatieomgeving env = echie tst = dry-run from home
if env == 'acc':
    prefix = 'https://ams-migrate.memorix.io'
    settings_file = Path(WORK_REPO, 'settings.json')
    cwd = os.getcwd()  # Get the current working directory (cwd)
    files = os.listdir(cwd)  # Get all the files in that directory
    print("Files in %r: %s" % (cwd, files))
elif env == 'prod':
    prefix = 'https://stadsarchiefamsterdam.memorix.io'
    settings_file = Path(WORK_REPO, 'settings.prod.json') 
elif env == 'tst':
    print(f'test output')
else:
    raise ValueError("Environment must be 'acc' or 'prod'")

settings = saa.readJsonFile(settings_file) # prod of acc
api = memorix.ApiClient(settings)

# Conceptlijst
vocabulair = 'a4863c0c-d9e5-3902-831a-d0960e381a41' # straten, of kies andere conceptlijst in Memorix

# Bestandspaden
turtle_file = "../template/deed.ttl"       # <-- Zet hier het pad naar jouw Turtle file
excel_file = "test_straten.xlsx"       # <-- Zet hier de gewenste Excel naam

# response = api.list_record_types()
# response = api.get_record_type( 'PersonObservation')
# response = api.get_record( 'Deed')
# response = api.list_record_types()
response = api.get_record_type( 'Deed')
#response = api.get_record()
print(response.text,  file=open(turtle_file, 'w', encoding='utf-8'))



### changes ###


'''if __name__ == '__main__':
        deviates = match_data(pattern, df_streets, **kwrgs)
        write_to_files(deviates, df_streets, df_concepts, **kwrgs)
        merged = merge_data(df_streets, df_concepts, df_alternatives, **kwrgs)
        output_to_file_and_db(merged, df_streets, deed, **kwrgs)'''