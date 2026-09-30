## Import libraries
import sys
import os 
from pathlib import Path
from datetime import time, datetime
import logging
import pandas as pd
import re

# Log handler 
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
    logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(logfile, mode='w')]
)
log = logging.getLogger()

## Declare script variables
current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
logfile = f'..logs/change_my_column{str(current_datetime)}.log'
data = sys.argv[1]
out_file = r'../data/inventaris-10012-omnummeren.csv' 
#pattern = r'.*?([1-9]\d*)$'
#replace = pattern.group(1)

# memorix.get_record_type(name)
def main():
    print('in')
    uuid = "uuid"
    identifier = "File.rico:identifier"
    ########################     READ FILES    ########################    
    #df_column = pd.read_csv(data)
    df_column = pd.read_csv(data, 
                            sep=';')
    #df_column = pd.DataFrame(df_column)     
    print(df_column)
    #print(df_column[identifier])
    print(df_column[identifier])
    try:
        df_column[identifier] = df_column[identifier].str.replace(r'^0/0100120*(\d+)$', r'\1', regex=True)
        print(df_column[identifier])
        print(df_column)

        df_column.to_csv(out_file, sep=';', index=False)

    except:
        log.info(f'Something went wrong with replacing the data in {df_column}')
        #print(f'We have an error in {df_column}') ##################   ------------->>> HIER WILLEN WE DE FILENAAM EXTRACTEN

if __name__ == '__main__':
    main()