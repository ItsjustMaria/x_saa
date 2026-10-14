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
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test/")
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
name = '' 
if not name:
    name = project_name
record_uuids = sys.argv[2] if len(sys.argv) > 2 else Path(HOME_REPO,'data',project_name, 'source', f'record_uuids_{env}.csv') 

current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
vocabulair = 'a4863c0c-d9e5-3902-831a-d0960e381a41'        #### !!!! uuid of vocabulair 
pattern = r'^(?P<street>.*?)(?:\s+(?P<number>\d+)(?P<add>.*))?$'
test_amount = 20000
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

def get_turtle_info(inst, g, uuid, predicates, pattern):
    
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
        r'b\t\\m\b' : '',
        r'\bz.j.\b|\bz.d.\b|\b\?\b|\bs.d.\b|\bzonder datum\b|\bzonder jaar\b|\bNiet gedateerd\b|\bdatum onbekend\b|\bonbekend\b|\b1 omslag\b|\b182\b' : ""
    }

    # Remove punctuation
    #date = re.sub(r'[^\w\s]', '', date)
    
    # Normalize abbreviations for numbered streets 
    for pattern, replacement in replacement.items():
        date = re.sub(pattern, replacement, date) 
    
    # Extra whitespace removal
    date = ' '.join(date.split()).lower()
    
    return date

def till_or_included():

    
    minus = str(int(r'\g<following>') - 1)

    tot_patttern = r'(?P<tot>\btot\b.*(?P<following>\d{2,4}))'
    tm_pattern = r'b\t\\m\b.*(?P<following>\d{2,4})'

    if tot_patttern:
        date = re.sub

def get_date(date, log):
    
    start_date = None
    end_date = None
    start = []
    end = []
    patterns = [r'(?P<year_1>\d{2,4}).*(?P<tot>\btot\b).*(?P<mnth_2>\d{2}).*(?P<year_2>\d{4})',
    r'(?P<year_1>\d{4}).*(?P<year_2>\d{4}).*(?P<year_3>\d{4}).*(?P<year_4>\d{4})',
    r'(?P<mnth_1>\d{2}).*(?P<year_1>\d{4}).*(?P<mnth_2>\d{2}).*(?P<year_2>\d{4})',
    r'(?i)(?P<year_1>\d{4}).*(?P<mnth_1>\d{2}).*(?P<year_2>\d{4})',
    r'(?P<year_1>\d{4}).*(?P<year_2>\d{4})', 
    r'(?i)^(?P<mnth_1>\d{2}).*(?P<short_year>\d{2}).*(?P<mnth_2>\d{1,2}).*(?P<year_2>\d{4})(?P<century>\d{2})\d{2}', 
    r'(?i)^(?P<mnth_1>\d{2}).*(?P<year_1>\d{4})', 
    r'(?P<cent_1>(?P<numb_1>\d{2})e).*(?P<cent_2>(?P<numb_2>\d{2})e)', 
    r'(?P<cent_1>(?P<numb_1>\d{2})e)',
    r'(?P<year_1>\d{4})'
    ]
    # r'(?P<words>\w?\d{0}.*)'
    '''print('I get in the pattern')
    for idx, item in enumerate(patterns):
            print(f'{idx}) \n{item}\n')'''
    #circa_pattern = re.search(r'(?i)cir?ca\.?', date)
    #decennium_pattern = re.search(r'(?i)(?=.*ci?r?c?a\.?)(?-i)(?P<decennium>\d{3}0)', date)

    for pattern_str in patterns:
        #print(f'{name}) \n{pattern_str}\n')

        match = re.search(pattern_str, date) 
        if match: 
            #print(f'Pattern {name} matched')
            
            extracted = {}
            for group in ['tot','first', 'mnth_1', 'mnth_2', 'year_1', 'year_2', 'century', 'short_year', 'cent_1', 'cent_2', 'numb_1', 'numb_2']:
                try:
                    extracted[group] = match.group(group)
                except IndexError:
                    pass

                # Calculate day           
            #days = [extracted[group] for group in extracted if group.startswith('mnth_')] # = group for group in extracted if it starts with month so either mnth_1 or mnth_2 
            ##print(days)
            ##centuries = [extracted[m] for m in extracted if m.startswith('cent_') ] # group for group in extracted if it starts with month so either cent_1 or cent_2
            #day = '30' if any(group in thirty_first for group in days) else '30'
                        
            # Build result
            one = extracted.get('numb_1') != None
            two = extracted.get('numb_2') != None
            tot = extracted.get('tot') != None
            # following = extracted.get('following') != None
            cent_1 = extracted.get('cent_1') != None
            cent_2 = extracted.get('cent_2') != None
            # print(f'one: {one} \ntwo: {two} ')

            if one: 
                cent_1 = f'{str(int(one) -1)}01' 
            if two:
                cent_2 = f'{str(int(two) -1)}00'

             

            #print(f'cent_1: {cent_1}')
            
            #cent_2 = f'{str(int(extracted.get('cent_2', 0)) -1)}00' 
            #print(f'cent_2: {cent_2}')
            mnth_1 = extracted.get('mnth_1', '01')
            year_1 = extracted.get('year_1')
            mnth_2 = extracted.get('mnth_2', '12')
            year_2 = extracted.get('year_2')

            if tot:         
                mnth_2 = f'0{str(int(mnth_2) -1)}'
                #print(mnth_2)


            end_of_month = {
                '31' : ['01', '03','05','07','08','10','12' ], 
                '28' : ['02'],
                '30' : ['04', '06', '09', '11']
            }
           
            
            def determine_day(mnth):
                day = None
                for k, v in end_of_month.items():
                    for d in end_of_month[k]:
                        if d == mnth_2:
                            day = k
                            break
                return day

            day = determine_day(mnth_2)
            #cent_2 = extracted.get('cent_2', '')

                    #start_date = f'01-01-{numb_1}01'
                    #end_date = f'31-12-{century_pattern.group('numb_1')}00'
            
            if year_1: 
                start_date = f'01-{mnth_1}-{year_1}'
            
            else:
                start_date = f'01-{mnth_1}-{cent_1}'
            
            
            if cent_2:
                end_date = f'{day}-{mnth_2}-{cent_2}'
            elif cent_1:
                end_date = f'{day}-{mnth_2}-{cent_1}'
            elif year_2: 
                end_date = f'{day}-{mnth_2}-{year_2}'
            else: 
                end_date = f'{day}-{mnth_2}-{year_1}'
            
            # if start_date == None or end_date == None:
             #   print(f'I am None : {start_date} {end_date}')
            log.info(f'I am the date: {date} and this is my start: {start_date} and this is my end: {end_date} type {type(start_date),type(end_date)}')
            #start.append({'start' : start_date})
            #print(start)
            #end.append({'end' : end_date})
            #log.error(f'Error while getting date: {date} {type(Exception()).__name__, Exception}')
            # print(f'I am the date: {date} and this is my start: {start_date} and this is my end: {end_date}')
    #print(f'I am of type : {type(start)} and I am start: \n{start}' )
    #start_df = pd.concat(start, ignore_index=True)
    #end_df = pd.concat(end, ignore_index=True)

    return start_date, end_date

    '''            year_1 = extracted.get('year_1', cent_1)
            mnth_2 = extracted.get('mnth_2', '12')
            year_2 = extracted.get('year_2', year_1)

            #cent_2 = extracted.get('cent_2', '')

                    #start_date = f'01-01-{numb_1}01'
                    #end_date = f'31-12-{century_pattern.group('numb_1')}00'
            
            start_date = f'01-{mnth_1}-{year_1}'
            end_date = f'{day}-{mnth_2}-{cent_2 if cent_2 else year_2}'
            print(f'I am the date: {date} and this is my start: {start_date} and this is my end: {end_date}')'''

    #return start_date, end_date
#
#
    #        day = ''
    #mnth_1 = match.group('mnth_1')
    #mnth_2 = match.group('mnth_2')
    #year_1 = match.group('year_1')
    #year_2 = match.group('year_2')
    #
    #for item in thirty_first:
    #    day = '31' if mnth_1 == item or mnth_2 == item else '30'
#
    #if tot_pattern:
    #    try:
    #        print(f'I\'m in the tot with date: {date}')
    #        minus = f'{str(int(tot_pattern.group('first')) - 1)}'
    #        print(f'this is the minus: {minus}')
    #        
    #        date = re.sub(tot_pattern.group('first'), f'0{minus}', date)
    #        print(f'this is the date: {date}')
    #    except Exception as e:
    #        print(f'I get in the tot with error: {e} and type {type(e).__name__, e}')
    #        '''#if tot_pattern.group('optional'):
    #        date = re.sub(tot_pattern.group('optional'), minus, date)
    #    elif tot_pattern.group('first'):
    #        date = re.sub(tot_pattern.group('first'), minus, date)'''
    #if four_yrs_pattern: # year, year year - year
    #    start_date = ''
    #    end_date = ''
    #    #print(f'I\'m in the four_yrs_pattern with date{date}')
    #    return start_date, end_date
    #'''if mnth_yr_mnth_yr_pattern: # month - year - month - year
    #    print(f'I\'m in the mnth_yr_mnth_yr_pattern with date: {date}')
    #    start_date = f'01-{mnth_yr_mnth_yr_pattern.group('mnth_1')}-{mnth_yr_mnth_yr_pattern.group('year_1')}'
    #    end_date = f'31-{mnth_yr_mnth_yr_pattern.group('mnth_2')}-{mnth_yr_mnth_yr_pattern.group('year_2')}'
    #    return start_date, end_date'''
    #if mnth_yr_mnth_yr_pattern:
    #    
    #    mnth_1 = f'{mnth_yr_mnth_yr_pattern.group('mnth_1')}'
    #    start_date = f'01-{mnth_1}-{mnth_yr_mnth_yr_pattern.group('year_1')}'
    #    end_date = f'{day}-{mnth_2}-{mnth_yr_mnth_yr_pattern.group('year_2')}'
    #    print(f'I\'m in the mnth_yr_mnth_yr_pattern with date: {date} and startdate = {start_date} and end_date: {end_date}')
    #    return start_date, end_date
    #if yr_mnth_yr_pattern: # year - month - year
    #    #print(f'I\'m in the yr_mnth_yr_pattern with date: {date}')
    #    start_date = f'01-01-{yr_mnth_yr_pattern.group('year_1')}'
    #    end_date = f'31-{yr_mnth_yr_pattern.group('mnth_1')}-{yr_mnth_yr_pattern.group('year_2')}'  
    #    
    #    return start_date, end_date
    #if between_yrs_pattern: # year - year
    #    start_date = f'01-01-{between_yrs_pattern.group('year_1')}'
    #    end_date = f'31-12-{between_yrs_pattern.group('year_2')}'        
    #    #print(f'I\'m in the between_yrs_pattern with date: {date}')
    #    return start_date, end_date
    #if mnth_sh_yr_mnth_yr_pattern: # month - shorted year - month - year
    #    #print(f'I\'m in the mnth_sh_yr_mnth_yr_pattern with date: {date}')
    #    start_date = f'01-{mnth_sh_yr_mnth_yr_pattern.group('mnth_1')}-{mnth_sh_yr_mnth_yr_pattern.group('century')}{mnth_sh_yr_mnth_yr_pattern.group('short_year')}'
    #    end_date = f'31-12-{mnth_sh_yr_mnth_yr_pattern.group('year_2')}'  
    #    return start_date, end_date
    #if mnth_yr_pattern:
    #    #print(f'I\'m in the mnth_yr_pattern with date: {date}')
    #    start_date = f'01-{mnth_yr_pattern.group('mnth_1')}-{mnth_yr_pattern.group('year_1')}'
    #    end_date = f'31-{mnth_yr_pattern.group('mnth_1')}-{mnth_yr_pattern.group('year_1')}'  
    #    return start_date, end_date 
    #if centuries_pattern:
    #    numb_1 = f' {str(int(centuries_pattern.group('numb_1')) - 1)}' 
    #    start_date = f'01-01-{numb_1}01'
    #    end_date = f'31-12-{centuries_pattern.group('numb_1')}00'
    #    #print(f'I\'m in the centuries_pattern with date {date}')
    #    return start_date, end_date
    #if century_pattern:
    #    numb_1 = f' {str(int(century_pattern.group('numb_1')) - 1)}'
    #    start_date = f'01-01-{numb_1}01'
    #    end_date = f'31-12-{century_pattern.group('numb_1')}00'
    #    #print(f'I\'m in the century_patternwith date {date}')
    #    return start_date, end_date
    #'''if circa_pattern: # ca / ca. / Circa / circa - year ending in 0
    #    year_match = re.search( r'(?P<decennium>\\d{3}0).*', date)
    #    if year_match: 
    #        start_date = f'01-01-{year_match.group('decennium')}'
    #        # end = (int(decennium_pattern.group('decennium') ) + 9)
    #        end_date = f'31-12-{str(int(year_match.group('decennium')) + 9)}'
    #        return start_date, end_date
    #    else:
    #        pass'''
    #if yr_patttern:
    #    start_date = f'01-01-{yr_patttern.group('year_1')}'
    #    end_date  = f'31-12-{yr_patttern.group('year_1')}'
    #    #print('I\'m in the yr_patttern')
    #    return start_date, end_date
    #if else_pattern: 
    #    start_date = ''
    #    end_date = ''
    #    #print(f'I\'m in the else pattern with date: {date}')
    #    return start_date, end_date
    #else: 
    #    start_date = ''
    #    end_date = ''
 
    
def create_dataframe(record_uuids):

    date = str('File.rico:isAssociatedWithDate.rico:expressedDate')
    start = str('File.rico:isAssociatedWithDate.rico:hasBeginningDate')
    end = str('File.rico:isAssociatedWithDate.rico:hasEndDate')
    
    df = pd.read_csv(record_uuids, 
    sep=";",             
    dtype={ "uuid": str,
           date : str,
           start : str,
           end : str
       })
    df = df.fillna(value='')

    return df, date, start, end
    

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

        for inst in g.objects(None, SAA.date): #### 

            predicates_df, _, _, _, _, _ = get_turtle_info(inst, g, uuid, dates, pattern)

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
                    time.sleep(3)
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
        result['errors'].append({'errortext': "ERROR Main fn, failing transformation or upload", 'uuid': uuid, 'error': str(e)})
        result['status'] = 'failed'

    return result

def main():

    sys.path.append(str(f'{HOME_REPO}/scripts'))
    from general import file_and_log_management
    log, error_file, backup_file, out_file = file_and_log_management.setup_logging(env, project_name, project_name)
    
    log.info(f'ENVIRONMENT: {env}') 
    input('\t\"COLLECT AND ANALYZE DATA NOW?\": (Y/N)')

    errors = []
    backup = []
    out = []

    try: 
        df, date, start, end = create_dataframe(record_uuids)
        
        log.info(f'There are : {len(df)} rows in the datasheet.')

    except Exception as e: 
        log.info(f'FAILED CREATING DATAFRAME from the record_uuids')
        log.error(f'Error while creating dataframes {e}')    

    try:

        for idx, row in df.iterrows():
            date = df[date].notna()

            df[date]= df[date].apply(
                lambda x: filter_noise(x))

            df[start], df[end] = get_date(date, log)
            print('I do get out')
            df_out = pd.DataFrame(df.copy())
            out.append(df_out)
        
    except Exception as e:
        log.info(f'FAILED getting date with {df[start]} {df[end]} error : {e}')
        log.error(f'Error while getting dates {type(e).__name__, e}') 

    '''# -----------------------------------
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
            out.extend(result['outlier_rows'])'''

    
    # write CSVs once, after everything is done
    file_and_log_management.create_csv(errors, error_file)
    if backup:
        backup_df = pd.concat(backup, ignore_index=True)
        file_and_log_management.create_csv(backup_df, backup_file)
    if out:
        out_df = pd.concat(out, ignore_index=True)
        out_df.to_csv(out_file, mode="w", index=False)
        file_and_log_management.create_csv(out_df, out_file)
    
      
if __name__ == '__main__':
    main()
