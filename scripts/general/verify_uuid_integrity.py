import pandas as pd
from pathlib import Path
import sys
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))

'''
   Compare two CSV files to find UUID discrepancies
   
   Usage
   python verify_uuid_integrity.py --env

   The following data is needed; 
   * base_csv: Path to original CSV from third API (get_record)
   * result_csv: Path to threadpool output CSV

   Scripts used are: 
   -
   
   Modules used are:
   -

   This script does in order:  
   1) Setup logging and create directories if needed
   2) CONFIRM ENVIRONMENT AND ASK TO PROCEED
   3) Match uuids in result to base file and lists missing uuids in result
   4) Match uuids in base file to result and lists spooking uuids in result that should not occur
   5) Creates an export csv with all results

   Output files are: 
   * HOME_REPO/data/export/missing_uuids_{env}.csv

'''

env = sys.argv[1]  # "acc" or "prod"
project_name = 'rename_file_to_image_output'
# Paths to your files
base_csv = Path(HOME_REPO,'data',project_name, 'source' ,f'record_uuids_{env}.csv')     # Original from third API
result_csv = Path(HOME_REPO,'data',project_name,'export' ,  f'backup_{env}.csv')   # Threadpool result
missing_uuids = Path(HOME_REPO,'data',project_name,'export' ,  f'missing_uuids_{env}.csv')

def verify_uuid_integrity(base_csv, result_csv):
   
    # Load both files
    base_df = pd.read_csv(base_csv, dtype={'uuid': str})
    result_df = pd.read_csv(result_csv, dtype={'uuid': str})
    
    # Get UUID sets
    base_uuids = set(base_df['uuid'])
    result_uuids = set(result_df['uuid'])
    
    # Find discrepancies
    missing_in_result = base_uuids - result_uuids  # UUIDs in base but NOT in result
    missing_in_base = result_uuids - base_uuids    # UUIDs in result but NOT in base (unexpected)
    
    # Statistics
    stats = {
        'base_count': len(base_uuids),
        'result_count': len(result_uuids),
        'missing_in_result_count': len(missing_in_result),
        'missing_in_base_count': len(missing_in_base),
        'intersection_count': len(base_uuids & result_uuids)
    }
    
    return {
        'stats': stats,
        'missing_in_result': sorted(list(missing_in_result)),
        'missing_in_base': sorted(list(missing_in_base))
    }

# USAGE
if __name__ == '__main__':    
    
    verification = verify_uuid_integrity(base_file, result_file)
    
    # Print report
    print("=" * 60)
    print("UUID INTEGRITY VERIFICATION REPORT")
    print("=" * 60)
    
    print(f"\n STATISTICS:")
    print(f"   Base file UUIDs:      {verification['stats']['base_count']}")
    print(f"   Result file UUIDs:    {verification['stats']['result_count']}")
    print(f"   Matched UUIDs:        {verification['stats']['intersection_count']}")
    print(f"   Missing in result:    {verification['stats']['missing_in_result_count']}")
    print(f"   Unexpected in result: {verification['stats']['missing_in_base_count']}")
    
    if verification['missing_in_result']:
        print(f"\n  MISSING IN RESULT FILE ({len(verification['missing_in_result'])}):")
        print("-" * 40)
        for i, uuid in enumerate(verification['missing_in_result'], 1):
            print(f"   {i}. {uuid}")
    
    if verification['missing_in_base']:
        print(f"\n UNEXPECTED IN RESULT FILE ({len(verification['missing_in_base'])}):")
        print("-" * 40)
        for i, uuid in enumerate(verification['missing_in_base'], 1):
            print(f"   {i}. {uuid}")
        print("\n These UUIDs exist in result but NOT in original base file!")
    
    # Export missing UUIDs for manual review
    if verification['missing_in_result']:
        missing_df = pd.DataFrame({
            'uuid_to_verify': verification['missing_in_result']
        })
        missing_df.to_csv(missing_uuids, index=False)
        print(f"\n Missing UUIDs exported to: 'missing_uuids_for_manual_check.csv'")
    
    print("=" * 60)

    for uuid in verification['missing_in_result']:
        print(f"\nManual check for {uuid}:")