#!/usr/bin/env python3
r"""
organize_archive_files.py

Reorganizes files scattered across a drive into flat "toegangsnummer" folders,
driven by an Excel sheet that lists which (uuid, toegangsnummer, bestandsnaam)
combinations are supposed to exist.

------------------------------------------------------------------------
WHAT IT DOES
------------------------------------------------------------------------
1. Reads the Excel file and figures out the uuid / toegangsnummer / bestandsnaam
   columns (auto-detected, can be overridden with CLI flags).
2. Walks SOURCE_ROOT once, looking for any folder whose name STARTS WITH one
   of the archive numbers from the sheet (e.g. toegangsnummer "287" matches a
   folder named "287_001-<anything>", "287-<anything>", or just "287").
   Whatever comes after the archive number in the folder name (a sequence
   number, a uuid, anything else) is irrelevant and is not inspected at all.
   There can be several such folders for the same archive number -- all of
   them are used. The uuid column from the sheet is NEVER used to locate or
   verify anything on disk; it is carried through to the logs purely for
   your own reference, and may not correspond to the folder it's logged
   next to.
3. For every archive number the sheet actually needs, it walks *inside* all
   matching folders (any depth, any number of subfolders) and indexes every
   file found there.
4. For every row in the Excel file, it looks for the expected bestandsnaam
   inside that archive's combined file index:
     - Exact bestandsnaam match (case-insensitive) is tried first.
     - If found in more than one physical location, ALL copies are treated
       as genuine duplicates that both need to be transferred: each is
       moved into the destination folder, with the 2nd, 3rd, ... copy
       renamed with a "-2", "-3", ... suffix before the extension. This is
       flagged clearly in the logs so you can manually check whether they
       are really distinct files or true duplicates.
     - If no exact match exists, it falls back to matching on the bestandsnaam
       without its extension (in case the sheet omits extensions) -- but
       only when that resolves to exactly one physical file. If it matches
       more than one file with different extensions, nothing is moved for
       that row; it's logged as an error for manual review instead of being
       guessed at (this is a different, riskier kind of ambiguity than the
       same-name duplicates above, since different extensions could mean
       genuinely different files).
   Any file physically present on the drive that is NOT listed in the Excel
   sheet is never touched, matched, or moved -- only rows from the sheet are
   ever looked up.
5. Everything is logged:
      - success_log.csv    -> every file that was moved successfully
                               (includes a duplicate_group_size column)
      - duplicates_log.csv -> just the rows that were part of a same-name
                               duplicate group, for a quick manual check
      - error_log.csv      -> every file that could NOT be moved, and why
      - run_log_<ts>.log   -> full human-readable run log
      - a short console summary at the end

------------------------------------------------------------------------
IMPORTANT SAFETY NOTES
------------------------------------------------------------------------
- ALWAYS do a --dry-run first. It performs every step (including writing
  all logs) EXCEPT it doesn't touch any files. Check the logs, then re-run
  without --dry-run.
- Default action is MOVE. Pass --copy if you'd rather copy and keep the
  originals in place until you've verified everything.
- The script is safe to re-run: if a destination file already exists and is
  the same size as the source, it is skipped (not re-moved, not duplicated)
  and logged as "already present".
- File size is compared before/after every move/copy as a cheap integrity
  check. A mismatch is logged as an error rather than silently accepted.

------------------------------------------------------------------------
USAGE
------------------------------------------------------------------------
    python organize_archive_files.py \
        --excel "Q:\path\to\overview.xlsx" \
        --source "D:\drive_root" \
        --dest   "D:\organized_by_archive" \
        --dry-run

    # once you're happy with the dry run:
    python organize_archive_files.py \
        --excel "Q:\path\to\overview.xlsx" \
        --source "D:\drive_root" \
        --dest   "D:\organized_by_archive"

Optional flags:
    --sheet NAME_OR_INDEX     which sheet to read (default: first sheet)
    --uuid-col / --archive-col / --bestandsnaam-col
                              force column names if auto-detection fails
    --copy                    copy instead of move
    --dry-run                 simulate only, no file operations
    --log-dir PATH            where to write logs (default: ./logs)
"""

import argparse
import csv
import logging
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime

import pandas as pd

UUID_COL_CANDIDATES = ["uuid", "UUID"]
ARCHIVE_COL_CANDIDATES = [
    "TOEGANGSNUMMER", "toegangsnummer"
]
BESTANDSNAAM_COL_CANDIDATES = [
    "BESTANDSNAAM", "bestandsnaam"
]


LEADING_TOKEN_RE = re.compile(r"^([A-Za-z0-9]+)")
unique_paths = set()

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def find_column(columns, candidates):
    normalized = {col: norm(col) for col in columns}
    cand_norm = [norm(c) for c in candidates]
    for col, n in normalized.items():
        if n in cand_norm:
            return col
    return None


def clean_toegangsnummer(value):
    """Excel sometimes turns '287' into 287.0 -- undo that, keep everything
    else (leading zeros, alphanumeric archive numbers, etc.) untouched."""
    s = str(value).strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s


def sanitize_folder_name(name):
    """Strip characters that are illegal in Windows folder names, just in
    case an toegangsnummer ever contains something unexpected."""
    return re.sub(r'[<>:"/\\|?*]', "_", str(name)).strip()


def leading_token(name):
    """The leading contiguous alphanumeric run of a folder name, e.g.
    '287_001-ba17...' -> '287'. This is what we match archive numbers
    against -- nothing else in the folder name matters."""
    m = LEADING_TOKEN_RE.match(name)
    return m.group(1) if m else None


def setup_logging(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    log_file = f'logs/dam_supp {str(current_datetime)}.log'

    logger = logging.getLogger("organizer")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger, log_file


# --------------------------------------------------------------------------
# READ EXCELL AND FIND COLUMNS AND FILES
# --------------------------------------------------------------------------
def load_excel(path, sheet, uuid_col, archive_col, bestandsnaam_col, logger):
    logger.info(f"Reading Excel file: {path}")
    df = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    uuid_col = uuid_col or find_column(df.columns, UUID_COL_CANDIDATES)
    archive_col = archive_col or find_column(df.columns, ARCHIVE_COL_CANDIDATES)
    bestandsnaam_col = bestandsnaam_col or find_column(df.columns, BESTANDSNAAM_COL_CANDIDATES)

    missing = [
        name for name, col in
        [("uuid", uuid_col), ("toegangsnummer", archive_col), ("bestandsnaam", bestandsnaam_col)]
        if col is None
    ]
    if missing:
        raise SystemExit(
            f"Could not auto-detect column(s): {missing}. "
            f"Available columns are: {list(df.columns)}. "
            f"Re-run with --uuid-col / --archive-col / --bestandsnaam-col to specify them manually."
        )

    logger.info(f"Using columns -> uuid: '{uuid_col}', toegangsnummer: '{archive_col}', bestandsnaam: '{bestandsnaam_col}'")

    df = df[[uuid_col, archive_col, bestandsnaam_col]].copy()
    df.columns = ["uuid", "toegangsnummer", "bestandsnaam"]

    '''before = len(df)
    df = df.dropna(subset=["uuid", "toegangsnummer", "bestandsnaam"])
    df["uuid"] = df["uuid"].astype(str).str.strip()
    df["toegangsnummer"] = df["toegangsnummer"].apply(clean_toegangsnummer)
    df["bestandsnaam"] = df["bestandsnaam"].astype(str).str.strip()
    df = df[(df["uuid"] != "") & (df["toegangsnummer"] != "") & (df["bestandsnaam"] != "")]'''

    df["uuid"] = df["uuid"].astype(str).str.strip()
    df["toegangsnummer"] = df["toegangsnummer"].apply(clean_toegangsnummer)
    df["bestandsnaam"] = df["bestandsnaam"].astype(str).str.strip()
    for index, row in df.iterrows():
        missing_uuid = row.uuid == ""
        missing_toegansnr = row.toegangsnummer == ""
        missing_bestandsnaam = row.bestandsnaam == ""
        if missing_uuid:
            logger.warning(f"row {missing_uuid} has missing values.")
        if missing_toegansnr:
            logger.warning(f"row {missing_toegansnr} has missing values.")
        if missing_bestandsnaam:
            logger.warning(f"row {missing_bestandsnaam} has missing values.")

    #dropped = before - len(df)
    #if dropped:
        
    ## LOOK FOR FILES IN DIFFERENT ARCHIVES LOGIC -->> ADJUST
    dup_mask = df.duplicated(subset=["uuid", "toegangsnummer", "bestandsnaam"], keep="first")
    if dup_mask.any():
        logger.warning(f"Found {dup_mask.sum()} exact duplicate row(s) in the sheet; keeping the first occurrence of each.")
        df = df[~dup_mask]

    nr_of_uuid = []
    nr_of_uuid.append(str(df['uuid'].unique()))

    logger.info(f"Loaded {len(df)} row(s) covering {len(nr_of_uuid)} unique uuid(s) " #{df['uuid'].nunique()}
                f"and {df['toegangsnummer'].nunique()} unique toegangsnummer(s).")
    return df

# --------------------------------------------------------------------------
# INDEX ALL FOLDERS BELONGING TO TOEGANGSNUMMERS ON THE SOURCE PATH
# --------------------------------------------------------------------------
def find_archive_folders(source_root, archive_numbers, logger):
    """Scan all directories in source_root and log all toegangsnummers present in it.  
    It ignores all trailing information after the digits in the directory name and all found 
    directories with toegangsnummers are logged in a list per toegangsnummer. 
    The filenames are not indexed here. that is done separately in index_files_for_archive()
    Returns a dictionary with lists of all found DIRECTORY paths per toegangsnunmmers"""

    logger.info(f"Scanning {source_root} for toegangsnummer directories (this can take a while on large drives)...")

    archive_set = set(archive_numbers)
    normalized_lookup = defaultdict(list)
    # 287 matches 287 not 2870. 2870 matches 2870 not 28700 etc.
    for a in archive_set:
        normalized_lookup[a.lstrip("0") or "0"].append(a)

    archive_folders = defaultdict(list)
    matched_dirs = 0

    for dirpath, dirnames, _bestandsnamen in os.walk(source_root):
        keep = []
        for d in dirnames:
            token = leading_token(d)
            matched_archive = None
            if token is not None:
                if token in archive_set:
                    matched_archive = token
                else:
                    norm_token = token.lstrip("0") or "0"
                    candidates = normalized_lookup.get(norm_token)
                    if candidates and len(candidates) == 1:
                        matched_archive = candidates[0]

            if matched_archive is not None:
                full = os.path.join(dirpath, d)
                archive_folders[matched_archive].append(full)
                matched_dirs += 1
            else:
                keep.append(d)
        dirnames[:] = keep

    logger.info(f"Found {matched_dirs} matching folder(s) on the drive, covering {len(archive_folders)} "
                f"distinct archive number(s).")
    
    return archive_folders

# --------------------------------------------------------------------------
# INDEX ALL BESTANDSNAMEN PER FOUND DIRECTORY ON THE SOURCE_ROOT 
# --------------------------------------------------------------------------
def index_files_for_archive(archive_roots, logger):
    """Recursively index every file under all folders belonging to one
    archive number. Returns a dict: exact bestandsnaam (lowercased) ->
    [full paths]"""
    by_name = defaultdict(list)
    # SORT PER TOEGANSNUMMER IN THE DICTIONARY
    for toegangsnummer in archive_roots:
        # SORT PER PATH, TOEGANGSFOLDER UNDERNEATH [THERE CAN BE MORE PER TOEGANGSNUMMER], 
        # ALL FILES IN THOSE TOEGANGSNUMMERS 
        for dirpath, _dirnames, bestandsnamen in os.walk(toegangsnummer):
            # SORT PER FILE FOUND IN THE POOL OF FILES
            for file in bestandsnamen:
                full = os.path.join(dirpath, file)               
                ''' NOTE PRINT TO SEE IF THIS WORKS'''
                # CREATE A LIST OF ALL FOUND FILES AND ADD EACH OF THOSE FOUND FILES TO IT
                '''NOTE IT LOOKS LIKE WE ARE ADDING THE FILES TO A LIST [PER FILE]
                BUT WE ARE TELLING IT TO CREATE A LIST OF THE FILES. WE ARE ADDING IT 
                TO THE DICTIONARY OF TOEGANGSNUMMERS. WE ARE TELLING IT TO DO SO BY
                THE FOR LOOP AT THE START OF THIS HELPER FUNCTION'''
                by_name[file].append(file)               
                print(by_name)

    # returns a dictionary of lists with files sorted per toegangsnummer           
    return by_name

# --------------------------------------------------------------------------
# MATCH BESTANDSNAMEN IN THE EXCEL SHEET TO ALL FILES FOUND ON THE SOURCE 
# --------------------------------------------------------------------------
def match_file(bestandsnaam, by_name):
    """Only ever resolves to file(s) that match the sheet's bestandsnaam.
    Returns (candidates, match_type):
        match_type = "exact"           -> exactly one exact bestandsnaam match
        match_type = "exact_duplicate" -> exact bestandsnaam matched MORE THAN
                                           ONCE in different locations within
                                           this archive -- these are treated
                                           as genuine files that both need to
                                           be transferred (flagged for manual
                                           review, not blocked)
    Every other file physically present that is NOT listed in the sheet is
    never touched, matched, or considered.
    """
    # Bestansdsnaam on the excell sheet
    key = bestandsnaam
    # if bestandsnaam is found in the dictionary of source directories
    if key in by_name:
        # bestandsnaam is added to a list per toegangsnummer stored in 'candidates'
        candidates = by_name[key]
        # find the first unused candidate
        for path in candidates:
            if path not in unique_paths:
                unique_paths.add(path)
                return [path], "exact"
        return candidates, "exact_duplicate"


    return [], "none"


'''def safe_destination(dest_dir, bestandsnaam):
    """If bestandsnaam already exists in dest_dir for a reason unrelated to the
    intentional duplicate-suffixing below (e.g. re-running the script),
    append _dup1, _dup2, ... so we never silently overwrite a different
    file."""
    dest_path = os.path.join(dest_dir, bestandsnaam)
    if not os.path.exists(dest_path):
        return dest_path, False
    stem, ext = os.path.splitext(bestandsnaam)
    i = 1
    while True:
        candidate = os.path.join(dest_dir, f"{stem}_dup{i}{ext}")
        if not os.path.exists(candidate):
            return candidate, True
        i += 1'''

###### alter to check for duplicate files in whole folder
def duplicate_dest_name(basename, index):
    """index is 0 for the first (original) copy, 1, 2, ... for the rest.
    First copy keeps its name; subsequent copies get a '-2', '-3', ...
    suffix before the extension, as requested."""
    if index == 0:
        return basename
    stem, ext = os.path.splitext(basename)
    return f"{stem}-{index + 1}{ext}"


'''def transfer_one(src, dest_dir, dest_name, mode, dry_run, logger, allow_rename_on_collision=True):
    """Moves/copies a single file into dest_dir/dest_name, handling name
    collisions and a size-based integrity check. Returns (dest_path, status_str)."""
    if not dry_run:
        os.makedirs(dest_dir, exist_ok=True)

    dest_path = os.path.join(dest_dir, dest_name)

    if not dry_run and os.path.exists(dest_path):
        if os.path.getsize(dest_path) == os.path.getsize(src):
            return dest_path, "already present (skipped)"
        if allow_rename_on_collision:
            dest_path, renamed = safe_destination(dest_dir, dest_name)
            if renamed:
                logger.warning(f"Name collision for '{dest_name}' in {dest_dir}; "
                                f"saved as '{os.path.basename(dest_path)}' instead.")

    if dry_run:
        return dest_path, f"DRY RUN - would {'copy' if mode == 'copy' else 'move'}"

    src_size = os.path.getsize(src)
    if mode == "copy":
        shutil.copy2(src, dest_path)
    else:
        shutil.move(src, dest_path)
    dest_size = os.path.getsize(dest_path)
    if dest_size != src_size:
        raise IOError(f"size mismatch after transfer: source {src_size} bytes, dest {dest_size} bytes")
    return dest_path, ("moved" if mode == "move" else "copied")'''

# --------------------------------------------------------------------------
# WRITE TO EXCEL FILE
# --------------------------------------------------------------------------

def resolve_sheet(wb, sheet_arg, logger):
    if sheet_arg is None:
        ws = wb.worksheets[0]
        logger.info(f"Using first sheet: '{ws.title}'")
        return ws
    # try as an integer index first, then fall back to a name lookup
    try:
        idx = int(sheet_arg)
        ws = wb.worksheets[idx]
        logger.info(f"Using sheet at index {idx}: '{ws.title}'")
        return ws
    except (ValueError, IndexError):
        pass
    if sheet_arg in wb.sheetnames:
        ws = wb[sheet_arg]
        logger.info(f"Using sheet: '{ws.title}'")
        return ws
    raise SystemExit(f"Sheet '{sheet_arg}' not found. Available sheets: {wb.sheetnames}")


def find_header_col(ws, header_row, candidates):
    """Returns the 1-based column index of the first header cell (in
    header_row) whose normalized text matches one of candidates, or
    None if not found."""
    cand_norm = [norm(c) for c in candidates]
    for cell in header_row:
        if cell.value is not None and norm(cell.value) in cand_norm:
            return cell.column
    return None

def update_excel(excel_path, sheet_arg, status_map, excel_filename_col_override,
                  status_col_name, output_path, logger):
    logger.info(f"Reading Excel file: {excel_path}")
    wb = load_workbook(excel_path)
    ws = resolve_sheet(wb, sheet_arg, logger)

    header_row = next(ws.iter_rows(min_row=1, max_row=1))

    if excel_filename_col_override:
        filename_col_idx = find_header_col(ws, header_row, [excel_filename_col_override])
    else:
        filename_col_idx = find_header_col(ws, header_row, FILENAME_COL_CANDIDATES)

    if filename_col_idx is None:
        headers = [c.value for c in header_row]
        raise SystemExit(
            f"Could not find a filename column in the Excel sheet's header row. "
            f"Available headers: {headers}. Re-run with --excel-filename-col to specify it manually."
        )

    status_col_idx = find_header_col(ws, header_row, [status_col_name])
    if status_col_idx is None:
        status_col_idx = ws.max_column + 1
        ws.cell(row=1, column=status_col_idx, value=status_col_name)
        logger.info(f"Added new column '{status_col_name}' at column {status_col_idx}.")
    else:
        logger.info(f"Column '{status_col_name}' already exists at column {status_col_idx}; reusing it.")

    matched_rows = 0
    for row in ws.iter_rows(min_row=2):
        filename_cell = row[filename_col_idx - 1]
        if filename_cell.value is None:
            continue
        key = normalize_filename(filename_cell.value)
        if key in status_map:
            ws.cell(row=filename_cell.row, column=status_col_idx, value=status_map[key])
            matched_rows += 1

    logger.info(f"Wrote '{status_col_name}' for {matched_rows} row(s) in the Excel sheet "
                f"(out of {len(status_map)} distinct filenames from the CSV -- some may not appear "
                f"in this sheet/tab at all, which is expected).")

    wb.save(output_path)
    logger.info(f"Saved: {output_path}")


def process(df, source_root, excel_path, sheet_arg ,logger):
    successes = []  # dicts for success_log.csv
    errors = []     # dicts for error_log.csv

    # All toegangsnummers found on the excel sheet
    needed_archives = sorted(df["toegangsnummer"].unique())
    # A dictionary with a list of all found directories per toegangsnummer 
    archive_folders = find_archive_folders(source_root, needed_archives, logger)

    # Match the excel dataframe with the dictionary of found directories
    missing_toegangsnummer = []
    file_indexes = {}  
    # Loop through excel to find toegangsnummers 
    for i, toegangsnummer in enumerate(needed_archives, 1):
        # Loop through folders to find toegangsnummers
        if toegangsnummer not in archive_folders:
            missing_toegangsnummer.append(toegangsnummer)            
            continue
        # Loop to Log progress for every 200 toegangsnummers scanned
        if i % 200 == 0 or i == len(needed_archives):
            logger.info(f"Indexed files for {i}/{len(needed_archives)} needed archive folders...")
        ''' NOTE WATCH OUT!!! THE RETURN OBJECT IS A VARIABLE 'BY_NAME', BUT WE ARE NOT USING THAT HERE YET
        INSTEAD WE USE THE DICTIONARY WITH LISTS AS CONFIGURED IN THE FUNCTION. 
        WE DO THIS BECAUSE WE NEED THIS CONFIGURATION IN A FEW MORE STATEMENTS
        LATER ON WE RESTATE THE VARIABLE file_indexes[toegangsnummer] BACK TO THE VARIABLE
        by_name'''
        # Look through all the found toegangsnummer directories and return a dict with 
        # lists of files in those toegangsnummers
        file_indexes[toegangsnummer] = index_files_for_archive(archive_folders[toegangsnummer], logger)

    # Find the NUMBER of missing toegangsnummers by subtracting the unique neeeded minus the found
    missing_archive_folders = set(needed_archives) - set(archive_folders.keys())
    if missing_archive_folders:
        logger.warning(f"{len(missing_archive_folders)} archive number(s) from the sheet were not found "
                        f"as folders on the drive at all."
                        f"These are: {missing_toegangsnummer}")

    # Indexing of rows and filenames in the dataframe
    total = len(df)
    for n, row in enumerate(df.itertuples(index=False), 1):
        toegangsnummer, bestandsnaam = row.toegangsnummer, row.bestandsnaam
        
        # Log progress every 5000 rows
        if n % 5000 == 0 or n == total:
            logger.info(f"Processed {n}/{total} rows "
                        f"({len(successes)} moved, {len(errors)} errors so far)...")

        # Logging missing toegangsnummers
        if toegangsnummer not in archive_folders:
            errors.append({
                "toegangsnummer": toegangsnummer, "bestandsnaam": bestandsnaam,
                "reason": "archive folder not found on drive",
            })
            continue

        '''NOTE HERE THE VARIABLE IS RETURNED TO THE NAME 'by_name'. SEE ABOVE NOTE FOR EXPLANATION'''
        # Dictionary of lists of toegangsnummers with all files found on the source
        by_name= file_indexes[toegangsnummer]
        write_excel = defaultdict(list) 
        # Find matching files with excell sheet in the dictionary
        candidates, match_type = match_file(bestandsnaam, by_name)
        if match_type == "none":
            write_excel[toegangsnummer].append({'filenames' : candidates, 'reason' : match_type})  
            errors.append({
                "toegangsnummer": toegangsnummer, "bestandsnaam": bestandsnaam,
                "reason": "file not found inside archive folder(s)",
            })
            continue

        '''if match_type == "ambiguous":
            errors.append({
                "toegangsnummer": toegangsnummer, "uuid": uuid, "bestandsnaam": bestandsnaam,
                "reason": f"ambiguous match - {len(candidates)} files with different extensions found "
                          f"matching '{bestandsnaam}' ({', '.join(candidates)}) - skipped, needs manual review",
            })
            continue'''

        if match_type == "exact_duplicate":
            errors.append({
                "toegangsnummer": toegangsnummer, "bestandsnaam": bestandsnaam,
                "reason": f"duplicate match - {len(candidates)} duplicate files found "
                          f"matching '{bestandsnaam}' ({', '.join(candidates)}) - needs manual review",
            })
            continue

        # match_type is "exact", "exact_duplicate", or "stem" here.
        dest_dir = os.path.join(dest_root, sanitize_folder_name(toegangsnummer))
        group_size = len(candidates)

        for idx, src in enumerate(candidates):
            try:
                src_basename = os.path.basename(src)
                dest_name = duplicate_dest_name(src_basename, idx) if group_size > 1 else src_basename
                # for duplicate copies beyond the first, the -2/-3 suffix already makes
                # the name unique, so don't let a stray same-name file cause a rename
                allow_rename = not (group_size > 1 and idx > 0)
                dest_path, status = transfer_one(src, dest_dir, dest_name, mode, dry_run, logger,
                                                  allow_rename_on_collision=allow_rename)

                successes.append({
                    "toegangsnummer": toegangsnummer, "uuid": uuid,
                    "bestandsnaam_expected": bestandsnaam, "file_found": src_basename,
                    "source_path": src, "dest_path": dest_path,
                    "status": status, "match_type": match_type,
                    "duplicate_group_size": group_size,
                })

            except Exception as e:
                errors.append({
                    "toegangsnummer": toegangsnummer, "uuid": uuid, "bestandsnaam": bestandsnaam,
                    "reason": f"error during transfer of copy {idx + 1}/{group_size} ('{src}'): {e}",
                })

    return successes, errors

def safe_str(value):
    return "" if pd.isna(value) else str(value)

def write_success_log(successes, path): 
    print("write_success_log called")
    successes_sorted = sorted(
    successes,
    key=lambda r: (
        safe_str(r["uuid"]),
        safe_str(r["toegangsnummer"]),
        safe_str(r["bestandsnaam_expected"])))
    fieldnames= [
            "uuid", "toegangsnummer","bestandsnaam_expected", "file_found",
            "source_path", "dest_path", "status", "match_type", "duplicate_group_size",
        ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";" )
        #print("Delimiter:", repr(writer.dialect.delimiter))
        writer.writeheader()
        writer.writerows(successes_sorted)


def write_duplicates_log(successes, path):
    dup_rows = [r for r in successes if r["duplicate_group_size"] > 1]
    dup_rows_sorted = sorted(dup_rows, key=lambda r: (safe_str(r["uuid"]), safe_str(r["toegangsnummer"]), safe_str(r["bestandsnaam_expected"]), r["dest_path"]))
    fieldnames = ["toegangsnummer", "uuid", "bestandsnaam_expected", "file_found", "source_path", "dest_path", "duplicate_group_size"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows({k: r[k] for k in fieldnames} for r in dup_rows_sorted)
    return len(dup_rows_sorted)


def write_error_log(errors, path):
    errors_sorted = sorted(errors, key=lambda r: (safe_str(r["uuid"]), safe_str(r["toegangsnummer"]), safe_str(r["bestandsnaam"])))
    fieldnames=["toegangsnummer", "uuid", "bestandsnaam", "reason"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(errors_sorted)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Find files in folder and update excel sheet accordingly.")
    parser.add_argument("--excel", required=True, help="Path to the Excel file")
    parser.add_argument("--sheet", default=None, help="Sheet name or index (default: first sheet)")
    parser.add_argument("--source", required=True, help="Root folder to search for archive folders")
    '''parser.add_argument("--dest", required=True, help="Root folder where toegangsnummer folders will be created")'''
    '''parser.add_argument("--uuid-col", default=None, help="Override: name of the uuid column")'''
    parser.add_argument("--archive-col", default=None, help="Override: name of the toegangsnummer column")
    parser.add_argument("--bestandsnaam-col", default=None, help="Override: name of the bestandsnaam column")
    '''parser.add_argument("--copy", action="store_true", help="Copy instead of move")'''
    '''parser.add_argument("--dry-run", action="store_true", help="Simulate only, no files are touched")'''
    parser.add_argument("--log-dir", default="./logs", help="Directory for log/CSV output (default: ./logs)")
    parser.add_argument("--export-dir", default="./export", help="Directory for log/CSV output (default: ./export)")
    args = parser.parse_args()

    logger, log_file = setup_logging(args.log_dir)
    # Check if file already exists and delete based on env
    if not os.path.exists("./logs"):     
       os.makedirs("./logs")
       logger.info(f'Log directory did not exist. Logs directory created') 
    if not os.path.exists("./export"):     
       os.makedirs("./export")
       logger.info(f'Export directory did not exist. Export directory created') 
    '''mode = "copy" if args.copy else "move"'''

    '''logger.info(f"Mode: {mode.upper()}{'  (DRY RUN - no files will be touched)' if args.dry_run else ''}")'''
    logger.info(f"Source: {args.source}")
    logger.info(f"Destination: {args.dest}")

    if not os.path.isdir(args.source):
        raise SystemExit(f"Source folder does not exist: {args.source}")
    '''if not args.dry_run:
        os.makedirs(args.dest, exist_ok=True)'''

    df = load_excel(args.excel, args.sheet, args.archive_col, args.bestandsnaam_col, logger)

    successes, errors = process(df, args.source, args.excel, args.sheet, logger)

    current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    success_csv = os.path.join(args.export_dir, f"success_log{str(current_datetime)}.csv")
    error_csv = os.path.join(args.export_dir, f"error_log{str(current_datetime)}.csv")
    duplicates_csv = os.path.join(args.export_dir, f"duplicates_log{str(current_datetime)}.csv")
    write_success_log(successes, success_csv)
    write_error_log(errors, error_csv)
    dup_count = write_duplicates_log(successes, duplicates_csv)

    archives_touched = len({s["toegangsnummer"] for s in successes})
    logger.info("=" * 70)
    logger.info("RUN SUMMARY")
    logger.info(f"  Total rows in sheet processed : {len(df)}")
    logger.info(f"  Successfully moved/copied     : {len(successes)}")
    logger.info(f"  Of which same-name duplicates : {dup_count}  (see duplicates_log.csv)")
    logger.info(f"  Errors / missing files        : {len(errors)}")
    logger.info(f"  Archive folders touched       : {archives_touched}")
    logger.info(f"  Success log (CSV)             : {success_csv}")
    logger.info(f"  Duplicates log (CSV)          : {duplicates_csv}")
    logger.info(f"  Error log (CSV)               : {error_csv}")
    logger.info(f"  Full run log                  : {log_file}")
    logger.info("=" * 70)
    if args.dry_run:
        logger.info("This was a DRY RUN. No files were moved or copied. Review the logs, "
                     "then re-run without --dry-run when you're confident.")


if __name__ == "__main__":
    main()