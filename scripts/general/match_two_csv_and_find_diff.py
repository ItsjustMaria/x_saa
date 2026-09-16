import pandas as pd
from pathlib import Path
import sys
import os
from tqdm import tqdm
import csv
from io import StringIO
import numpy as np
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))

'''
   Compare two CSV files to find differences between the two
   
   Usage
   python match_two_csv_and_find_diff.py --source --match

   The following data is needed; 
   * source_csv: Path to original CSV 
   * match_csv: Path to CSV to match against

   Scripts used are: 
   -
   
   Modules used are:
   -

   This script does in order:  
   1) Setup logging and create directories if needed
   3) Match data betweeen files based on columns listed by user and log differences in result_output
   4) Match uuids in base file to result and lists spooking uuids in result that should not occur
   5) Creates an export csv with all results

   Output files are: 
   * HOME_REPO/data/export/missing_uuids_{env}.csv

'''
source = sys.argv[1]
match = sys.argv[2]


env = sys.argv[1]  # "acc" or "prod"
project_name = 'match_two_csv_and_find_diff'
os.makedirs(Path(HOME_REPO, 'data', project_name ), exist_ok=True)
# Paths to your files
source_csv = Path(HOME_REPO, 'data', project_name, 'source' ,source)     # Identify the path where the source file is located
match_csv = Path(HOME_REPO, 'data', project_name, 'source',  match)   # Identify the path where the file to match against is located
columns = {'uuid' : str, 'filename' : str}
result_missing_csv = Path(HOME_REPO,'data',project_name,'output' ,  f'result_missing_rows.csv')
missing_list = []

def create_csv(my_df, file):
    #my_list = [arr.tolist() for arr in my_list]
    #print(f"The structure of ly list: \n {my_list[:3]}")
    # Outliers to dataframe 
    #csv_df = pd.DataFrame(my_list) # , index=range(len(my_list))

    my_df.to_csv(
        file,
        mode="w", sep=';',
        header=True,
        
    )

    return my_df

def read_csv_lines(filename, delimiter=';'):
        with open(filename, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=delimiter)
            return list(reader)

def find_columns_mismatch(source_csv, result_csv):

    #for _ in tqdm(range(80000), desc="Processing large range"):
      
    # Read both files as lists of parsed rows
    

    f1_rows = read_csv_lines(source_csv)
    f2_rows = read_csv_lines(result_csv)

    #for line in f1_contents:
    #    if line not in f2_contents:
    #        missing_list.append(line)
    missing_rows = [row for row in f2_rows if row not in f1_rows]
    #missing_list.extend(missing_rows)
    df_missing = pd.DataFrame(missing_rows, columns=[
                'uuid',
                'TOEGANGSNR',
                'INVNR',
                'filename',
                'ASSETID'
                ])
    print(df_missing)
    #missing_list.append(df_missing)
    #df_missing.to_csv('missing_rows.csv', index=['UUID', 'TOEGANGSNR', 'INVNR', 'BESTANDSNAAM', 'ASSETID'], header=True, sep=';')
#
    #for line in f2_contents:
    #    if line not in f1_contents:
    #        print(line)
    #        headers = [header.strip() for header in line[0].split()]
    #        print(f"Header: \n:{headers}")
    #
    #        '''for row in line[1:]:
    #            values = [value.strip() for value in row.split(',')]
    #            row_dict = {'column' : headers, 'value' : values}
    #            print(f"values: \n:{values}")'''
    #        df = pd.DataFrame(dtype={line : str})
    #        print (df)
    #    missing_list.append(df)
    #    
        #print(f"row_dict: \n{row_dict}")
    create_csv(df_missing, result_missing_csv)

    

# USAGE
if __name__ == '__main__':    
  
    differences = find_columns_mismatch(source_csv, match_csv)
    
    