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
from concurrent.futures import ThreadPoolExecutor, as_completed
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs")
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
project_name = 'rename_file_to_output'  
source_file = Path(HOME_REPO,'data',project_name, 'source', f'backup_{env}.csv')   #### !!!! Location of uuid from memorix                                        #### !!!! State project name for data collection in file, logs and data folder     
turtle = Path(HOME_REPO,'data','turtle', f'rename_file_to_output.ttl')   #### !!!! Location ofturtle
backup = []
errors = []
out = []
test_amount = 20000
max_workers= 8
retry_attempts = 3
pattern = r'^10163/(\d+)$'

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

    out_df = pd.DataFrame(df)

    df.to_csv(
            out_file,
            mode="a",
            index=False
            )
    
    return 

def change_identifier(df):

    mask = df['identifier'].notna()
    extracted = df.loc[mask, 'identifier'].str.extract(r'^10163/(\d+)')[0]
    df.loc[mask, 'new_identifier'] = extracted
    print(df['new_identifier'])

    return df


def process_one_uuid(df, row, log):                          

    uuid = row['uuid']

    result = {
        'uuid': uuid,
        'errors': [],       
        'backup_rows' : [], 
        'out_rows' : [], 
        'status': 'ok',
    }    

    turtle_changed = False                    
     # Get Record turtle 
    response = api.get_record(uuid)
    
    if response.status_code != 200:
        time.sleep(3)
        response = api.get_record(uuid)
        if response.status_code != 200:
            log.error(f"Reading failed for {uuid}")
            log.error({'errortext': "Record does not exist", 'uuid': uuid})
            result['errors'].append({'errortext': 'failed for uuid', 'uuid': uuid, 'error': response.text})
            result['status'] = 'failed'
            return result
     
    # load the graph
    g = Graph()
    turtle = g.parse(data=response.text, format='turtle')  
                 
    record = URIRef(f"{PREFIX}/resources/records/{uuid}")
     
    for record in g.subjects(RDF.type, MEMORIX.Record):

        #identifier = df['identifier'].iloc[0]
        #row = df.loc[df['new_identifier'] == uuid]
        #df, _, _ = change_identifier(df)
        
        data_changed = row['new_identifier']

        new_identifier = row['new_identifier']
        print(new_identifier and data_changed)

        #old_identifier = str(g.value(record, RICO.identifier))
        #not_same = str(new_identifier) == old_identifier
        #print(not_same)
            

        if pd.notna(data_changed) :
            g.remove((record, RICO.identifier, None))  
            changed_identifier = g.add((record, RICO.identifier, Literal(new_identifier)))
            turtle_changed = True     
            log.info('data changed')  
     
        try:
            if turtle_changed:
                turtle = g.serialize(format="turtle")
                response = api.update_record(uuid, turtle)
                if response.status_code == 200:            
                    log.info(f"Turtle succesfully updated for row: {uuid}")  
                    if response.status_code != 200:
                        time.sleep(3)
                        #response = api.get_record(uuid)
                        if response.status_code != 200:
                            log.error(f"Updating failed for {uuid}")
     
            else:           
                log.error(f"Turtle NOT updated for row:  {uuid}")
                

        except Exception as e:
            log.info(f'Failed filtering noise on the date : {e}', exc_info=True) 
            log.error(f'Error while filtering noise {type(e).__name__, e}') 
            template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
            message = template.format(type(e).__name__, e.args)
            print(message)
    
    return result


def main():

    errors = []
    backup = []
    attempts = []
    retried = []
    out = []
    start_time = time.time()
    retried = []
    attempts = []

    sys.path.append(f'{HOME_REPO}/saa/scripts')
    from general import file_and_log_management
    log, error_file, backup_file, out_file = file_and_log_management.setup_logging(env, project_name, project_name)

    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ALTER DATA NOW?\": (Y/N)')

    df = pd.read_csv(source_file, 

        dtype={
            'uuid': str,
            'identifier' : str
            
            },
            delimiter=';')

    try:
        df = change_identifier(df)
        file_and_log_management.create_csv(df, backup_file)
        log.info('created a dataframe and a backup')
    except Exception as e:
            log.info(f'Something went wrong with altering column fields')
            log.error({'Error while altering column data' : e})

    # -----------------------------------
    # THREADPOOL FOR WORKLOAD DIVISION
    # -----------------------------------  
    uuids_to_process = df[11565:].head(test_amount)
    #for idx, row in df.head(test_amount).iterrows():
        #uuid = row['uuid'] 
    with ThreadPoolExecutor(max_workers) as executor:
            
        # Submit all tasks with metadata for tracking
        futures = {}
        for idx, row in uuids_to_process.iterrows():
            future = executor.submit(
                process_one_uuid,
                df, row, log
            )
            futures[future] = {
                'uuid': row['uuid'],
                'row_index': idx,
                'attempts': 1
            }
    
        # All executed runs are collected in a tqdm list with the total length of the executed uuid loops [e.g. based on your test_amount then]
        for future in tqdm(as_completed(futures), total=len(futures)):
            meta = futures[future]
    
            #Setting the uuid as the identifier for each ran process in the accumulated list
            uuid = futures[future]
            try:
                # Apply a [builtin ? ] method to identify the information accumulated in the result dictionary
                result = future.result(timeout=60)  # 60s timeout per task
                log.info(f'running with uuid: {uuid}')
                if result.get('error'):
                    result['errors'].append({
                        'uuid': meta['uuid'],
                        'error': result['error'],
                        'attempts': meta['attempts']
                    })
                else:
                    attempts.append(result)

            except TimeoutError:
                result['errors'].append({
                    'uuid': meta['uuid'],
                    'error': 'TIMEOUT',
                    'attempts': meta['attempts']
                })

            except Exception as e:
                # Retry logic for transient failures
                if meta['attempts'] < retry_attempts:
                    meta['attempts'] += 1
                    
                    # Resubmit with backoff
                    time.sleep(min(2 ** meta['attempts'], 10))
                    retried.append(meta['uuid'])
                    
                    new_future = executor.submit(
                        process_one_uuid,
                        df, meta['uuid'], log
                    )
                    futures[new_future] = meta
                    
                else:
                    errors.append({
                        'uuid': meta['uuid'],
                        'error': str(e),
                        'attempts': meta['attempts']
                    })
                # this only fires if process_one_uuid itself crashed unexpectedly
                
                errors.append({'errortext': f'Can not find uuid after {retry_attempts} retries', 'uuid': uuid, 'error': str(e)})
                template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
                message = template.format(type(e).__name__, e.args)
                log.error(f"Unhandled exception for uuid {uuid} with error: {e} - {message}")
                continue
    
            # merge the identified uuid's result into the shared lists 
            # this code only ever runs in the main thread, one future at a time
            errors.extend(result['errors'])
            backup.extend(result['backup_rows'])
            out.extend(result['out_rows'])
    
    # write CSVs once, after everything is done
    elapsed = time.time() - start_time
    file_and_log_management.create_csv(errors, error_file)
    if backup:
        backup_df = pd.DataFrame(backup)
        backup_df.to_csv(backup_file, mode="w", index=False)
        file_and_log_management.create_csv(backup_df, backup_file)
    '''if out:
        out_df = pd.concat(out, ignore_index=True)
        out_df.to_csv(out_file, mode="w", index=False)
        file_and_log_management.create_csv(out_df, out_file)'''
    # -------------------------------------------------------
    # OUTPUT SUMMARY & AUDIT TRAIL
    # -------------------------------------------------------
    report = {
        'total_submitted': len(uuids_to_process),
        'successful': len(attempts),
        'failed_permanent': len(errors),
        'retried': len(retried),
        'success_rate': f"{len(attempts)/len(uuids_to_process)*100:.1f}%" if uuids_to_process.size else 0,
        'elapsed_seconds': round(elapsed, 2),
        'avg_per_second': round(len(attempts)/elapsed, 1) if elapsed > 0 else 0
    }
    print(f"\n{'='*60}")
    print("THREADPOOL EXECUTION REPORT")
    print(f"{'='*60}")
    print(f"  Submitted:        {report['total_submitted']}")
    print(f"  Successful:       {report['successful']}")
    print(f"  Failed:           {report['failed_permanent']}")
    print(f"  Retried:          {report['retried']}")
    print(f"  Success Rate:     {report['success_rate']}")
    print(f"  Elapsed Time:     {report['elapsed_seconds']}s ({report['avg_per_second']} req/sec)")
    print(f"{'='*60}")
    # Export error log for investigation
    if errors:
        errors_df = pd.DataFrame(errors)
        errors_df.to_csv('threadpool_errors.csv', index=False)
        print(f"\n Errors exported to: threadpool_errors.csv")
        # Show top 5 error types
        print("\nTop errors:")
        error_counts = errors_df['error'].value_counts().head(5)
        for err, count in error_counts.items():
            print(f"   {err}: {count}")
    # Export successful results
    if attempts:
        results_df = pd.DataFrame(attempts)
        results_df.to_csv('threadpool_results.csv', index=False)
        print(f"✓ Results exported to: threadpool_results.csv")
    # Return for downstream use
    
        
if __name__ == '__main__':
    main()