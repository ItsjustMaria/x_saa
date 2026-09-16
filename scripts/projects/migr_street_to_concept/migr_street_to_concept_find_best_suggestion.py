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
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test/")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
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
# CLI AD DECLARATIONS
# ---------------------------
env = sys.argv[1]  # "acc" or "prod"

project_name = 'migr_street_to_concept'                    #### !!!! State project dir name for data collection in file, logs and data folder     
data = sys.argv[2] if len(sys.argv) > 2 else Path(HOME_REPO,'data',project_name, 'source', f'alternatieve_straatnamen.csv') 

current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
vocabulair = 'a4863c0c-d9e5-3902-831a-d0960e381a41'        #### !!!! uuid of vocabulair 

concept_turtle = Path(HOME_REPO,'data', 'turtle', "concept.ttl")                #### !!!! Location of street turtle
record_uuids = Path(HOME_REPO,'data',project_name, 'source', f'record_uuids_{env}.csv')                           #### !!!! Location of uuid from work_apialternatives = r"data/alternatives.csv",               #### !!!! Location of external csv
pattern = r'^(?P<street>.*?)(?:\s+(?P<number>\d+)(?P<add>.*))?$'
concept_list =  []
total_concept_uuids = []
test_amount = 20000
threshold=70
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
SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")

# -----------------------------------
# FUNCTIONS
# -----------------------------------

def read_concept_turtle(s, g, s_str):
    
    match = re.search(r'/vocabularies/concepts/([^/>]+)', s_str)
    uuid = match.group(1) if match else ""

    prefLabel = next((str(lab) for lab in g.objects(s, SKOS.prefLabel)), "")
    exactMatch = next((str(em) for em in g.objects(s, SKOS.exactMatch)), "") # <-- fout: want exactMatch kan nu meer dan 1 waarde hebben
    scopeNote = next((str(sn) for sn in g.objects(s, SKOS.scopeNote)), "")
    
    concept_list.append({
        'concept_uuid' : uuid,
        'streetTextualValue' : prefLabel,
        'adamlink' : exactMatch,
        'scope' : scopeNote
    }) 
    
    total_concept_uuids.append(uuid)   

    return concept_list, total_concept_uuids
    

def extract_street(inst, g, uuid, predicates, pattern):
    
    predicates.append({
          'uuid': uuid,
          'streetTextualValue': str(g.value(inst, SAA.streetTextualValue)),
          'house_number': str(g.value(inst, SAA.houseNumber)),
          'number_add': str(g.value(inst, SAA.houseNumberAddition)),
          'street' : str(g.value(inst, SAA.street)),
          'adamlink' : str(g.value(None, SAA.hasOrHadSubjectLocation))
    })
    
    # Turn turtle predicates to dataframe
    predicates_df = pd.DataFrame(predicates)

    predicates_df = predicates_df.fillna('')
    predicates_df = predicates_df.replace('None', '')
    
    # Migration street extraction in street number, number addition
    extract_pattern = predicates_df['streetTextualValue'].str.extract(pattern)

    # Add string parts to dataframe
    predicates_df['extracted_street'] = extract_pattern['street'].str.strip()
    predicates_df['extracted_number'] = extract_pattern['number'].str.strip()
    predicates_df['extracted_add'] = extract_pattern['add'].str.strip()

    # Normalize empty fields and replace string 'None' with empty string
    predicates_df.fillna("",inplace=True)
    predicates_df['house_number'] = predicates_df['house_number'].replace('None', '')
    predicates_df['extracted_number'] = predicates_df['extracted_number'].replace('None', '')
    predicates_df['number_add'] = predicates_df['number_add'].replace('None', '')
    predicates_df['extracted_add'] = predicates_df['extracted_add'].replace('None', '')
    
    return predicates_df, predicates_df.streetTextualValue, predicates_df.street, predicates_df.house_number, predicates_df.number_add, predicates_df.adamlink

def normalize_add(number_add):

    print(f'I get in the normalized with the addition: {number_add}')    
    replacement = {
        r'\b-i\b': "-1",
        r'\b-ii\b' : "-2",
        r'\b-iii\b': "-3",
        r'\b-iv\b': "-4", 
        r'\b-v\b': "-5", 
        r'\b^i\b': "-1",
        r'\b^ii\b' : "-2",
        r'\b^iii\b': "-3",
        r'\b^iv\b': "-4",
        r'\bv\b': "-5",
        r'\bi\b': "1",
        r'\bii\b' : "2",
        r'\biii\b': "3",
        r'\biv\b': "4", 
        r'\bv\b': "5",         
    }
    print(f'this is the number add type: {type(number_add)}')
    # Remove punctuation
    number_add = re.sub(r'[^\w\s]', '', number_add)
    print(f'First adaptation addition: {number_add}')
    # Normalize abbreviations for numbered streets 
    for pattern, replacement in replacement.items():
        number_add = re.sub(pattern, replacement, number_add) 
    print(f'After the for loop addition: {number_add}')
    # Extra whitespace removal
    number_add = ' '.join(number_add.split())
    print(f'Joining the addition addition: {number_add}')
    print(f'This is what it normalized : {number_add}')
    return number_add

def normalize_street_name(street):
    
    replacement = {
        r'\b1\b|\b1e\b|\b1ste\b': "Eerste",
        r'\b2\b|\b2e\b|\b2de\b' : "Tweede",
        r'\b3\b|\b3e\b|\b3de\b': "Derde",
        r'\b4\b|\b4e\b|\b4de\b': "Vierde",
        r'\bN\b|\bnwe\b|\bNwe\b': "Nieuwe",
        r'utrechtsche|Utrechtsche' : "Utrechtse",
        r'leidsche|Leidsche' : 'Leidse'
    }

    # Remove punctuation
    street = re.sub(r'[^\w\s]', '', street)

    # Normalize abbreviations for numbered streets 
    for pattern, replacement in replacement.items():
        street = re.sub(pattern, replacement, street) 

    # Extra whitespace removal
    street = ' '.join(street.split()).lower()

    return street

def get_fuzzy_adamlink(street, adamlink_to_streets, threshold):

    for adamlink, candidates in adamlink_to_streets.items():
        match = process.extractOne(street, candidates, scorer=fuzz.ratio, score_cutoff=threshold)
        if match:
            return adamlink
    return None

def build_lookup(df, key_col, name_cols):
    lookup = defaultdict(list)
    for _, row in df.iterrows():
        key = row[key_col]
        if pd.notna(key):
            for col in name_cols:
                val = row[col]
                if isinstance(val, str) and pd.notna(val):
                    lookup[key].append(val)
                elif isinstance(val, (list, tuple, set)):
                    lookup[key].extend(v for v in val if isinstance(v, str))
             
    return lookup

def find_adamlink(predicates_df, adamlink_lookup, threshold=95):

    predicates_df['new_adamlink'] = predicates_df['streetTextualValue'].apply(
        lambda s: get_fuzzy_adamlink(s, adamlink_lookup, threshold)
    )
    mask = predicates_df['new_adamlink'].isna()
    predicates_df.loc[mask, 'new_adamlink'] = predicates_df.loc[mask, 'normalized_street'].apply(
        lambda s: get_fuzzy_adamlink(s, adamlink_lookup, threshold)
    )
    return predicates_df

def find_concept_uuid(predicates_df, concept_uuid_lookup, threshold=95):

                
    predicates_df['new_concept_uuid'] = predicates_df['streetTextualValue'].apply(
        lambda s: get_fuzzy_adamlink(s, concept_uuid_lookup, threshold)
    )
    
    mask = predicates_df['new_concept_uuid'].isna()
    predicates_df.loc[mask, 'new_concept_uuid'] = predicates_df.loc[mask, 'normalized_street'].apply(
    lambda s: get_fuzzy_adamlink(s, concept_uuid_lookup, threshold)
    )
    
    return predicates_df

def add_predicate_alt_number(predicates_df):

    predicates_df['alt_number'] = predicates_df['new_adamlink'].str.extract(r'(\d+)')

    return predicates_df


def merge_dataframes(concept_df, predicates_df):
    
    # merge dfs to accumulate all data  
    merge_dfs = predicates_df.merge(concept_df[['alt_number', 'concept_uuid', 'alternative_names']], on = 'alt_number', how='left')
    
    new_merge = merge_dfs.drop_duplicates(subset=['uuid'])

    # Assign working name to merged dataframe            
    predicates_df = new_merge

    return new_merge, predicates_df

def outliers_to_csv(new_merge, out_file, first):

    # Outliers to dataframe based on index predicates
    outliers_df = pd.DataFrame( index=new_merge.index)
    outliers_df['uuid'] = new_merge['uuid']

    # Fill numbers etc where deviant
    street_map = {
                  'house_number': 'extracted_number',
                  'number_add': 'extracted_add',
    }
        
    for target, source in street_map.items():

        # mask to fill empty fields 
        mask_fill = (
            new_merge[target].isna() &
            new_merge[source].notna()
        )
        outliers_df.loc[mask_fill, target] = new_merge.loc[mask_fill, source]
        
        # Write to outliers if data already exists
        mask_to_csv = (
            new_merge[target].notna() &
            new_merge[source].notna() &
            (new_merge[target] != new_merge[source])
        )
        outliers_df.loc[mask_to_csv, target] = new_merge.loc[mask_to_csv, source]

        merge_concepts = outliers_df.merge(new_merge[['uuid', 'alternative_names']], on = 'uuid', how='left' )
        outliers_df = merge_concepts

    outliers_df.to_csv(
        out_file,
        mode="w" if first else "a",
        header=first,
        index=False
        
    )
    first = False


    return outliers_df, first

def process_one_uuid(uuid, concept_df, adamlink_lookup, concept_uuid_lookup, log):
        
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

    predicates = []
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

        for inst in g.objects(None, SAA.isAssociatedWithModernAddress): 

            predicates_df, _, _, _, _, _ = extract_street(inst, g, uuid, predicates, pattern)

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

            '''###################### OPTIONAL NORMALISATION OF ROMAN NUMERALS ############################'''
            #try: 
            #    # Normalize housenumber addition by changing roman lettering to latin and adding a dash if missing
            #    predicates_df['normalized_number_addition'] = normalize_add(number_add)
            #    normalized_add = predicates_df['normalized_number_addition'].iloc[0]
            #except Exception as e:
            #    log.error(f'can not normalize number addition for row: {uuid} with error {e}')

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

            """
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

            '''###################### OPTIONAL NORMALISATION OF ROMAN NUMERALS ############################''' 
            #if number_add == '' or number_add == 'None' or normalized_add:               
            #    if normalized_add and (normalized_add != '' or normalized_add != 'None'):
            #        print(f'###################################################### \n I GET INTO THE LOGIC. \n The normalize add = {normalized_add} \n########################################################')
            #        extracted_add = predicates_df['normalized_number_addition'].iloc[0]
            #        g.add((inst, SAA.houseNumberAddition, Literal(number_add)))
            #        g.add((inst, SAA.houseNumberAddition, Literal(normalized_add)))
            #        turtle_changed = True
            #        log.info(f"Housenumber addition was empty and is now filled for uuid {uuid}")
            #    else: 
            #        extracted_add = predicates_df['extracted_add'].iloc[0]
            #        if extracted_add and extracted_add != '':
            #            g.add((inst, SAA.houseNumberAddition, Literal(extracted_add)))
            #            turtle_changed = True
            #            log.info(f"Housenumber addition was empty and is now filled for uuid {uuid}")
            #else:
            #    log.info(f"HouseNumberAddition : {predicates_df['number_add']} not changed for uuid {uuid}")

        if turtle_changed:
            turtle = g.serialize(format="turtle")
            response = api.update_record(uuid, turtle)
            if response.status_code == 200:            
                log.info(f"Turtle succesfully updated for row: {uuid}")  
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

        """
                
    except Exception as e:
        log.error(f"Failure in the script for row: {uuid} with error : {e}")
        result['errors'].append({'errortext': "ERROR Main fn, failing transformation or upload", 'uuid': uuid, 'error': str(e)})
        result['status'] = 'failed'

    return result

def main():

    log, error_file, backup_file, out_file = setup_logging()
    g = Graph()
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ANALYZE DATA NOW?\": (Y/N)')

    try: 
        # Read concept turtle and put in list
        print(Path(concept_turtle))
        g.parse(concept_turtle, format='turtle') 

        for s in g.subjects(rdflib.RDF.type, SKOS.Concept):
            s_str = str(s)
    
            concept_list, total_concept_uuids = read_concept_turtle(s, g, s_str) 

        log.info(f'A total of : {len(concept_list)} are stored in a list. There are : {len(total_concept_uuids)} concepts retrieved from the turtle. There have been : {len(concept_list) - len(total_concept_uuids)} losses during data extraction.')
        log.info(f'Concept turtle put in list with a total of {len(total_concept_uuids)} concepts')   

    except Exception as e:
        log.info(f'Reading the concept turtle failed {e}')
        log.error(f'fn: read_concept_turtle{[concept_turtle, concept_list, total_concept_uuids, e] }')
        result['errors'].append({ 'errortext' : 'Error while reading concept turtle', 'error': e})
          
    try: 
        #Creating dataframes
        df_record_uuids = pd.read_csv(record_uuids, 
        sep=";",             
        dtype={ "uuid": str
           })


        df_data = pd.read_csv(data, 
            sep=",",             
            dtype={ "adamlink": str,
                   'streetTextualValue' : str,
                   'altlabel' : str,
                })

        external_df = pd.DataFrame(df_data)
        df_record_uuids = pd.DataFrame(df_record_uuids)
        concept_df = pd.DataFrame(concept_list, index=range(len(concept_list)))
        
        concept_df['normalized_street'] = concept_df["streetTextualValue"].apply(
            lambda street: normalize_street_name(street)
        )
   
        log.info(f'There are : {len(external_df)} rows in the datasheet added through commandline. \nA total of : {len(df_record_uuids)} record_uuids were added to a dataframe.\nThe list of concepts was also added to a dataframe')
        log.info(f'The streets in the concept dataframe are normalized')

    except Exception as e: 
        log.info(f'FAILED CREATING DATAFRAMES {df_record_uuids, data}')
        log.error(f'Error while creating dataframes {e}')    
        result['errors'].append({'errortext' : 'Error while creating dataframes' , 'error' : e})


    try:
        # Find street and concept_uuid by cross referencing multiple columns to eachother
        concept_df['alt_number'] = concept_df['adamlink'].str.extract(r'(\d+)')
        external_df['alt_number'] = external_df['adamlink'].str.extract(r'(\d+)')
        # Find street and concept_uuid by cross referencing multiple columns to eachother
        adamlink_lookup = build_lookup(external_df, 'adamlink', ['streetTextualValue', 'altlabel'])
        concept_uuid_lookup = build_lookup(concept_df, 'concept_uuid', ['streetTextualValue', 'normalized_street'])        
        log.info(f'Cross referencing adamlink and concept_uuid completed')

    except Exception as e: 
        log.info(f'FAILED LOOKING UP adamlink  {data, e}')
        log.error(f'Error while looking up adamlink {e}')    
        result['errors'].append({'errortext' : 'Error while looking up adamlink' , 'error' : e})

    try:
        # Build alternative names list in concept_df
        alt_number_to_names = defaultdict(list)
        for _, row in external_df.iterrows():
            num = row['alt_number']
            if pd.notna(num):
                if pd.notna(row['altlabel']):
                    alt_number_to_names[num].append(row['altlabel'])
                if pd.notna(row['streetTextualValue']):
                    alt_number_to_names[num].append(row['streetTextualValue'])

        concept_df['alternative_names'] = concept_df['alt_number'].apply(
            lambda n: alt_number_to_names.get(n, [])
        )
        log.info(f'Alternative names list build and added to concept_df')
        
    except Exception as e: 
            log.info(f'FAILED BUILDING ALTERNATIVE NAMES LIST  {data, e}')
            log.error(f'Error while building list of alternative names {e}')    
            result['errors'].append({'errortext' : 'Error while building list of alternative names' , 'error' : e})
    # Former tqdm for uuid in df loop, now a variable that returns the loop to the threadpool process

    # -----------------------------------
    # THREADPOOL FOR WORKLOAD DIVISION
    # -----------------------------------  
    uuids_to_process = df_record_uuids.head(test_amount)['uuid'].tolist()
    errors = []
    backup = []
    out = []

    with ThreadPoolExecutor(max_workers) as executor:

        # Dictionary that collects all params to run through the threadpool processor
        futures = {
            # All params that are accumulated as variables in the main process and needs to run through are process for loop
            executor.submit(
                process_one_uuid, uuid, concept_df,
                adamlink_lookup, concept_uuid_lookup, log
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
        create_csv(out_df, out_file)
    
      
if __name__ == '__main__':
    main()
