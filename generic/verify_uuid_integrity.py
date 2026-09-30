import pandas as pd
from pathlib import Path
import sys
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))

env = sys.argv[1]  # "acc" or "prod"
project_name = 'rename_file_to_image_output'

def verify_uuid_integrity(base_csv, result_csv):
    """
    Compare two CSV files to find UUID discrepancies
    
    Args:
        base_csv: Path to original CSV from third API (get_record)
        result_csv: Path to threadpool output CSV
    
    Returns:
        dict with missing_in_result, missing_in_base, and stats
    """
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
    # Paths to your files
    base_file = Path(HOME_REPO,'data',project_name, f'record_uuids_{env}.csv')     # Original from third API
    result_file = Path(HOME_REPO,'files',project_name, f'assets_{env}.csv')   # Threadpool result
    
    verification = verify_uuid_integrity(base_file, result_file)
    
    # Print report
    print("=" * 60)
    print("UUID INTEGRITY VERIFICATION REPORT")
    print("=" * 60)
    
    print(f"\n📊 STATISTICS:")
    print(f"   Base file UUIDs:      {verification['stats']['base_count']}")
    print(f"   Result file UUIDs:    {verification['stats']['result_count']}")
    print(f"   Matched UUIDs:        {verification['stats']['intersection_count']}")
    print(f"   Missing in result:    {verification['stats']['missing_in_result_count']}")
    print(f"   Unexpected in result: {verification['stats']['missing_in_base_count']}")
    
    if verification['missing_in_result']:
        print(f"\n⚠️  MISSING IN RESULT FILE ({len(verification['missing_in_result'])}):")
        print("-" * 40)
        for i, uuid in enumerate(verification['missing_in_result'], 1):
            print(f"   {i}. {uuid}")
        
        print("\n💡 SUGGESTED ACTIONS:")
        print("   • Verify these UUIDs were deleted manually")
        print("   • Check if assetname was null/empty in workapi")
        print("   • Confirm no exceptions occurred during threadpool processing")
        print("   • Manually call get_record(uuid) to check current status")
    
    if verification['missing_in_base']:
        print(f"\n❗ UNEXPECTED IN RESULT FILE ({len(verification['missing_in_base'])}):")
        print("-" * 40)
        for i, uuid in enumerate(verification['missing_in_base'], 1):
            print(f"   {i}. {uuid}")
        print("\n   ⚠️ These UUIDs exist in result but NOT in original base file!")
    
    # Export missing UUIDs for manual review
    if verification['missing_in_result']:
        missing_df = pd.DataFrame({
            'uuid_to_verify': verification['missing_in_result']
        })
        missing_df.to_csv('missing_uuids_for_manual_check.csv', index=False)
        print(f"\n📁 Missing UUIDs exported to: 'missing_uuids_for_manual_check.csv'")
    
    print("=" * 60)

    for uuid in verification['missing_in_result']:
        print(f"\nManual check for {uuid}:")