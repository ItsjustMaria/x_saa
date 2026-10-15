## Import libraries
import sys
import os 
from pathlib import Path
from datetime import time, datetime
import logging
import pandas as pd
import re

log = logging.getLogger()

## Declare script variables
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
logfile = f'..logs/change_my_column{str(current_datetime)}.log'
data = sys.argv[1]
out_file = r'../data/inventaris-10012-omnummeren.csv' 

# Log handler 
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
    logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(logfile, mode='w')]
)

def main():

    uuid = "uuid"
    identifier = "File.rico:identifier"

    # READ FILES     
    df_column = pd.read_csv(data, 
                            sep=';')
      
    try:
        df_column[identifier] = df_column[identifier].str.replace(r'^0/0100120*(\d+)$', r'\1', regex=True)

        df_column.to_csv(out_file, sep=';', index=False)

    except:
        log.info(f'Something went wrong with replacing the data in {df_column}')

if __name__ == '__main__':
    main()