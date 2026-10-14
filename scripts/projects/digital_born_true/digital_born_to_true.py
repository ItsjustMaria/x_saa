## Import libraries
import sys
from datetime import time, datetime
import pandas as pd
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace, RDF, BNode, XSD
from pathlib import Path
import time
import logging
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test/")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
PREFIX = 'stadsarchief'

'''
   Script for setting the 'digital born' indicator on a single record of type 'record' to 'true' 
   
   USAGE:
   python digital_born_to_true.py --env --name_of_csv_file

   The following data is needed; 
   * On file list of uuids

   Scripts used are: 
   * 
   
   Modules used are:
   * def get_record(self, uuid, options = {}):
   * def update_record(self, uuid, turtle):

   This script does in order:  
   1) Setup logging and create directories if needed
   2) CONFIRM ENVIRONMENT AND ASK TO PROCEED   
   3) Create dataframe from record uuids
   4) Retrieve record from Memorix with a single uuid per iteration divided over max workload number 
   5) Determine graph values
   6) Backup original data
   7) Read record turtle for current status digital born 
   8) Alter turtle with desired digital born state
   9) If turtle changed, update through api
   10) Create out files

   Output files are: 
   * logs/location_migration{current_date}.log
   * [name]_out_{env}.csv
   * [name]_backup_{env}.csv
   * [name]error_{env}.csv

'''

# -----------------------------------
# CLI 
# -----------------------------------
env = sys.argv[1]
name = sys.argv[2]

# -----------------------------------
# DECLARATIONS
# -----------------------------------
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
vocabulair = 'ec65be65-51ec-4272-e053-b784100a2a55'        #### !!!! uuid of vocabulair   
project_name = 'digital_born_to_true'         
record_uuids = Path(HOME_REPO,'data',project_name, 'source', f'{name}.csv')             #### !!!! Location of uuid from memorix
test_amount = 100000
#max_workers= 8
#retry_attempts = 3
errors = []
backup = []
out = []

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
FILE = Namespace(f"{PREFIX}/resources/recordtypes/File#")
SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")

# -----------------------------------
# FUNCTIONS
# -----------------------------------

def process_one_uuid(log):
        
    try: 
        #Creating dataframe
        record_uuids_df = pd.read_csv(record_uuids, 
        sep=";",             
        dtype={ "uuid": str
           })
        record_df = record_uuids_df[['uuid']].drop_duplicates()
        log.info({'info' : f'UUID DF CREATED WITH : {len(record_df)} rows'})
  

    except Exception as e: 
        log.info({'info' : f'FAILED CREATING DATAFRAME: {record_df}'})
        log.error({'errortext' : f'Error while creating dataframe {e}'})    

    turtle_changed = False

    try:

        for idx, row in record_df.head(test_amount).iterrows():
            uuid = row['uuid']

            log.info({'info' : f"STARTING WITH UUID: {uuid}"})
    
            # Get Record turtle 
            response = api.get_record(uuid)

            if response.status_code != 200:
                time.sleep(3)
                response = api.get_record(uuid)

                if response.status_code != 200:
                    log.error({'errortext' : f"Reading failed for {uuid}"})
                    errors.append({'errortext': f'Record does not exist for uuid: {uuid}'})

            # load the graph
            g = Graph()
            turtle = g.parse(data= response.text, format='turtle')       

            record = URIRef(f"{PREFIX}/resources/records/{uuid}")


            for record in g.subjects(RDF.type, MEMORIX.Record): 

                digital_born = str(g.value(record, FILE.digitalBorn))

                # Create backup of current data
                backup_df = pd.DataFrame({'uuid': [uuid], 'digital born value': [digital_born]})
                backup.append(backup_df)

                try:                           
                    # Check if false and - if s -o set to true
                    if digital_born == 'false':

                        g.set((record, FILE.digitalBorn, Literal(True, datatype=XSD.boolean)))

                        turtle_changed = True

                        log.info({  f'digital born set to \'True\' for UUID: {uuid}'}) 
                    else:
                        log.info({  f'Digital born was already set to True. Nothing changed for uuid: {uuid}'})
                        print('I get here')

                except Exception as e:
                        log.error({'errortext' : f'Was not able to change the digital born boolean for uuid:, {uuid}, with error: {e}'})
                        errors.append({'error' : f'Was not able to change the digital born boolean for uuid:, {uuid}, with error: {e}'})
                try: 
                    if turtle_changed:
                        turtle = g.serialize(format="turtle")
                        response = api.update_record(uuid, turtle)

                        if response.status_code == 200:            
                            log.info({  f"Turtle succesfully updated for uuid: {uuid}"})
                            if response.status_code != 200:
                                time.sleep(3)
                                response = api.update_record(uuid,turtle)

                                if response.status_code != 200:
                                    log.error({'errortext' :  f"Updating failed for {uuid}"})
                                    log.error({'errortext' : f'Update failed for uuid: {uuid} with error: {response.text}'})


                        else:            
                            log.error({'errortext' : f"Turtle update failed for row:  {uuid}"})

                        #log.info({  f"Turtle is changed in the script. Check loginfo for details on uuid: {uuid}"})
                    else:
                        log.info({  f"Turtle has no changes on uuid: {uuid}"})    

                except Exception as e:
                    log.error({'errortext' : f'Updating of turtle failed for uuid: {uuid}, with error: {e}'})
                    errors.append({'errortext' : f'Updating of turtle failed for uuid: {uuid}, with error: {e}'})

    except Exception as e:
        log.error({'errortext' : f"Failure in the script for row: {row['uuid']} with error : {e}"})
        errors.append({'errortext' : f"Failure in the script for row: {row['uuid']} with error : {e}"})



def main():
    sys.path.append(str(f'{HOME_REPO}/scripts' ))
    from general import file_and_log_management
    log, error_file, backup_file, out_file = file_and_log_management.setup_logging(env, name, project_name)    
    
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')

    process_one_uuid(log)

    file_and_log_management.create_csv(errors, error_file)
    if backup:
        backup_df = pd.concat(backup, ignore_index=True)
        backup_df.to_csv(backup_file, mode="w", index=False)
        file_and_log_management.create_csv(backup_df, backup_file)
    if out:
        out_df = pd.concat(out, ignore_index=True)
        out_df.to_csv(out_file, mode="w", index=False)
        file_and_log_management.create_csv(out_df, out_file)    
    '''if errors:
        error_df = pd.concat(errors, ignore_index=True)
        error_df.to_csv(error_file, mode="w", index=False)
        file_and_log_management.create_csv(error_df, error_file)  '''

if __name__ == '__main__':
    main()
