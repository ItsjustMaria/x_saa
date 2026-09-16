## Import libraries
import sys
import os 
import asyncio
import tracemalloc
import simplejson as json
from datetime import time, datetime
from tqdm import tqdm
sys.path.append(r'../../')
from modules import memorix
from modules import saa
import click
# from modules import wrapper
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace, RDF, BNode, XSD
import pandas as pd
import re
from pathlib import Path
import logging
from rapidfuzz import fuzz

tracemalloc.start()
PYTHONTRACEMALLOC = 1
'''Script for creating brand new files to a fonds and importing it'''
@click.command()
@click.argument('script')
@click.option('--env', '-e', type=click.Choice(['acc', 'prod']), default='acc',
              help='Which environment to use: “acc” or “prod”.')
@click.argument('records')
#@click.option('--output', '-o', default='output.csv',
#              help='Path to CSV logfile (will be appended).')
#@click.option('--workers', '-w', default=10, show_default=True,
#              help='Number of concurrent worker threads.')
#@click.option('--max-calls', '-m', default=0, type=int, show_default=True,
#              help='Maximum API calls per second (0 = unlimited).')
def main(script, env, records): 
    pass


## Declare script variables
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
env = sys.argv[1]
file = sys.argv[2]

# Define a namespace
record = Namespace("/resources/records/")
rt = Namespace("/resources/recordtypes/")
rico = Namespace("https://www.ica.org/standards/RiC/ontology#")
mmx = Namespace("http://memorix.io/ontology#") 
saa_nm = Namespace("https://data.archief.amsterdam/ontology#")
xsd = Namespace("http://www.w3.org/2001/XMLSchema#")
# concept = Namespace("/resources/vocabularies/concepts/")
# vocabularies = Namespace("/resources/vocabularies/conceptschemes/")
dr = Namespace("/resources/recordtypes/DigitalRecord#")
dd = Namespace("/resources/recordtypes/DigitalDossier#")
skos = Namespace("http://www.w3.org/2004/02/skos/core#")


# Declare user case dependent variables 
logfile = f'../logs/create_files {str(current_datetime)}.log' # Specify your own log name and location
turtle = Path("../template/file.ttl") # <-- Zet hier het pad naar jouw turtle 
turtle_uuid = '94a49083-be64-4258-9a49-46d0b8816cbe' # <-- turtle uuid om aan te passen voor upload 
regex_format = r'/resources/recordtypes/([^/>]+)' # Declare what to search for to validate the turtle used


names = ['ADMNR','NADERE_TOELICHTING','NAAM','GEBOORTEDATUM','DOSSIERTYPE','DOSSIERTYPE_BESCHRIJVING','CREATIEDATUM_DOSSIER'] # Column names in one string
pattern = r'''
(\d{7})?,                                         # 1: admin_nr
([A-Z0-9]*)?,                                     # 2: admin_extra
([A-Za-z]+\s*[A-Za-z]*\s*[A-Za-z]*\s*[A-Za-z]*)?, # 3: name + initials
(\d{2}-\d{2}-\d{4})?,                             # 4: date
([A-Z]{2,4})?,                                    # 5: type  
([A-Za-z]+\s*[A-Za-z]*)?,                         # 6: description
(\d{2}-\d{2}-\d{4})?                              # 7: date
'''

#pattern = r'(\d{7})([A-Z0-9]+)([A-Za-z]\s*?)(\d{2}-\d{2}-\d{4})([A-Z]{2,4})([A-Za-z]\s*?)(\d{2}-\d{2}-\d{4})'

# Log handling
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
    settings_file = r'../../settings.json'
    cwd = os.getcwd()  # Get the current working directory (cwd)
    files = os.listdir(cwd)  # Get all the files in that directory
    print("Files in %r: %s" % (cwd, files))
elif env == 'prod':
    prefix = 'https://stadsarchiefamsterdam.memorix.io'
    settings_file = '../../settings.prod.json'
elif env == 'tst':
    settings_file = r'../../settings.json'
    #print(f'test output')
else:
    raise ValueError("Environment must be 'acc' or 'prod'")

# Standard API client variables
settings = saa.readJsonFile(settings_file) # prod of acc
api = memorix.ApiClient(settings)


# Check if turtle legit
def check_turtle_legit(turtle):
    # Laden van RDF/Turtle bestand
    g = rdflib.Graph()
    g.parse(turtle, format="ttl")
    print('I get in the if response')
    match = re.search(regex_format, str)
    for s in g.type(rdflib.RDF.type, rt.File): ########################
        if match:
            print(f'This turtle is a valid format')
            
        else:
            my_log.error(f'turtle is not of type \'file\': {turtle}')

# async function to determine turtle is legit
async def get_turtle(turtle):
    print('I get in the not')
    try:
        response = api.get_record( turtle_uuid )
        await asyncio.sleep(3)
        print(response.status_code)
        print(response.text,  file=open(turtle, 'w', encoding='utf-8'))
    except:
        my_log.error(f'turtle can not be imported')
        raise ImportError    

# check if turtle exists and call async if not
if not turtle.is_file():
    t = get_turtle(turtle)
    asyncio.run(t)
else: 
    check_turtle_legit(turtle)
# read file and convert to set for fast searching

df = pd.read_csv(file, header=None, delimiter = ',')
# df_set = set(df.iloc[:, 0]) # DO I NEED A SET? I DON'T NEED TO SEARCH RIGHT?

#df[names] = df[0].str.extract(pattern, flags=re.VERBOSE)
df[0] = df[0].str.replace('"', '', regex=False)
df[0] = df[0].str.replace('        ', ' ', regex=False)
df[0] = df[0].str.replace(', ', ' ', regex=False)
#print(f'This is the type of the df{type(df[0])}')
df[0] = df[0].str.strip()
df[0].to_csv('../data/test_output.csv', sep=',')
print (df[0])
extracted = df[0].str.extract(pattern)
df['one'] = extracted[1].str.strip()
print(df['one'])
df[names] = df[0].str.extract(pattern, flags=re.VERBOSE)

print(f'this is the shap:{extracted.shape}')
print(f'This is the head: {extracted.head()}')
#df_sep.notna('', inplace = True)

# Merge back columns that should not be separated

print(f'This is the length: {len(names)}')

df_sep = df[names]
# Add names to colunns
df_sep.columns.fillna = [names]


#df_sep[2] = df_sep[3] + ' ' + df_sep[2]
#df_sep.drop(columns = [3])
#print(f'This is names: {df_sep[2]}') 
#print(f'This is additives: {df_sep[3]}')
#names_list = list(names.split(','))
for index, name in enumerate(names):
    df_sep.rename(columns={index: name}, inplace = True)

#        df_sep = pd.concat([df, sep], axis=1).fillna
print(df_sep)
#print(df_sep)

### Added a row ###

#file_to_rows = []
#
#for index, row in df.iterrows():
#    admin_nr = ast.literal_eval(row["ADMNR"])
#    for locatie in locatie_list:
#        doc_id_list = ast.literal_eval(str(locatie["doc_id"]))
#        for doc_id in doc_id_list:
#            if doc_id is not None:
#                if "|" in doc_id:
#                    result = doc_id.split('|')
#                    for id in result:
#                        doc_id_rows.append({'uuid': row['uuid'], 'doc_id': id, 'end_date': row['end_date'], 'description': row['description']})
#                else:
#                    doc_id_rows.append({'uuid': row['uuid'], 'doc_id': doc_id, 'end_date': row['end_date'], 'description': row['description']})
#doc_id_df = pd.DataFrame(doc_id_rows)
#
#
for index, row in df.iterrows():
    g = Graph()

    g.bind("record", record)
    g.bind("rt", rt)
    g.bind("rico", rico)
    g.bind("memorix", mmx)
    g.bind("saa", saa_nm)
    # g.bind("concept", concept)
    # g.bind("vocabularies", vocabularies)
    # g.bind("dd", dd)
    g.bind("skos", skos)

ar_uri = BNode()
g.add((ar_uri, RDF.type, mmx.AccessibilityAndRightsComponent))
g.add((ar_uri, mmx.accessModeDisplay, mmx.DisplayAssets))
g.add((ar_uri, mmx.accessModeDownload, Literal(True, datatype=XSD.boolean)))
g.add((ar_uri, mmx.accessModeReservation, Literal(False, datatype=XSD.boolean)))
g.add((ar_uri, mmx.accessModeScanningOnDemand, Literal(False, datatype=XSD.boolean)))
g.add((ar_uri, mmx.attributionRequired, Literal(False, datatype=XSD.boolean)))
g.add((ar_uri, mmx.audience, mmx.AudienceExternal))
#use_uri = URIRef(concept["e8a92b13-efaf-4b2e-e053-b784100a3466"])
#g.add((use_uri, RDF.type, skos.Concept))
#g.add((ar_uri, mmx.limitationOfUse, use_uri))
#g.add((ar_uri, mmx.physicallyAvailable, Literal(False, datatype=XSD.boolean)))
#raw_value = row.get("openbaarheid", None)
#openbaarheid_dict = ast.literal_eval(raw_value)
#if openbaarheid_dict.get("omschrijvingBeperkingen") == "Aanvraagformulier":
#    access_uri = URIRef(concept["56b6ffe6-f801-4715-872b-303db35f48f9"])
#    g.add((ar_uri, mmx.limitationOfAccess, access_uri))
#    g.add((access_uri, RDF.type, skos.Concept))
#    g.add((ar_uri, mmx.restrictionsExpire, Literal(openbaarheid_dict.get("datum"), datatype=XSD.date)))
#if openbaarheid_dict.get("omschrijvingBeperkingen") is None:
#    access_uri = URIRef(concept["b91d25b5-a1b4-4bc9-a15c-d48883a95d0b"])
#    g.add((ar_uri, mmx.limitationOfAccess, access_uri))
#    g.add((access_uri, RDF.type, skos.Concept))
#g.serialize(f"E:/wabo/bwt/{toegangsnr}/rechten/{row["uuid"]}.ttl", format="turtle", encoding='utf-8')
#print(f"Turtle gemaakt voor rechten {row["uuid"]}")
#

if __name__ == '__main__':
    main()
