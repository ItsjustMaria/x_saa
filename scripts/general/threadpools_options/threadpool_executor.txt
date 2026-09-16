from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from tqdm import tqdm
from pathlib import Path
from functools import wraps
import time
import os 
import sys
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))

# -----------------------------------------------------------
# RETRY DECORATOR WITH EXPONENTIAL BACKOFF
# -----------------------------------------------------------
def retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=10.0):
    """Retry decorator for functions that may fail transiently"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = base_delay
            
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        time.sleep(delay)
                        delay = min(delay * 2, max_delay)  # Exponential backoff
            
            raise last_exception  # All attempts failed
        return wrapper
    return decorator



def execute_threadpool(
        max_workers, 
        uuids_to_process, 
        process_one_uuid, 
        log, 
        errors,
        backup,
        retried,
        out,
        create_csv,
        error_file,
        backup_file,
        out_file,
        start_time
        ):

    with ThreadPoolExecutor(max_workers) as executor:
        
        # Dictionary that collects all params to run through the threadpool processor
        futures = {}
        for _, row in uuids_to_process.iterrows():
            future = executor.submit(
                process_one_uuid, 
                row['uuid'],           # ← unique per iteration
                row['assetname'],      # ← matched to that uuid
                out_file, 
                log
            )
            futures[future] = row['uuid']
    
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
            out.extend(result['out_rows'])
    
    # write CSVs once, after everything is done
    create_csv(errors, error_file)
    if backup:
        backup_df = pd.concat(backup, ignore_index=True)
        backup_df.to_csv(backup_file, mode="w", index=False)
        create_csv(backup_df, backup_file)
    if out:
        out_df = pd.concat(out, ignore_index=True)
        out_df.to_csv(out_file, mode="w", index=False)
        create_csv(out_df, out_file)