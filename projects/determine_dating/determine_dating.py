## Import libraries
import os 
import sys
from datetime import time, datetime
from tqdm import tqdm
import pandas as pd
import re
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace, BNode, RDF, XSD
from collections import defaultdict
import logging
from rapidfuzz import process, fuzz
from pathlib import Path
import time
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
PREFIX = 'stadsarchief'


# 182
# 1452
# 1452[\s+] -[\s+]  1453
# 1452 (circa)
# 1452 (circa) 1453 (circa)
# 1452, 1453, 1452 - 1453
# 1452 (ca)
# 1452 (ca.)
# 14e eeuws
# ?
# [1452]
# [s.d.]
# augustus 1452 - juli 1453
# ca. 1452 (1 charter)
# ca. 1452
# ca. 14e [\s+] - [\s+] 15e eeuw
# ca. 1452
# ca. 14e eeuw
# ca. 1452 [\s+ - [\s+] 1453
# ca. 1452 ca. 1452
# Circa 1452
# Circa 1452 [\s+ - [\s+] circa 1452
# datum onbekend
# jan [\s+ - [\s+] 05-1452  
# Niet gedateerd
# onbekend
# s.d.
# september 1452
# z.d.
# z.j.
# zonder datum 
# zonder jaar


######### vier jaren = onbekend
# 1452, 1453, 1452 - 1453

######### maand jaar maand jaar
# augustus 1452 - juli 1453

######### jaar maand jaar
# 1452 - juli 1453

    
############## tussen twee jaren
# 1452[\s+] -[\s+]  1453
# 1452 (circa) 1453 (circa)
# ca. 1452 [\s+ - [\s+] 1453
# ca. 1452 ca. 1452
# 1452 t/m 1453
# Circa 1452 [\s+ - [\s+] circa 1452

####### maand kortjaar maand jaar ########

# januari 52 juli 1452


######### maand jaar
# september 1452

############### decennium ############

# Circa 1980
# 1980 circa


###### eeuwen 
# ca. 14e [\s+] - [\s+] 15e eeuw
# 14e eeuws
# ca. 14e eeuw
# 14e eeuws

############# enkele jaartallen
# ca. 1452
# 1452 (circa)
# 1452 (ca)
# 1452 (ca.)
# [1452]
# Circa 1452
# ca. 1452 (1 charter)
# ca. 1452
# 1452

############### onbekend #############

# ?
# Niet gedateerd
# [s.d.]
# onbekend
# s.d.
# 182
# z.d.
# z.j.
# zonder datum 
# datum onbekend
# zonder jaar
# 1 omslag 



'''
   Script for filling dates based on migration date information to conformity being: 
   - specific date when mentioned
   - 1st of january to 31st of december when year is mentioned
   - 1st of january to 31st of december to range of years when range of years is mentioned
   - Decade of archive when date unknown / without year
   - 2 centuries when 3 numbers are 

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
project_name = 'determine_dating'                 
record_uuids = sys.argv[2] if len(sys.argv) > 2 else Path(HOME_REPO,'data',project_name, 'source', f'record_uuids_{env}.csv') 

current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
vocabulair = 'a4863c0c-d9e5-3902-831a-d0960e381a41'        #### !!!! uuid of vocabulair 
pattern = r'^(?P<street>.*?)(?:\s+(?P<number>\d+)(?P<add>.*))?$'
test_amount = 4000
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
#XSD = Namespace('https://www.w3.org/2001/XMLSchema#')
SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")

# -----------------------------------
# FUNCTIONS
# -----------------------------------  
# Function to remove all noice and convert text to string-numbers
def filter_noise(date):
    
    replacement = {
        r'\]|\[|\(|\)|': "",
        r'(?!)\bcirca|\bca\b' : "",
        r'\.': "",
        r'\bjanuari|jan\b': "01",
        r'\bfebruari|feb\b': "02",
        r'\bmaart|mrt\b' : "03",
        r'\bapril|apr\b' : '04',
        r'\bmei\b' : '05',
        r'\bjuni|jun\b' : '06',
        r'\bjuli|jul\b' : '07',
        r'\baugustus|aug\b' : '08',
        r'\bseptember|sep\b' : '09',
        r'\boktober|okt\b' : '10',
        r'\bnovember|nov\b' : '11',
        r'\bdecember|dec\b' : '12',
        r'^t\s*\\\s*m$' : '',
        r'b\t\\m\b' : ''
    }

    # Normalize abbreviations for numbered streets 
    for pattern, replacement in replacement.items():
        date = re.sub(pattern, replacement, date) 
    
    # Extra whitespace removal
    date = ' '.join(date.split()).lower()
    
    return date

# Function to determine correct end day to end the month
# according to the month in question
def determine_day(mnth):

    day = None
    end_of_month = {
        '31' : ['01', '03','05','07','08','10','12' ], 
        '28' : ['02'],
        '30' : ['04', '06', '09', '11']
    }

    for k, v in end_of_month.items():
        for d in end_of_month[k]:
            if d == mnth:
                day = k
                break
    
    return day

def get_date(date, df, log):
    
    
    start_date = pd.to_datetime(df['start']).dt.strftime('%Y-%m-%d')
    end_date = pd.to_datetime(df['start']).dt.strftime('%Y-%m-%d')
    date_type = []
    tot = re.search(r'(?P<tot>\btot\b.*(?P<mnth_2>\d{2})?.*(?P<year_2>\d{4})?)', date) # tot pattern
    fy = re.search(r'(?P<year_1>\d{4}).*(?P<year_2>\d{4}).*(?P<year_3>\d{4}).*(?P<year_4>\d{4})', date) # 4 years pattern
    mymy = re.search(r'(?P<mnth_1>\d{2}).*(?P<year_1>\d{4}).*(?P<mnth_2>\d{2}).*(?P<year_2>\d{4})', date) # month year month year pattern
    ymy = re.search(r'(?i)(?P<year_1>\d{4}).*(?P<mnth_1>\d{2}).*(?P<year_2>\d{4})', date) # year month year pattern
    by = re.search(r'(?P<year_1>\d{4}).*(?P<year_2>\d{4})', date) # between years pattern
    msymy = re.search(r'(?i)^(?P<mnth_1>\d{2}).*(?P<short_year>\d{2}).*(?P<mnth_2>\d{2}).*(?P<year_2>(?P<century>\d{2})\d{2})', date)
    my = re.search(r'(?i)^(?P<mnth_1>\d{2}).*(?P<year_1>\d{4})', date) # month year pattern
    cs = re.search(r'(?P<cent_1>(?P<numb_1>\d{2})e).*(?P<cent_2>(?P<numb_2>\d{2})e)', date) # cs
    cp = re.search(r'(?P<cent_1>(?P<numb_1>\d{2})e)',date) # century pattern
    yp = re.search(r'(?P<year_1>\d{4})', date) # year patttern
    ep = re.search(r'\w?\d{0}.*', date) # ep
    
    if tot: # Date created 'until' not included
        try:
            mnth_2 = tot.group('mnth_2') != None
            year_2 = tot.group('year_2') != None
            if mnth_2:                
                mnth_2 = f'{str(int(mnth_2) -1)}'
                # Extra day test according to the month
                day = determine_day(mnth_2)
            if year_2:
                year_2 = f'{str(int(year_2) -1)}' 
            start_date = f'{tot.group('year_1')}-{tot.group('mnth_1')}-01'
            end_date = f'{year_2}-{mnth_2}-{day}'
            date_type = 'tot'
            return start_date, end_date, date_type
        except Exception as e:
            template = f"An exception of type {0} occurred. Arguments:\n{1!r}"
            message = template.format(type(e).__name__, e.args)
            log.error(message)

    if fy: # year, year year - year -> do nothing. Format unclear
        start_date = ''
        end_date = ''
        date_type = 'fy'
        log.info(f'I\'m in the fy with date{date} and startdate = {start_date} and end_date: {end_date}')
        return start_date, end_date, date_type

    if mymy: # Month year, month year -> Create date
        mnth_1 = f'{mymy.group('mnth_1')}'
        mnth_2 = f'{mymy.group('mnth_2')}'
        # Extra day test according to the month
        day = determine_day(mnth_2)
        start_date = f'{mymy.group('year_1')}-{mnth_1}-01'
        end_date = f'{mymy.group('year_2')}-{mnth_2}-{day}'
        date_type = 'mymy'
        log.info(f'I\'m in the mymy with date: {date} and startdate = {start_date} and end_date: {end_date}')
        return start_date, end_date, date_type
    if ymy: # year - month - year -> Create date
        log.info(f'I\'m in the ymy with date: {date} and startdate = {start_date} and end_date: {end_date}')
        mnth_2 = f'{ymy.group('mnth_2')}'
        # Extra day test according to the month
        day = determine_day(mnth_2)
        start_date = f'{ymy.group('year_1')}-01-01'
        end_date = f'{ymy.group('year_2')}-{ymy.group('mnth_1')}-{day}'  
        date_type = 'ymy'
        return start_date, end_date, date_type
    if by: # Between year and year -> Create date
        start_date = f'{by.group('year_1')}-01-01'
        end_date = f'{by.group('year_2')}-12-31'        
        log.info(f'I\'m in the by with date: {date} and startdate = {start_date} and end_date: {end_date}')
        date_type = 'by'
        return start_date, end_date, date_type
    if msymy: # month - shorted year - month - year -> Create date
        log.info(f'I\'m in the msymy with date: {date} and startdate = {start_date} and end_date: {end_date}')
        mnth_2 = f'{msymy.group('mnth_2')}'
        # Extra day test according to the month
        day = determine_day(mnth_2)
        # First year has a shorthand format. 
        # Determine century from second year to match the shorthand of the first
        start_date = f'{msymy.group('century')}{msymy.group('short_year')}-{msymy.group('mnth_1')}-01'
        end_date = f'{msymy.group('year_2')}-{msymy.group('mnth_2')}-{day}'
        date_type = 'msymy'
        return start_date, end_date, date_type
    if my: # Month - year -> Create date
        log.info(f'I\'m in the my with date: {date} and startdate = {start_date} and end_date: {end_date}')
        mnth_2 = f'{my.group('mnth_2')}'
        # Extra day test according to the month
        day = determine_day(mnth_2)
        start_date = f'{my.group('year_1')}-{my.group('mnth_1')}-01'
        end_date = f'{my.group('year_1')}-{my.group('mnth_1')}-{day}'  
        date_type = 'my'
        return start_date, end_date, date_type 
    if cs: # Centuries plural mentioned -> Create date
        # Substract one from the first century because you look backwards
        numb_1 = f' {str(int(cs.group('numb_1')) - 1)}' 
        # Start at year 1, not from 0
        start_date = f'{numb_1}01-01-01'
        # End the second century when the full 00 is finished
        end_date = f'{cs.group('numb_2')}00-12-31'
        log.info(f'I\'m in the cs with date: {date} and startdate = {start_date} and end_date: {end_date}')
        date_type = 'cs'
        return start_date, end_date, date_type
    if cp: # Century single mentioned -> Create date
        # Substract one from the century because you look backwards
        numb_1 = f' {str(int(cp.group('numb_1')) - 1)}'
        start_date = f'{numb_1}01-01-01'
        end_date = f'{cp.group('numb_1')}00-12-31'
        log.info(f'I\'m in the cp with date: {date} and startdate = {start_date} and end_date: {end_date}')
        date_type = 'cp'
        return start_date, end_date, date_type
    if yp:
        start_date = f'{yp.group('year_1')}-01-01'
        end_date  = f'{yp.group('year_1')}-12-31'
        log.info(f'I\'m in the yp with date: {date} and startdate = {start_date} and end_date: {end_date}')
        date_type = 'yp'
        return start_date, end_date, date_type
    if ep: 
        start_date = ''
        end_date = ''
        
        date_type = 'ep'
        return start_date, end_date, date_type
    else: 
        start_date = ''
        end_date = ''
        date_type = 'else'
        log.info(f'I\'m in the else pattern with date: {date} and startdate = {start_date} and end_date: {end_date}')
    
    return start_date, end_date, date_type


def get_turtle_data(inst, g, dates, uuid):

    dates.append({
          'uuid': uuid,
          'date': str(g.value(inst, RICO.expressedDate)),
          'start': str(g.value(inst, RICO.hasBeginningDate)),
          'end': str(g.value(inst, RICO.hasEndDate)),
    })
    
        # Turn turtle predicates to dataframe
    df = pd.DataFrame(dates)
    df = df.fillna('')
    df = df.replace('None', '')
    start = df['start']
    end = df['end']

    return df, start, end

def process_one_uuid(uuid, log):
        
    """
    Runs the full pipeline for a single uuid.
    """
    # Local lists converted to outfiles by threadpool executor
    result = {
        'uuid': uuid,
        'errors': [],       
        'backup_rows': [],  
        'out_rows': [],     
        'status': 'ok',
    }

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

        for inst in g.objects(None, RICO.isAssociatedWithDate):

            try:
                df, start, end = get_turtle_data(inst, g, dates, uuid)                
                log.info(f'Created dataframe and backup of df succesfully')
            except Exception as e:
                log.info(f'FAILED getting turtle data with  error : {e}', exc_info=True) 
                log.error(f'Error while getting turtle data {type(e).__name__, e}') 
                template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
                message = template.format(type(e).__name__, e.args)
                print(message)
                
            try:
                result['backup_rows'].append(df)
                print(df)
                log.info(f'Created backup of df succesfully')
            except Exception as e:
                log.info(f'FAILED creating backup with  error : {e}', exc_info=True) 
                log.error(f'Error while creating a backup {type(e).__name__, e}') 
                template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
                message = template.format(type(e).__name__, e.args)
                print(message)
    
            try:
                df['date'] = df['date'].apply(
                lambda x: filter_noise(x))
                log.info(f'Filtered noise on the date column')
            except Exception as e: 
                log.info(f'Failed filtering noise on the date : {e}', exc_info=True) 
                log.error(f'Error while filtering noise {type(e).__name__, e}') 
                template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
                message = template.format(type(e).__name__, e.args)
                print(message)

            try:
                df['start'], df['end'], df['type'] = zip(*df['date'].apply(
                    lambda x: get_date(x, df, log)))
                # start = df['start'].notna().iloc[0]
                # end = df['end'].notna().iloc[0]
                log.info(f'Extracted start and enddate succesfully')
            except Exception as e:
                log.info(f'Failed Extracted start and enddate with error: {e}', exc_info=True) 
                log.error(f'Error while Extracted start and enddate  {type(e).__name__, e}') 
                template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
                message = template.format(type(e).__name__, e.args)
                print(message)
            
            '''try:
                result['out_rows'].append(df)
                log.info(f'Created out_file succesfully')
            except Exception as e:
                log.info(f'Failed creating out_file with error: {e}', exc_info=True) 
                log.error(f'Error while creating out_file  {type(e).__name__, e}') 
                template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
                message = template.format(type(e).__name__, e.args)
                print(message)'''

            # start = g.value(inst, RICO.hasBeginningDate)
            # print(start)
            # end = g.value(inst, RICO.hasEndDate)
            # print(end)
            try:
                # Fill startdate if empty
                if not g.value(inst, RICO.hasBeginningDate): 
                    print(f' I am the data type : {type(df['start'])}')    
                    print (f' I am the data type : {type(df['start'].iloc[0])}') 
                    g.add((inst, RICO.hasBeginningDate, Literal(df["start"].iloc[0], datatype=XSD.date) ))
                    turtle_changed = True
                    log.info(f'Changed start date for UUID: {uuid} to  {df['start']}.')                    
                else:
                    log.warning(f'Startdate already filled for uuid: {uuid}.')

                # Fill end date only if empty     
                if not g.value(inst, RICO.hasEndDate):     
                    g.add((inst, RICO.hasEndDate, Literal(df["end"].iloc[0], datatype=XSD.date) ))
                    turtle_changed = True
                    log.info(f'Changed end date for UUID: {uuid} to  {df['end']}.')                    
                else:
                    log.warning(f'Enddate already filled for uuid: {uuid}.')
            except Exception as e:
                log.info(f'Failed changing start or end dates with error: {e}', exc_info=True) 
                log.error(f'Error while changing start or end dates   {type(e).__name__, e}') 
                template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
                message = template.format(type(e).__name__, e.args)
                log.error(message)

        if turtle_changed:
            turtle = g.serialize(format="turtle")
            result['out_rows'].append(df.copy())
            response = api.update_record(uuid, turtle)
            #print(response.text)
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
#

    except Exception as e:
        log.info(f'Failure in the script with error: {e}', exc_info=True) 
        log.error(f'Error in the script of t {type(e).__name__, e}') 
        template = f"An exception of type {0} occurred. Arguments:\n{1!r}"            
        message = template.format(type(e).__name__, e.args)
        log.error(message)
        result['errors'].append({'errortext': "ERROR Main fn, failing transformation or upload", 'uuid': uuid, 'error': str(e)})
        result['status'] = 'failed'

    return result

def main():

    sys.path.append(str(f'{HOME_REPO}/saa/scripts'))
    from general import file_and_log_management
    log, error_file, backup_file, out_file = file_and_log_management.setup_logging(env, project_name, project_name)
    
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ANALYZE DATA NOW?\": (Y/N)')

    df = pd.read_csv(record_uuids, 
        sep=";",             
        dtype={ "uuid": str,
        })
    
    log.info(f'There are : {len(df)} rows in the datasheet.')




    # -----------------------------------
    # THREADPOOL FOR WORKLOAD DIVISION
    # -----------------------------------  
    uuids_to_process = df.head(test_amount)['uuid'].tolist()
    errors = []
    backup = []
    out = []

    with ThreadPoolExecutor(max_workers) as executor:

        # Dictionary that collects all params to run through the threadpool processor
        futures = {
            # All params that are accumulated as variables in the main process and needs to run through are process for loop
            executor.submit(
                process_one_uuid, uuid,log
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
            out.extend(result['out_rows'])

    # write CSVs once, after everything is done
    file_and_log_management.create_csv(errors, error_file)
    if backup:
        backup_df = pd.concat(backup, ignore_index=True)
        print(f'I am the backup datafram: \n\n{backup_df}\n\n')
        file_and_log_management.create_csv(backup_df, backup_file)
    if out:
        out_df = pd.concat(out, ignore_index=True)
        #out_df.to_csv(out_file, mode="w", index=False)
        file_and_log_management.create_csv(out_df, out_file)
    
      
if __name__ == '__main__':
    main()
