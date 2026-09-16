## Import libraries
import os 
import sys
import tracemalloc
import click
import simplejson as json
from datetime import time, datetime
from tqdm import tqdm
from uuid import uuid4
import pandas as pd
import re
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace, RDF, BNode, XSD
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
record_uuids = r"data/uuids.csv"                           #### !!!! Location of uuid from memorixalternatives = r"data/alternatives.csv",               #### !!!! Location of external csv
outliers_csv = r"data/outliers.csv"                            #### !!!! Location of output outliers
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

# Step 1 fucntie
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
    

def match_street(inst, g, uuid, predicates, total_predicates, pattern ):
 
    
    predicates.append({
          'uuid': uuid,
          'streetTextualValue': str(g.value(inst, SAA.streetTextualValue)),
          'house_number': str(g.value(inst, SAA.houseNumber)),
          'number_add': str(g.value(inst, SAA.houseNumberAddition)),
          'street' : str(g.value(inst, SAA.street))
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
    predicates_df['streetTextualValue'] = extract_pattern['street'].str.strip()
    predicates_df['extracted_number'] = extract_pattern['number'].str.strip()
    predicates_df['extracted_number_add'] = extract_pattern['add'].str.strip()

    # Normalize empty fields and replace string 'None' with empty string
    predicates_df.fillna("",inplace=True)
    predicates_df['house_number'] = predicates_df['house_number'].replace('None', '')
    predicates_df['extracted_number'] = predicates_df['extracted_number'].replace('None', '')
    predicates_df['number_add'] = predicates_df['number_add'].replace('None', '')
    predicates_df['extracted_number_add'] = predicates_df['extracted_number_add'].replace('None', '')
    
    total_predicates += 1

    return predicates_df, predicates_df['streetTextualValue'], predicates_df['street'], predicates_df['house_number'], predicates_df['number_add']

def outliers_to_csv(predicates_df):

    print(f'Predicates: \n{predicates_df}')
    # Outliers to dataframe based on index predicates
    outliers_df = pd.DataFrame( index=predicates_df.index)

    # Take uuid from predicates
    outliers_df['uuid'] = predicates_df['uuid']

    # Fill numbers etc where deviant
    street_map = {
                  'house_number': 'extracted_number',
                  'number_add': 'extracted_number_add',
                  'uuid' : 'uuid'
    }
        
    for target, source in street_map.items():

        # mask to fill empty fields 
        mask_fill = (
            predicates_df[target].isna() &
            predicates_df[source].notna()
        )
        predicates_df.loc[mask_fill, target] = predicates_df.loc[mask_fill, source]

        # Write to outliers if data already exists
        mask_to_csv = (
            predicates_df[target].notna() &
            predicates_df[source].notna() &
            (predicates_df[target] != predicates_df[source])
        )
        outliers_df.loc[mask_to_csv, target] = predicates_df.loc[mask_to_csv, source]
 
    # List alternative writings to outliers based on 'uuid'
    merge_concepts = outliers_df.merge(predicates_df[['uuid', 'alternative_names']], on = 'uuid', how='left' )
    outliers_df = merge_concepts

    #predicates_dict = predicates_df.to_dict
    #print(f'outliers: \n{outliers_df}')
    #input('pause')
    #outliers.append(predicates_dict)
    #print(predicates_df)
    #print(outliers)

    return outliers_df


# Step 3 function 
def match_concept(concept_df, df_external_data, predicates_df):
             
    # Add concept uuid and adamlink to predicates dataframe based on 'street' with a merge         
    merge_concepts = predicates_df.merge(concept_df[['streetTextualValue', 'concept_uuid', 'adamlink']], on = 'streetTextualValue', how='left' )
    predicates_df = merge_concepts

    # Remove altlabel from adammlink and add to column in two dataframes 
    predicates_df['altlabel'] = predicates_df['adamlink'].str.extract(r'(\d+)')
    df_external_data['number_altlabel'] = df_external_data['straat-label-altlabel'].str.extract(r'(\d+)')
    
    # Compare number altlabel between dataframes and add to a list
    def find_alternatives(row, df_external_data):    
                
        if pd.notna(row['altlabel']):
            
            # Find all rows in the alternatives dataframe with the same number
            number_to_match = row['altlabel']
            
            alternatives = df_external_data[df_external_data['number_altlabel'] == number_to_match]
            return alternatives['straat-label-altlabel'].tolist()  # Return all matching alternatives
        return []

    # Add list alternative writings to predicates dataframe
    predicates_df['alternative_names'] = predicates_df.apply(find_alternatives, axis=1, args=[df_external_data])
    

    #predicates_dict = predicates_df.to_dict
    outliers_df = outliers_to_csv(predicates_df)

    return predicates_df, outliers_df, predicates_df['concept_uuid'], predicates_df['adamlink']

def main():

    print('----------------------------------------------------------------------------\n\n' + f"\t\t\"OMGEVING:\n\n\t\t\t'{env}'\"\n" ) 
    input('\t\"Starten met ophalen van de data?\": (Y/N) \n' + '\n----------------------------------------------------------------------------\n\n')

    count = 0
    g = Graph()

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
        

    try: 
        #Creating dataframes
        df_record_uuids = pd.read_csv(record_uuids, 
        sep=";",             
        dtype={ "uuid": str
           })


        df_data = pd.read_csv(data, 
            sep=";",             
            dtype={ "straat-label-altlabel": str
                })

        df_external_data = pd.DataFrame(df_data)
        df_record_uuids = pd.DataFrame(df_record_uuids)
        concept_df = pd.DataFrame(concept_list, index=range(len(concept_list)))
        
        log.info(f'CREATED DATAFRAMES {df_record_uuids, data}')
        
        print('\n----------------------------------------------------------------------------\n\n' + f"\tGereed. Er zijn {len(df_external_data)} rijen opgehaald uit de externe datasheet {data}.\n" + f"\tEn {len(df_record_uuids)} uuids in een dataframe gestopt.\n" '''+ '\n----------------------------------------------------------------------------\n\n',''')
        input('\t\"Starten met ophalen van de data?\": (Y/N) \n' + '\n----------------------------------------------------------------------------\n\n')

    except: 
        log.info(f'FAILED CREATING DATAFRAMES {df_record_uuids, data}')
    
        
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
                    logging.error(f"Reading failed for {row.uuid}")
                    errors.append(("Record does not exist",row))
                    continue

            # load the graph
            g = Graph()
            turtle = g.parse(data= response.text, format='turtle')       

            for inst in g.objects(None, SAA.isAssociatedWithModernAddress): 

                predicates_df, _, _, _, _ = match_street(inst, g, uuid, predicates, total_predicates, pattern)
                predicates_df, outliers_df, _, _ = match_concept(concept_df, df_external_data, predicates_df)
                
                # Extract SCALAR values from the (single-row) DataFrame
                street_text_val = predicates_df['streetTextualValue'].iloc[0]
                street_val = predicates_df['street'].iloc[0]                
                house_number_val = predicates_df['house_number'].notna().iloc[0]
                number_add_val = predicates_df['number_add'].notna().iloc[0]
                concept_uuid_val = predicates_df['concept_uuid'].iloc[0]
                adamlink_val = predicates_df['adamlink'].iloc[0]

                # Determine Record and adamlink URI
                record_uri = URIRef(f"{PREFIX}/resources/records/{row.uuid}")
                adamlink_uri = URIRef(adamlink_val)

                address = g.objects(
                record_uri, 
                SAA.isAssociatedWithModernAddress
                    )
                #g.parse(r'data/records/' + f'record {count}.ttl', format='turtle') 
                #turtle_changed = False
                print(outliers_df)
                dict = outliers_df.to_dict()
                outliers.append(dict)
                print(f'outliers: \n{outliers}')
                #input('pause')
                '''print(record_uri)
                print(record_uri in set(g.subjects(RDF.type, MEMORIX.Record)))
                print(row.adamlink)'''          

                # Add concept URI to rrq:street if empty
                if street_val == '' or street_val == 'None':
                    if pd.notna(concept_uuid_val) and concept_uuid_val != '':
                        concept_uri = URIRef(f"{PREFIX}/resources/vocabularies/concepts/{concept_uuid_val}")
                        g.add((inst, SAA.street, concept_uri))
                        turtle_changed = True
                        log.info(f"Filled concept for street '{street_text_val}', uuid {uuid}, concept {concept_uuid_val}")
                    else:
                        log.warning(f"No concept match found for street '{street_text_val}', uuid {uuid}")
                else:
                    log.info(f"Street already filled for uuid {uuid}")
                    log.error(f'Concept already filled for uuid: {concept_uuid_val}')  
                # Change street to stripped version without additions  
                 # 2. Replace streetTextualValue (always filled, always change)
                g.remove((inst, SAA.streetTextualValue, None))
                g.add((inst, SAA.streetTextualValue, Literal(street_text_val)))
                turtle_changed = True   

                # 3. Fill houseNumber only if empty
                if house_number_val == '' or house_number_val == 'None':
                    extracted_num = predicates_df['extracted_number'].iloc[0]
                    if extracted_num and extracted_num != '':
                        g.add((inst, SAA.houseNumber, Literal(extracted_num)))
                        turtle_changed = True
                else:
                    log.info(f"HouseNumber not changed for uuid {uuid}")    

                # 4. Fill houseNumberAddition only if empty
                if number_add_val == '' or number_add_val == 'None':
                    extracted_add = predicates_df['extracted_number_add'].iloc[0]
                    if extracted_add and extracted_add != '':
                        g.add((inst, SAA.houseNumberAddition, Literal(extracted_add)))
                        turtle_changed = True
                else:
                    log.info(f"HouseNumberAddition not changed for uuid {uuid}")

            if turtle_changed:
                serialized = g.serialize(format="turtle")
                with open(f'data/records/record_{count}.ttl', 'w', encoding='utf-8') as f:
                    f.write(serialized) 
                log.info(f"Turtle changed and saved for uuid {uuid}")

        except Exception as e:
            logging.error(f"FAILED TRANSFORMATION {predicates_df} error = {e}")
            errors.append(("ERROR Main fn", [row, e]))
            log.info(f"DEBUG streetTextualValue: {repr(predicates_df['streetTextualValue'].iloc[0])}")
            log.info(f"DEBUG location_link before extract: {predicates_df['adamlink'].iloc[0]}")

    try: 
        out_df = pd.DataFrame(outliers) 
        out_df.to_csv(outliers_csv, index=False)
        log.info(f'Createrd a csv with all the data that did not match or needs attendance at: {outliers_csv} ')
    
    except Exception as e:
        logging.error(f"FAILED creating outl_df {outliers} error = {e}")
        errors.append(("ERROR creating out_df ",[outliers]))


if __name__ == '__main__':
    main()