#!/usr/bin/env python3
"""
Duplicate Finder - Find files with duplicate names across a directory tree.
Outputs results to CSV sorted by filename groups.

Usage: python3 find_duplicates.py <search_location> [match_percentage]
       match_percentage: 1-100 (default: 100 = exact match)
"""

import sys
import os
import csv
import argparse
from pathlib import Path
from collections import defaultdict
HOME_REPO = Path("/opt/lampp/htdocs/test/scripts")
sys.path.append(str(HOME_REPO))
from general import file_and_log_management

# Type alias for clarity
FileEntry = tuple[str, str, int]  # (name, path, size)

project = 'duplicate_files_finder'
projectname = 'find_duplicate_files'

def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def calculate_similarity(name1: str, name2: str, max_len: int) -> float:
    """Return similarity as percentage (100 = identical)."""
    distance = levenshtein_distance(name1, name2)
    if max_len == 0:
        return 100.0
    similarity = ((max_len - distance) / max_len) * 100
    return round(similarity, 2)


def group_by_similarity(files: list[FileEntry], threshold: float) -> list[list[FileEntry]]:
    """Group files by filename similarity above threshold."""
    used = set()
    groups: list[list[FileEntry]] = []
    
    files_sorted = sorted(files, key=lambda x: x[0].lower())
    
    for i in range(len(files_sorted)):
        if i in used:
            continue
        
        file1 = files_sorted[i]
        name1, path1, size1 = file1
        
        group = [file1]
        used.add(i)
        
        for j in range(i + 1, len(files_sorted)):
            if j in used:
                continue
            
            file2 = files_sorted[j]
            name2, path2, size2 = file2
            
            max_len = max(len(name1), len(name2))
            similarity = calculate_similarity(name1, name2, max_len)
            
            if similarity >= threshold:
                group.append(file2)
                used.add(j)
        
        if len(group) > 1:
            groups.append(group)
    
    return groups


def find_files(root: Path) -> list[FileEntry]:
    """Walk directory tree and collect all files with name, path, size."""
    files: list[FileEntry] = []
    
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            file_path = Path(dirpath) / filename
            try:
                file_size = os.path.getsize(file_path)
                files.append((filename, str(file_path.resolve()), file_size))
            except OSError as e:
                print(f"[WARNING] Could not access {file_path}: {e}", file=sys.stderr)
    
    return files


def write_csv(groups: list[list[FileEntry]], output_path: str):
    """Write duplicate groups to CSV file."""
    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        if not groups:
            writer = csv.writer(csvfile)
            writer.writerow(['note'])
            writer.writerow(['No duplicate files found'])
            return
        
        # Build dynamic header based on max number of duplicates in any group
        max_cols = max(len(g) for g in groups)
        header = []
        for i in range(max_cols):
            header.extend([f'name_{i+1}', f'location_{i+1}', f'size_{i+1}'])
        
        writer = csv.writer(csvfile)
        writer.writerow(header)
        
        for group in groups:
            row = []
            for name, path, size in group:
                row.extend([name, path, size])
            writer.writerow(row)


def main():

    log, error_file, backup_file, out_file = file_and_log_management.setup_logging('private', projectname, project)

    parser = argparse.ArgumentParser(
        description="Find duplicate files by name across a directory tree."
    )
    
    parser.add_argument("location", type=str, help="Directory to search for duplicates")
    parser.add_argument(
        "--match", "-m", 
        type=int, 
        default=100,
        help="Match percentage (default: 100 for exact filename match)"
    )
    
    args = parser.parse_args()
    
    # Validate match percentage
    if not (1 <= args.match <= 100):
        print("Error: Match percentage must be between 1 and 100")
        sys.exit(1)

    start = '/mnt/files'
    search_location = Path(start, args.location).resolve()
    
    if not search_location.exists():
        print(f"Error: Search location does not exist: {search_location}")
        sys.exit(1)
    
    if not search_location.is_dir():
        print(f"Error: Path is not a directory: {search_location}")
        sys.exit(1)
    
    match_threshold = args.match
    
    print(f"\n=== Duplicate Finder ===")
    print(f"Search location: {search_location}")
    print(f"Match threshold: {match_threshold}%")
    print(f"Output file:     {out_file}")
    print("-" * 40)
    print("Scanning files...")
    
    files = find_files(search_location)
    print(f"Total files scanned: {len(files)}")
    
    if len(files) == 0:
        print("No files found to analyze.")
        return
    
    groups = group_by_similarity(files, match_threshold)
    print(f"Duplicate groups found: {len(groups)}")
    
    write_csv(groups, out_file)
    print(f"Results written to: {args.output}")
    
    total_duplicates = sum(len(g) for g in groups)
    print(f"Total duplicate files: {total_duplicates}")
    
    if groups:
        print("\nTop 5 largest duplicate groups:")
        sorted_groups = sorted(groups, key=lambda g: max(f[2] for f in g), reverse=True)[:5]
        for i, group in enumerate(sorted_groups, 1):
            names = [f[0] for f in group]
            sizes = [f[2] for f in group]
            print(f"  {i}. '{names[0]}' ({len(group)} copies, {max(sizes)} bytes max)")
            for name, path, size in group[:3]:
                print(f"     - {path} ({size} bytes)")
            if len(group) > 3:
                print(f"     - ... and {len(group)-3} more")


if __name__ == "__main__":
    main()