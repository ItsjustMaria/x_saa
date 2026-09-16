## Import libraries
import os 
import sys
from datetime import time, datetime
import logging
from pathlib import Path
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test/cli_module")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa


# -----------------------------------
# DECLARATIONS
# -----------------------------------
def main():
    
    env = sys.argv[1]
    current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    logfile = f'logs/retrieve_concept_turtle {str(current_datetime)}.log'
    errors = []
    vocabulair = 'a4863c0c-d9e5-3902-831a-d0960e381a41'  #### !!!! uuid of vocabulair            
    concept_turtle = r"data/concept_turtle.ttl"           #### !!!! Location of street turtle

    # Log handler 
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.FileHandler(logfile, mode='w')]
    )
    log = logging.getLogger()

    # Environment setup
    if env == 'acc':
        PREFIX = 'https://ams-migrate.memorix.io'
        settings_file = Path(WORK_REPO, 'settings.json') 
    elif env == 'prod':
        PREFIX = 'https://stadsarchiefamsterdam.memorix.io'
        settings_file = Path(WORK_REPO, 'settings.prod.json') 
        print(' Am using production')
    elif env == 'tst':
        settings_file = print(f'test output')
    else:
        raise ValueError("Environment must be 'acc' or 'prod'")

    settings = saa.readJsonFile(settings_file) 
    api = memorix.ApiClient(settings)

    try: 
        # Retrieve concept vocabulaire from memorix
        response = api.list_concepts( vocabulair)
        print(response.text,  file=open(concept_turtle, 'w', encoding='utf-8'))

        if response.status_code != 200:
            log.info("...Try to read again...")
            time.sleep(3)
            response = api.list_concepts( vocabulair)
            print(response.text,  file=open(concept_turtle, 'w', encoding='utf-8'))
        else:

            print(response.text,  file=open(concept_turtle, 'w', encoding='utf-8'))
    
    except Exception as e:
        print(f"FAILED {vocabulair, response}: {e}")
        log.error(f'Something went wrong with retrieving the concepts from memorix { env, vocabulair}')
        errors.append({'fn: main: retrieve concepts turtle from memorix for the vocabulair and environment': [vocabulair, env]})


if __name__ == '__main__':
    main()