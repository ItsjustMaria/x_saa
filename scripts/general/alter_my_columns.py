## Import libraries
import sys
import os 
from pathlib import Path
from datetime import time, datetime
from rdflib import Graph, URIRef, Literal, RDF, Namespace
import logging
import pandas as pd
import re
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test/")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
PREFIX = 'stadsarchief'

'''
   Script for updating one or more columns through the ap' 
   
   USER INPUT:
   * Specify the shacl definitions in the shacl dictionairy for every column altered 
   * Command line inpute of csv file with already altered data and column names correponding to shacl definitions

   USAGE:
   python alter_my_columns.py --env --location_of_csv_file

   The following data is needed; 
   * On file list altered csv with a ';' delimiter

   Scripts used are: 
   * 
   
   Modules used are:
   * def get_record(self, uuid, options = {}):
   * def update_record(self, uuid, turtle):

   This script does in order:  
   1) Setup logging and create directories if needed
   2) CONFIRM ENVIRONMENT AND ASK TO PROCEED   
   3) Create dataframe from the uploaded csv
   4) Add altered columns to the dataframe 
   5) Backup original data
   7) Get record per uuid 
   8) Alter turtle with desired columns
   9) If turtle changed, update through api
   10) Create out files

   Output files are: 
   * logs/location_migration{current_date}.log
   * [name]_backup_{env}.csv
   * [name]error_{env}.csv

'''
# -----------------------------------
# USER VARIABLES
# -----------------------------------
shacl = {
    'RICO.title' : 'File.rico:title',  # ADJUST NAMES ACCORDING TO THE SHACL DEFINITIONS AND COLUMN NAMES.
    'RICO.hasBeginningDate': 'File.rico:isAssociatedWithDate.rico:hasBeginningDate', # USE CAPITALS FOR NAMESPACES. SEE BELOW FOR SPECIFIC NAMESPACES USED
    'RICO.hasEndDate' : 'File.rico:isAssociatedWithDate.rico:hasEndDate' 
}                                                 # REPEAT FOR AS MANY COLUMNS AS YOU HAVE   

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
# SCRIPT VARIABLES
# -----------------------------------
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
logfile = f'..logs/change_my_column{str(current_datetime)}.log'
project_name = 'alter_my_columns'
env = sys.argv[1]
data = sys.argv[2]
result = {
    'logs': [],
    'errors': [],       # local list, merged into global `errors` afterward
    'backup': [],  # local list of predicates_df copies
    'outl': [], # local list for out_file
    'status': 'ok',
} 

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

# -----------------------------------
# FUNCTIONS
# -----------------------------------  
def create_csv(my_list, file):

    # Outliers to dataframe 
    csv_df = pd.DataFrame(my_list, index=range(len(my_list)))

    csv_df.to_csv(
        file,
        mode="w",
        sep=';',
        index=False
    )

    return csv_df

def copy_source():

    pass

def create_df(data):


    df = pd.read_csv(data, 
        sep=";",             
        dtype={  
            "uuid": str,
       })
    
    # Make empty values strings    
    df = df.fillna(value='')
   
    return df
  
def get_turtle_definitions(df, **shacl):    
    
    #Creating dataframes
    
    'RICO.title' : 'File.rico:title',  # ADJUST NAMES ACCORDING TO THE SHACL DEFINITIONS AND COLUMN NAMES.
    'RICO.hasBeginningDate': 'File.rico:isAssociatedWithDate.rico:hasBeginningDate', # USE CAPITALS FOR NAMESPACES. SEE BELOW FOR SPECIFIC NAMESPACES USED
    'RICO.hasEndDate' : 'File.rico:isAssociatedWithDate.rico:hasEndDate' 
    


        print(f'this is the key: {key}\nAnd the values:\n{value}')

def process_uuid(log):
       
    """
    Runs the full pipeline for a single uuid.
    Returns a dict describing what happened — nothing is written to shared
    lists or files from inside this function.
    """
    dates = []
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

            title, start_date, end_date = get_turtle_definitions(inst, g, uuid, dates, pattern)

            migr_street = predicates_df['extracted_street'].iloc[0]
            street_val = predicates_df['street'].iloc[0]                
            house_number = predicates_df['house_number'].notna().iloc[0]
            number_add = predicates_df['number_add'].iloc[0]
            adamlink = predicates_df['adamlink'].notna().iloc[0]

            log.info(f'predicates dataframe is created for row: {uuid}')

            try: 
                # Normalize street by lowercasing, removing punctuation and letter prefixes
                predicates_df['normalized_street'] = normalize_street_name(migr_street)
                log.info(f'Street is normalized for row: {uuid} with name : {predicates_df['normalized_street']}')
            except:
                log.error(f'can not normalize street for row: {uuid}')

            try:
                # Match street in predicates_df to all streets in external dataframe and collect the adamlink
                predicates_df = find_adamlink(predicates_df, adamlink_lookup)
                log.info(f'Known adamlink is added for row: {uuid}')
            except:
                log.error(f'can not find adamlink for row: {uuid}')
                result['errors'].append({'errortext' : f'can not find adamlink for row: {uuid}'}) 

            try:
                predicates_df = find_concept_uuid(predicates_df, concept_uuid_lookup)    
                # Get scalar value for concept uuid
                concept_uuid = predicates_df['new_concept_uuid'].iloc[0]               
                log.info(f'Street is normalized for row: {uuid}')
            except:
                log.error(f'can not find concept for row: {uuid}') 
                result['errors'].append({'errortext' : f'can not find concept for row: {uuid}'})               

            try:
                # Get number from adamlink in all dataframes and add alternatives to list in concepts
                predicates_df = add_predicate_alt_number(predicates_df)
                log.info(f'Adamlink location number added for row: {uuid}')
            except:
                log.error(f'can not find adamlink location number for row: {uuid}')
                result['errors'].append({'errortext' : f'can not find adamlink location number for uuid: {uuid}'})   

            try:
                # Merge concepts on same street
                new_merge, predicates_df = merge_dataframes(concept_df, predicates_df)
                log.info(f'Dataframes merged for row: {uuid}')
            except:
                log.error(f'merging dataframes failed for row: {uuid}')  
                result['errors'].append({'errortext' : f'merging dataframes failed for uuid: {uuid}'})                             

            result['outlier_rows'].append(new_merge)

            result['backup_rows'].append(predicates_df.copy())

            # Add concept URI to saa:street if empty
            if street_val == '' or street_val == 'None':
                if pd.notna(concept_uuid) and concept_uuid != '':
                    concept_uri = URIRef(f"{PREFIX}/resources/vocabularies/concepts/{concept_uuid}")
                    g.add((inst, SAA.street, concept_uri))
                    turtle_changed = True
                    log.info(f'UUID: {uuid}') 
                    log.info(f'Changed migrant street: {predicates_df['streetTextualValue']} to normalized street : {predicates_df['normalized_street']}.')
                    log.info(f'Filled concept {concept_uuid} and concept street name: {predicates_df['streetTextualValue']}')                        
                else:
                    log.warning(f'UUID: {uuid} No concept match found for street {predicates_df['extracted_street']}')

            else:
                log.info(f"Street already filled for uuid {uuid}")
                log.error(f'Concept already filled for uuid: {concept_uuid}')  

            # Fill houseNumber only if empty     
            if house_number == '' or house_number == 'None':
                extracted_number = predicates_df['extracted_number'].iloc[0]
                if extracted_number and extracted_number != '':
                    g.add((inst, SAA.houseNumber, Literal(extracted_number)))
                    turtle_changed = True
                    log.info(f"Housenumber was empty and is now filled for uuid {uuid}")                        
            else:
                log.info(f"HouseNumber: {predicates_df['house_number']} not changed for uuid {uuid}")    

            # Fill houseNumberAddition only if empty
            if number_add == '' or number_add == 'None':
                extracted_add = predicates_df['extracted_add'].iloc[0]
                if extracted_add and extracted_add != '':
                    g.add((inst, SAA.houseNumberAddition, Literal(extracted_add)))
                    turtle_changed = True
                    log.info(f"Housenumber addition was empty and is now filled for uuid {uuid}")
            else:
                log.info(f"HouseNumberAddition : {predicates_df['number_add']} not changed for uuid {uuid}")

        if turtle_changed:
            turtle = g.serialize(format="turtle")
            response = api.update_record(uuid, turtle)
            if response.status_code == 200:            
                log.info(f"Turtle succesfully updated for row: {uuid}")  
                if response.status_code != 200:
                    datetime.time.sleep(3)
                    response = api.get_record(uuid)
                    if response.status_code != 200:
                        log.error(f"Updating failed for {uuid}")
                        result['errors'].append({'errortext': 'Update failed for uuid', 'uuid': uuid, 'error': response.text})
                        result['status'] = 'failed'    
            else:            
                log.error(f"Turtle update failed for row:  {uuid}")
                log.info(f"Turtle is changed in the script. Check loginfo for details on uuid: {uuid}")


    except Exception as e:
        log.error(f"Failure in the script for row: {uuid} with error : {e}")
        result[' errors'].append({'errortext': "ERROR Main fn, failing transformation or upload", 'uuid': uuid, 'error': str(e)})
        result['status'] = 'failed'

    return result

# memorix.get_record_type(name)
def main():
    sys.path.append(str(WORK_REPO))
    from general import threadpool_executor

    try: 
        df = create_df(data)

        result['logs'].append({'info' : f'There are : {len(df)} rows in the datasheet.'})
        

    except Exception as e: 
        result['logs'].append({'info' : f'FAILED CREATING DATAFRAME from the record_uuids'})
        result['logs'].append({'error' : f'Error while creating dataframe with error: {e} as {type(e).__name__, e}'})    
        result['errors'].append({'errortext' : f'Error while creating dataframe with error: {e} as {type(e).__name__, e}'})

    try:
        threadpool_executor.execute_threadpool(
                    df,
                    max_workers,
                    process_one_uuid,
                    project_name,
                    test_amount,
                    retry_attempts,
                    env,
                    name,
                    attempts = 0
                    )
    except Exception as e: 

        result['logs'].append({'info' : f'FAILED accessing the threadpool executor'})
        result['logs'].append({'error' : f'FAILED accessing the threadpool executor with error: {e} as {type(e).__name__, e}'})    
        result['errors'].append({'errortext' : f'Error while accessing the threadpool executor with error: {e} as {type(e).__name__, e}'})


    except:
        log.info(f'Something went wrong with replacing the data in {df}')
        #print(f'We have an error in {df_column}') ##################   ------------->>> HIER WILLEN WE DE FILENAAM EXTRACTEN

if __name__ == '__main__':
    main()