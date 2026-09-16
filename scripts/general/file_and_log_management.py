import sys
import os 
import logging
from datetime import time, datetime
from pathlib import Path
import pandas as pd
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))

current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")

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
    
    filename = Path(HOME_REPO,'data',project_name, folder,f'{file}.{ext}')
    
    os.makedirs(Path(filename.parent), exist_ok=True)
    
    if os.path.exists(filename):
        os.makedirs(Path(HOME_REPO,'data',project_name, folder, 'OLD/'), exist_ok=True)
        old_file = Path(HOME_REPO,'data',project_name, folder, 'OLD/', f'{file}_{current_datetime}{ext}')
        os.rename(filename, old_file)
        log.info(f'Filename {filename} already existed. Archived file with current date timestamp and moved to dir: OLD')
        
    log.info(f'Created the file: {Path(filename)}\n')
    
    return filename

def setup_logging(env, project_name):
    
    log = logging.getLogger("organizer")
    log.setLevel(logging.DEBUG)   

    logfile = check_file_exist(project_name,'migr_str_to_cnpt_log', log, 'log')
    backup_file = check_file_exist(project_name,f"backup_{env}", log, 'csv')
    error_file = check_file_exist(project_name,f"error_{env}", log, 'csv')
    out_file = check_file_exist(project_name,f"out_{env}", log, 'csv')

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