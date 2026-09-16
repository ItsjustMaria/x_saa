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
    logfile = f'logs/retrieve_uuid_from_memeorix {str(current_datetime)}.log'
    errors = []
    record_uuids = r"data/record_uuids.csv"            #### !!!! Location of uuid from memorix

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
    elif env == 'tst':
        settings_file = print(f'test output')
    else:
        raise ValueError("Environment must be 'acc' or 'prod'")

    settings = saa.readJsonFile(settings_file) 
    api = memorix.ApiClient(settings)

    try: 
        # Path based on location of script and datafolder
        sys.path.append(str(HOME_REPO))
        import get_uuid  

        # Get uuids with query and give storage location for csv
        response = get_uuid.main(env, record_uuids)
        print(response.text,  file=open(record_uuids, 'w', encoding='utf-8'))
        
        if response.status_code != 200:
            log.info("...Try to read again...")
            time.sleep(3)
            response = get_uuid.main(env, record_uuids)
            print(response.text,  file=open(record_uuids, 'w', encoding='utf-8'))
        else:
            print(response.text,  file=open(record_uuids, 'w', encoding='utf-8'))
    
    except Exception as e:
        print(f"FAILED {record_uuids, response}: {e}") 
        log.error(f'Something went wrong with retrieving the record uuids from memorix { env, record_uuids}')
        errors.append({'fn: main: retrieve record uuids from memorix in the environment': [env]})


if __name__ == '__main__':
    main()