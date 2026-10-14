#!/usr/bin/env python3
"""
Smart Merge - Move files from origin to destination while preserving structure.
Keeps the larger file when duplicates exist.

Usage: python3 smart_merge.py <origin_path> <destination_path>
"""

import sys
import os
import shutil
from pathlib import Path
HOME_REPO = Path("/opt/lampp/htdocs/test/scripts")
sys.path.append(str(HOME_REPO))
from general import file_and_log_management

project = 'smart_merge'
name = 'move_sims_files'

def get_file_size(file_path: str) -> int:
    """Return file size in bytes."""
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0


def process_directory(log, origin: Path, destination: Path) -> tuple[int, int, int]:
    """
    Process all files in origin directory tree.
    
    Returns: (files_moved, files_overwritten, files_skipped)
    """
    moved = 0
    overwritten = 0
    skipped = 0

    log.info({'TEST' : f'test'})
    # Walk through all files in origin
    for origin_root, dirs, files in os.walk(origin):
        # Calculate relative path from origin base
        rel_path = os.path.relpath(origin_root, origin)
        dest_root = destination / rel_path
        
        # Create destination folder if it doesn't exist
        if not dest_root.exists():
            dest_root.mkdir(parents=True, exist_ok=True)
        
        for filename in files:
            origin_file = Path(origin_root) / filename
            dest_file = dest_root / filename
            
            if not dest_file.exists():
                # File doesn't exist in destination - move it
                try:
                    shutil.move(str(origin_file), str(dest_file))
                    moved += 1
                    log.info({"MOVE" : f"{rel_path}/{filename}"})
                except Exception as e:
                    log.error({"ERROR" : f"Failed to move {origin_file}: {e}"})
            else:
                # File exists - compare sizes
                origin_size = get_file_size(str(origin_file))
                dest_size = get_file_size(str(dest_file))
                
                if origin_size > dest_size:
                    # Origin file is larger - overwrite
                    try:
                        shutil.move(str(origin_file), str(dest_file))
                        overwritten += 1
                        log.info({f"OVERWRITE" : f"{rel_path}/{filename} origin size: ({origin_size}B -> dest size{dest_size}B)"})
                    except Exception as e:
                        log.error({f"ERROR" : f"Failed to overwrite {dest_file}: {e}"})
                elif origin_size == dest_size:
                    # Same size - skip (files may be identical)
                    skipped += 1
                    print('I get here, so ... ')
                    log.info({"SKIP" : f"{rel_path}/{filename} (same size: {origin_size}B)"})
                else:
                    # Destination file is larger - skip
                    skipped += 1
                    log.info({"SKIP" : f"{rel_path}/{filename} (keeping larger dest file: {dest_size}B)"})
                    
    
    return moved, overwritten, skipped


def main():

    log, error_file, backup_file, out_file = file_and_log_management.setup_logging('private', name, project)
    
    

    if len(sys.argv) != 3:
        print("Usage: python3 smart_merge.py <origin_path> <destination_path>")
        print("\nMerges origin into destination:")
        print("  - Creates missing folders")
        print("  - Moves missing files")
        print("  - Keeps larger file when duplicates exist")
        sys.exit(1)

    origin = '/mnt/sims/BACKUP SIMS/Sims 4/Custom Content/New CC/NEW/Mods/CAS/'
    dest = '/mnt/sims/BACKUP SIMS/Sims 4/Custom Content/Backup ALL CC/1 CAS/'
    origin_path = Path(origin, sys.argv[1]).resolve()
    destination_path = Path(dest, sys.argv[2]).resolve()
    
    if not origin_path.exists():
        print(f"Error: Origin path does not exist: {origin_path}")
        sys.exit(1)
    
    if not origin_path.is_dir():
        print(f"Error: Origin path is not a directory: {origin_path}")
        sys.exit(1)
    
    # Warn if destination doesn't exist (will be created)
    if not destination_path.exists():
        print(f"Warning: Destination does not exist, will be created: {destination_path}")
    
    print(f"\n=== Smart Merge Started ===")
    print(f"Origin:      {origin_path}")
    print(f"Destination: {destination_path}")
    print("-" * 40)
    
    

    

    moved, overwritten, skipped = process_directory(log, origin_path, destination_path)
    
    print("-" * 40)
    print(f"\n=== Summary ===")
    print(f"Files moved:       {moved}")
    print(f"Files overwritten: {overwritten}")
    print(f"Files skipped:     {skipped}")
    print(f"Total processed:   {moved + overwritten + skipped}")


if __name__ == "__main__":
    main()