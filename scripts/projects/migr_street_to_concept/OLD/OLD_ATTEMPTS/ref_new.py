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
   Script for exporting data from Memorix through various channels with help of
   various other scripts, one external data_document and with use of the Memorix API.
   Scripts used are: 
   streets.py
   conceptlist_turtle_to_excel.ipynb
      
   * External document used in this script can be altered.
   * Scripts can be altered for various purposes.
   * Click commands can be reduced or expanded 
   
   #### !!!! Alteration options mentioned like this  

   This script does in order:  \\# ADJUST THESE WHEN ALL FUNCTIONS ARE DONE CREATING!!!!!!!!! 

   1) Retrieve deed turtle for definition from Memorix
   2) Retrieve total concept vocabulaire turtle from Memorix 
   3) Retrieve UUID's from Memorix based on turtle from step 1
   4) Alter concept turtle from step 2 to an excel sheet
   5) Read external document and define columns
   6) Iterate through uuid's from step 3 and retrieve info from Memorix
   7) 
   Export UUID's from Memorix using APi. Use these to get information from Memorix. 
   Alter this information. Upload this information back to Memorix.
   
   Call script with CLI and the environment option:

   'python this_script.py pipeline --env [specify tst /acc /prod] data_to_be_used.ext'
'''

# Script variables
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
logfile = f'logs/refactoring {str(current_datetime)}.log'
errors = []
outliers = []
concept_list =  []
total_concept_uuids = []
test_amount = 100
total_predicates = 0

# User variables
vocabulair = 'a4863c0c-d9e5-3902-831a-d0960e381a41'        #### !!!! uuid of vocabulair            
concept_turtle = r"data/concept_turtle.ttl"                #### !!!! Location of street turtle
record_uuids = r"data/uuids.csv"                    #### !!!! Location of uuid from memorixalternatives = r"data/alternatives.csv",               #### !!!! Location of external csv
outliers_csv = r"data/outliers.csv"                        #### !!!! Location of output outliers
pattern = r'^(?P<street>.*?)(?:\s+(?P<number>\d+)(?P<add>.*))?$'

# Log handler 
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(logfile, mode='w')]
)
log = logging.getLogger()

def error_logging(errors):
    
    for item in errors:

        df = pd.DataFrame(item)
        df.to_csv(
            f"data/errors.csv",
        mode="a",
        index=False
        )
        

    errors = []


#total_record_uuids = [] 

# CLI 
env = sys.argv[1]
data = sys.argv[2]

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
    

def extract_street(inst, g, uuid, predicates, total_predicates, pattern ):
    
    predicates.append({
          'uuid': uuid,
          'streetTextualValue': str(g.value(inst, SAA.streetTextualValue)),
          'house_number': str(g.value(inst, SAA.houseNumber)),
          'number_add': str(g.value(inst, SAA.houseNumberAddition)),
          'street' : str(g.value(inst, SAA.street)),
          'adamlink' : str(g.value(None, SAA.hasOrHadSubjectLocation))
    })
    
    #total_predicates += 1
    #print(total_predicates)
    
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
    
    total_predicates += 1

    return predicates_df, predicates_df.streetTextualValue, predicates_df.street, predicates_df.house_number, predicates_df.number_add, predicates_df.adamlink

def normalize_street_name(street):
    
    replacement = {
        r'\b1\b|\b1e\b|\b1ste\b': "Eerste",
        r'\b2\b|\b2e\b|\b2de\b' : "Tweede",
        r'\b3\b|\b3e\b|\b3de\b': "Derde",
        r'\b4\b|\b4e\b|\b4de\b': "Vierde"
    }

    # Remove punctuation
    street = re.sub(r'[^\w\s]', '', street)

    # Normalize abbreviations for numbered streets 
    for pattern, replacement in replacement.items():
        street = re.sub(pattern, replacement, street) 

        '''#print(f'This is the normalized:\n{normalized}')'''

    # Extra whitespace removal
    street = ' '.join(street.split())
    """#print(f'{message}:\n{street}')
    #input('pauze')"""
    return street

def fuzzy_match(query, candidates, threshold=0.95):

    best_match = None
    best_ratio = 0
    for candidate in candidates:
        if pd.notna(candidate) and isinstance(candidate, str):
            ratio = fuzz.ratio(query, candidate) / 100
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = candidate
    if best_ratio >= threshold:
        return best_match
    
    return None

def get_fuzzy_adamlink(street, adamlink_to_streets, threshold=0.85):
    for adamlink, candidates in adamlink_to_streets.items():
        match = fuzzy_match(street, candidates, threshold)
        if match is not None:
            return adamlink
    return None


def find_concept_uuid(concept_df, predicates_df):

    # map all concept_uuids to streetnames
    all_street_names = []
    for _, row in concept_df.iterrows():
        concept_uuid = str(row['concept_uuid'])
        #print(f'I\m the uuid: {concept_uuid}')
        if pd.notna(concept_uuid):
            conventional = row['streetTextualValue']
            alternative_column = row['normalized_street']
            if pd.notna(conventional) and isinstance(conventional, str):
                all_street_names.append((conventional, concept_uuid))
            if pd.notna(alternative_column):
                if isinstance(alternative_column, str):
                    all_street_names.append((alternative_column, concept_uuid))
                elif isinstance(alternative_column, (list, tuple, set)):
                    for alt in alternative_column:
                        if pd.notna(alt) and isinstance(alt, str):
                            all_street_names.append((alt, concept_uuid))

    # Group all street names by their concept_uuid
    concept_uuid_to_street = defaultdict(list)
    for street, concept_uuid in all_street_names:
        concept_uuid_to_street[concept_uuid].append(street)
            
    # apply new column to predicates df with concept_uuid based on match in streetTextualValue with fuzzymatch applied
    predicates_df['new_concept_uuid'] = predicates_df['streetTextualValue'].apply(
        lambda s: get_fuzzy_adamlink(s, concept_uuid_to_street, threshold=0.95)
    )
    
    # apply new column to predicates df with concept_uuid based on match in normalized_street  with fuzzymatch applied
    second_column = 'normalized_street'
    mask = predicates_df['new_concept_uuid'].isna()
    predicates_df.loc[mask, 'new_concept_uuid'] = predicates_df.loc[mask, second_column].apply(
    lambda s: get_fuzzy_adamlink(s, concept_uuid_to_street, threshold=0.95)
    )
    

    return concept_df, predicates_df, predicates_df['new_concept_uuid']

def find_adamlink(predicates_df, external_df):

    # map all adamlinks to streetnames
    all_street_names = []
    for _, row in external_df.iterrows():
        adamlink = row['adamlink']
        if pd.notna(adamlink):
            conventional = row['streetTextualValue']
            alternative = row['altlabel']
            if pd.notna(conventional) and isinstance(conventional, str):
                all_street_names.append((conventional, adamlink))
            if pd.notna(alternative):
                if isinstance(alternative, str):
                    all_street_names.append((alternative, adamlink))
                elif isinstance(alternative, (list, tuple, set)):
                    for alt in alternative:
                        if pd.notna(alt) and isinstance(alt, str):
                            all_street_names.append((alt, adamlink))

    # Group all street names by their adamlink
    adamlink_to_streets = defaultdict(list)
    for street, adamlink in all_street_names:
        adamlink_to_streets[adamlink].append(street)
  

    # apply new column to predicates df with adamlink based on match in streetTextualValue  with fuzzymatch applied
    predicates_df['new_adamlink'] = predicates_df['streetTextualValue'].apply(
        lambda s: get_fuzzy_adamlink(s, adamlink_to_streets, threshold=0.95)
    )

    # apply new column to predicates df with adamlink based on match in normalized_street  with fuzzymatch applied
    second_column = 'normalized_street'
    mask = predicates_df['new_adamlink'].isna()
    predicates_df.loc[mask, 'new_adamlink'] = predicates_df.loc[mask, second_column].apply(
    lambda s: get_fuzzy_adamlink(s, adamlink_to_streets, threshold=0.95)
    )

    return predicates_df
   

def add_adamlink_location_number(predicates_df, concept_df, external_df):

    # Remove number from adammlink and add to column in three dataframes 
    concept_df['alt_number'] = concept_df['adamlink'].str.extract(r'(\d+)') 
    external_df['alt_number'] = external_df['adamlink'].str.extract(r'(\d+)')
    predicates_df['alt_number'] = predicates_df['new_adamlink'].str.extract(r'(\d+)')

    # Compare number altlabel between dataframes and add to a list
    def find_alternatives(row, external_df):    
                
        if pd.notna(row['alt_number']):
            
            # Find all rows in the alternatives dataframe with the same number
            number_to_match = row['alt_number']
            
            alternatives = external_df[external_df['alt_number'] == number_to_match]
            altlabel = alternatives['altlabel'].tolist()
            label = alternatives['streetTextualValue'].tolist()
            merged_labels = altlabel + label
             
            return merged_labels  # Return all matching alternatives
        return []

    # Add list alternative writings to predicates dataframe
    concept_df['alternative_names'] = concept_df.apply(find_alternatives, axis=1, args=[external_df])
    #print(concept_df['alternative_names'])
    
    return concept_df,  predicates_df

def merge_dataframes(concept_df, predicates_df):
    #print('I get in at merge')
    
    
    #print()
    merge_dfs = predicates_df.merge(concept_df[['alt_number', 'concept_uuid', 'alternative_names']], on = 'alt_number', how='left')
    new_merge = merge_dfs.drop_duplicates(subset=['uuid'])
        
    #print(merge_dfs)
        
    predicates_df = new_merge
   #retrieved_concept_uuid = (predicates_df['concept_uuid'] == "" or None) & predicates_df['new_concept_uuid'].notna() 
    #predicates_df.loc[retrieved_concept_uuid, 'retrieved_concept_uuid'] = predicates_df.loc[retrieved_concept_uuid, 'concept_uuid']

    #print(predicates_df)

    return new_merge, predicates_df

def outliers_to_csv(new_merge, first):

    print(f'I am the merge df : \n {new_merge}')
    # Outliers to dataframe based on index predicates
    outliers_df = pd.DataFrame( index=new_merge.index)
    outliers_df['uuid'] = new_merge['uuid']
    print(f'I am the outliers df: \n {outliers_df}')
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
        print(outliers_df)
        # Write to outliers if data already exists
        mask_to_csv = (
            new_merge[target].notna() &
            new_merge[source].notna() &
            (new_merge[target] != new_merge[source])
        )
        outliers_df.loc[mask_to_csv, target] = new_merge.loc[mask_to_csv, source]

    
        '''concept_map = {
                        'new_concept_uuid' : 'new_concept_uuid',
                        'concept_uuid' : 'concept_uuid'
        }

        for target, source in concept_map.items():

            mask_concept_to_csv = (
                    new_merge[target] == ""  &
                    new_merge[source] == "" or 
                    (new_merge[target].isna() &
                    new_merge[source].isna())
                )
            outliers_df.loc[mask_concept_to_csv, target] = new_merge.loc[mask_concept_to_csv, source]'''
            #no_concept = merge_dfs['concept_uuid'] == 'None' or merge_dfs['concept_uuid'] == '' & (merge_dfs['new_concept_uuid'] == "" or merge_dfs['new_concept_uuid'] == 'None')
        #print(no_concept)
        # List alternative writings to outliers based on 'uuid'''
        merge_concepts = outliers_df.merge(new_merge[['uuid', 'alternative_names']], on = 'uuid', how='left' )
        outliers_df = merge_concepts
        print(f' I am the outliers_df: \n {outliers_df}')
        #print(outliers_df)
        #predicates_dict = predicates_df.to_dict
        #print(f'outliers: \n{outliers_df}')
        #input('pause')
        #outliers.append(predicates_dict)
        #print(predicates_df)
        #print(outliers)
    outliers_df.to_csv(
        f"data/outliers.csv",
        mode="w" if first else "a",
        header=first,
        index=False
        
    )
    first = False
    print('I am trying to write something')

    return outliers_df, first


'''# Step 3 function 
def match_streets(concept_df, predicates_df):

    
    
    # Add concept uuid and adamlink to predicates dataframe based on 'street' with a merge         
    
    

    #predicates_dict = predicates_df.to_dict
    outliers_df = outliers_to_csv(predicates_df)

    return predicates_df, outliers_df, predicates_df['concept_uuid'], predicates_df['adamlink']'''

def main():

    print('----------------------------------------------------------------------------\n\n' + f"\t\t\"OMGEVING:\n\n\t\t\t'{env}'\"\n" ) 
    input('\t\"Starten met ophalen van de data?\": (Y/N) \n' + '\n----------------------------------------------------------------------------\n\n')

    count = 0
    g = Graph()
    first = True

    try: 
        # Read concept turtle and put in list
        g.parse(concept_turtle, format='turtle') 
        turtle_changed = False

        for s in g.subjects(rdflib.RDF.type, SKOS.Concept):
            s_str = str(s)
    
            concept_list, total_concept_uuids = read_concept_turtle(s, g, s_str) 

        
        print('\n----------------------------------------------------------------------------\n\n' + f"\tGereed. Er zijn {len(concept_list)} concepten naar een lijst geschreven\'\'\n" + f'\tWe hebben \'{len(total_concept_uuids)}\' concepten uit memorix gehaald. \'\'\n' + f'\tEr zijn {len(concept_list) - len(total_concept_uuids)} concepten verloren gegaan bij het uitlezen van de data\'\'\n' )
        input('\t\"Verder met maken van de dataframes?\": (Y/N) \n' + '\n----------------------------------------------------------------------------\n\n')
        log.info(f'Concept turtle put in list with a total of {len(total_concept_uuids)} concepts')   

    except Exception as e:
        log.info(f'Reading the concept turtle failed {e}')
        log.error(f'fn: read_concept_turtle{[concept_turtle, concept_list, total_concept_uuids, e] }')
        errors.append(('Error while reading concept turtle', e))
        error_logging(errors)
        

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
        print(f'I\'m coming back with the concept df normalized street {concept_df['normalized_street']}')

        print('\n----------------------------------------------------------------------------\n\n' + f"\tGereed. Er zijn {len(external_df)} rijen opgehaald uit de externe datasheet {data}.\n" + f"\tEn {len(df_record_uuids)} uuids in een dataframe gestopt.\n" '''+ '\n----------------------------------------------------------------------------\n\n',''')
        input('\t\"Starten met ophalen van de data?\": (Y/N) \n' + '\n----------------------------------------------------------------------------\n\n')

    except Exception as e: 
        log.info(f'FAILED CREATING DATAFRAMES {df_record_uuids, data}')
        log.error(f'Error while creating dataframes {e}')    
        errors.append(('Error while creating dataframes' , e))
        error_logging(errors)
        
    for index, row in tqdm(df_record_uuids.head(test_amount).iterrows(), total=df_record_uuids.shape[0]):
        log.info(f"STARTING WITH UUID: {row.uuid}")
        uuid = row.uuid
        count += 1
        predicates = []

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

            for inst in g.objects(None, SAA.isAssociatedWithModernAddress): 

                predicates_df, _, _, _, _, _ = extract_street(inst, g, uuid, predicates, total_predicates, pattern)
                
                # Extract SCALAR values from the (single-row) DataFrame
                migr_street = predicates_df['extracted_street'].iloc[0]
                street_val = predicates_df['street'].iloc[0]                
                house_number = predicates_df['house_number'].notna().iloc[0]
                number_add = predicates_df['number_add'].notna().iloc[0]
                adamlink = predicates_df['adamlink'].notna().iloc[0]

                """#predicates_message = 'This is the predicates street \n'"""
                predicates_df['normalized_street'] = normalize_street_name(migr_street)

                # Match street in predicates_df to all streets in external dataframe and collect the adamlink
                predicates_df = find_adamlink(predicates_df, external_df)
                #print(f'I am the concept_df uuid: \n {concept_df['concept_uuid']}')
                
                concept_df, predicates_df, _ = find_concept_uuid(concept_df, predicates_df)
                

                # Extract SCALAR values from the (single-row) DataFrame
                concept_uuid = predicates_df['new_concept_uuid'].iloc[0]

                # Get number from adamlink in all dataframes and add alternatives to list in concepts
                concept_df, predicates_df = add_adamlink_location_number(predicates_df, concept_df, external_df)
                #'''# print(f'I\'m coming back with the predicates df normalized street {predicates_df['normalized_street']}')'''


                
                
                #print(predicates_df['normalized_street'])                        

                # Merge concepts on same street
                new_merge, predicates_df = merge_dataframes(concept_df, predicates_df)
                #print(f'I am the predicates DATAFRAME: \n {predicates_df}')
                #concept_uuid = predicates_df['concept_uuid'].iloc[0]


                #same_street = (Levenshtein.ratio(str(concept_df['normalized_street']).lower(), str(predicates_df['normalized_street']).lower() > 0.95 or Levenshtein.distance(str(concept_df['normalized_street']).lower(), str(predicates_df['normalized_street']).lower()) <= 1 or str(predicates_df['altlabel']).lower() in str(concept_df['alternative_names']).lower() or str(predicates_df['normalized_street']).lower() in str(concept_df['alternative_names'])))         
                #print(same_street)

                #street_in_adamlink = (Levenshtein.ratio(str(predicates_df['normalized_street']).lower(), str(predicates_df['normalized_street']).lower()) > 0.95 or Levenshtein.distance(str(concept_df['normalized_street']).lower(), str(predicates_df['normalized_street'].lower()) <= 1 or str(predicates_df['streetTextualValue']).lower() in str(external_df['straat-label-altlabel']) or str(predicates_df['normalized_street']).lower() in str(external_df['straat-label-altlabel']))
                
                #    !!!!! @@@@@@ merge_dfs = predicates_df.merge(concept_df[['normalized_street', 'concept_uuid', 'adamlink']], on = 'normalized_street', how='left' )
 
                # Determine Record and adamlink URI
                #record_uri = URIRef(f"{PREFIX}/resources/records/{row.uuid}")
                
                # Create dictionairy and df for out_csv
                outliers_df = outliers_to_csv(new_merge, first)
                print(f'I am the outliers df : \n {outliers_df}')
                #df_list = outliers_df.to_dict()
                #outliers.append(df_list)


                # Add concept URI to saa:street if empty
                if street_val == '' or street_val == 'None':
                    if pd.notna(concept_uuid) and concept_uuid != '':
                        concept_uri = URIRef(f"{PREFIX}/resources/vocabularies/concepts/{concept_uuid}")
                        g.add((inst, SAA.street, concept_uri))
                        turtle_changed = True
                        log.info(f"UUID: {uuid} \n Changed dMigr street: '{migr_street}' to normalized street : '{predicates_df.normalized_street}'. \nFilled concept {concept_uuid} and concept street name: {concept_df['streetTextualValue']}")
                        
                    else:
                        log.warning(f"UUID: {uuid} \nNo concept match found for street '{migr_street}'")
                        errors.append(('No concept match found ', row))
                        error_logging(errors)
                else:
                    log.info(f"Street already filled for uuid {uuid}")
                    log.error(f'Concept already filled for uuid: {concept_uuid}')  
                    errors.append(('Concept already filled', row))
                    error_logging(errors)
                # Change street to stripped version without additions  

                # 3. Fill houseNumber only if empty
                if house_number == '' or house_number == 'None':
                    extracted_number = predicates_df['extracted_number'].iloc[0]
                    if extracted_number and extracted_number != '':
                        g.add((inst, SAA.houseNumber, Literal(extracted_number)))
                        turtle_changed = True
                        
                else:
                    log.info(f"HouseNumber not changed for uuid {uuid}")    

                # 4. Fill houseNumberAddition only if empty
                if number_add == '' or number_add == 'None':
                    extracted_add = predicates_df['extracted_add'].iloc[0]
                    if extracted_add and extracted_add != '':
                        g.add((inst, SAA.houseNumberAddition, Literal(extracted_add)))
                        turtle_changed = True
                        
                else:
                    log.info(f"HouseNumberAddition not changed for uuid {uuid}")

            if turtle_changed:
                turtle = g.serialize(format="turtle")
                response = api.update_record(row.uuid, turtle)
                if response.status_code == 200:            
                    log.info(f"SUCCEED {row.uuid}")     
                else:            
                    log.error(f"UPDATE FAILED:  {row.uuid}")
                    errors.append(('Update failed for uuid', [row.uuid, response.text]))
                    error_logging(errors)
                '''with open(f'data/records/record_{count}.ttl', 'w', encoding='utf-8') as f:
                    f.write(turtle)''' 
                log.info(f"Turtle changed and saved for uuid {uuid}")


        except Exception as e:
            log.error(f"FAILED TRANSFORMATION {row} error = {e}")
            errors.append(("ERROR Main fn, failing tranformation or upload", [e, row]))
            error_logging(errors)
            log.info(f"DEBUG streetTextualValue: {repr(predicates_df['streetTextualValue'].iloc[0])}")
            #log.info(f"DEBUG location_link before extract: {merge_dfs['adamlink'].iloc[0]}")

    '''try: 
        out_df = pd.DataFrame(outliers) 
        out_df.to_csv(outliers_csv)
        
        result = pd.DataFrame(errors, index=False)
        result.to_csv(errors_csv)
        log.info(f'Createrd a csv with all the data that did not match or needs attendance at: {outliers_csv} ')
    
    except Exception as e:
        logging.info(f"FAILED creating outl_df {out_df, e}")
        errors.append('Failed creating dataframe', e)'''


if __name__ == '__main__':
    main()
