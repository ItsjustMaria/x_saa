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
'''from modules import memorix
from modules import saa
from modules import wrapper
'''
from general import file_and_log_management

'''# -----------------------------------------------------------
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
    return decorator'''



def execute_threadpool(
        result,
        **kwrgs
        ):
    
    log, error_file, backup_file, out_file = file_and_log_management.setup_logging(kwrgs['env'], kwrgs['project_name'])
    uuids_to_process = kwrgs['record_df'].head(kwrgs['test_amount'])
    logs = []
    errors = []
    backup = []
    out = []
    print(type(kwrgs['record_df']))
    print(type(uuids_to_process))
    with ThreadPoolExecutor(kwrgs['max_workers']) as executor:

        futures = {}
        for idx, row in uuids_to_process.iterrows():
            future = executor.submit(
                kwrgs['process_one_uuid'],
                row['uuid'],
                result
            )
            futures[future] = {
                'uuid': row['uuid'],
                'attempts': 1
            }

        # All executed runs are collected in a tqdm list with the total length of the executed uuid loops [e.g. based on your test_amount then]
        for future in tqdm(as_completed(futures), total=len(futures)):
            meta = futures[future]

            try:
                # Apply a [builtin ? ] method to identify the information accumulated in the result dictionary
                result = future.result(timeout=60)  # 60s timeout per task
                
                if result.get('error'):
                    errors.append({
                        'uuid': meta['uuid'],
                        'error': result['error'],
                        'attempts': meta['attempts']
                    })
                else:
                    kwrgs['attempts'].append(result)

            except TimeoutError:
                result['errors'].append({
                    'uuid': meta['uuid'],
                    'error': 'TIMEOUT',
                    'attempts': meta['attempts']
                })

            except Exception as e:
                # Retry logic for transient failures
                if meta['attempts'] < result['retry_attempts']:
                    meta['attempts'] += 1
                    
                    # Resubmit with backoff
                    time.sleep(min(2 ** meta['attempts'], 10))
                    result['retried'].append(meta['uuid'])
                    
                    new_future = executor.submit(
                        kwrgs['process_one_uuid'],
                        meta['uuid'],
                    )
                    futures[new_future] = meta
                    
                else:
                    errors.append({
                        'uuid': meta['uuid'],
                        'error': str(e),
                        'attempts': meta['attempts']
                    })
                # this only fires if process_one_uuid itself crashed unexpectedly
                log.error(f"Unhandled exception for uuid {meta['uuid']}: {e}")
                errors.append({'errortext': f'Can not find uuid after {result['retry_attempts']} retries', 'uuid': meta['uuid'], 'error': str(e)})
                continue
    
            # merge the identified uuid's result into the shared lists 
            # this code only ever runs in the main thread, one future at a time
            logs.extend(result['log'])
            for idx, data in enumerate(logs):
                key, value = next(iter(data.items()))
                if key == 'info':
                    log.info(value)
                if key == 'warning':
                    log.warning(value)
                if key == 'error':
                    log.error(value)
                
            errors.extend(result['errors'])
            backup.extend(result['backup_rows'])
            out.extend(result['out_rows'])

    # write CSVs once, after everything is done
    file_and_log_management.create_csv(errors, error_file)
    if backup:
        backup_df = pd.concat(backup, ignore_index=True)
        backup_df.to_csv(backup_file, mode="w", index=False)
        file_and_log_management.create_csv(backup_df, backup_file)
    if out:
        out_df = pd.concat(out, ignore_index=True)
        out_df.to_csv(out_file, mode="w", index=False)
        file_and_log_management.create_csv(out_df, out_file)


     #-------------------------------------------------------
        # OUTPUT SUMMARY & AUDIT TRAIL
        # -------------------------------------------------------
        report = {
            'total_submitted': len(uuids_to_process),
            'successful': len(attempts),
            'failed_permanent': len(errors),
            'retried': len(retried),
            'success_rate': f"{len(attempts)/len(uuids_to_process)*100:.1f}%" if uuids_to_process.size else 0,
            'elapsed_seconds': round(elapsed, 2),
            'avg_per_second': round(len(attempts)/elapsed, 1) if elapsed > 0 else 0
        }

        print(f"\n{'='*60}")
        print("THREADPOOL EXECUTION REPORT")
        print(f"{'='*60}")
        print(f"  Submitted:        {report['total_submitted']}")
        print(f"  Successful:       {report['successful']}")
        print(f"  Failed:           {report['failed_permanent']}")
        print(f"  Retried:          {report['retried']}")
        print(f"  Success Rate:     {report['success_rate']}")
        print(f"  Elapsed Time:     {report['elapsed_seconds']}s ({report['avg_per_second']} req/sec)")
        print(f"{'='*60}")

        # Export error log for investigation
        if errors:
            errors_df = pd.DataFrame(errors)
            errors_df.to_csv('threadpool_errors.csv', index=False)
            print(f"\n  Errors exported to: threadpool_errors.csv")

            # Show top 5 error types
            print("\nTop errors:")
            error_counts = errors_df['error'].value_counts().head(5)
            for err, count in error_counts.items():
                print(f"   {err}: {count}")

        # Export successful results
        if attempts:
            results_df = pd.DataFrame(attempts)
            results_df.to_csv('threadpool_results.csv', index=False)
            print(f"✓ Results exported to: threadpool_results.csv")

        # Return for downstream use
        return attempts, result, retried, report


    ## -----------------------------------------------------------
    ## ENHANCED WORKER FUNCTION WITH ERROR CATCHING
    ## -----------------------------------------------------------
    #@retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=10.0)
    #def process_one_uuid(uuid, assetname, out_file, log):
    #    """Worker with built-in exception handling and retry support"""
    #    
    #    try:
    #        # 1)  Check for empty assetname early (common silent failure)
    #        if not assetname or str(assetname).strip() == '':
    #            return {'uuid': uuid, 'assetname': assetname, 'error': 'EMPTY_ASSETNAME', 'skipped': True}
    #        
    #        # 2) Fetch Turtle from second API
    #        turtle_content = api.get_record(assetname)  # Your existing function
    #        
    #        # 3) Parse with rdflib (wrapped for errors)
    #        try:
    #            g = rdflib.Graph()
    #            g.parse(data=turtle_content, format='turtle')
    #        except Exception as parse_error:
    #            return {'uuid': uuid, 'assetname': assetname, 'error': f'PARSER_ERROR: {parse_error}', 'parsed': False}
    #        
    #        # 4) Your processing logic here
    #        processed_data = extract_rdf_data(g)  # Your existing logic
    #        
    #        return {
    #            'uuid': uuid,
    #            'assetname': assetname,
    #            'status': 'success',
    #            'data': processed_data
    #        }
    #        
    #    except Exception as e:
    #        # Re-raise for retry decorator to catch
    #        raise RuntimeError(f"UUID {uuid}: {str(e)}")