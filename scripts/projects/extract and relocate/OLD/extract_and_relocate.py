#!/usr/bin/env python3
r"""
organize_archive_files.py

Reorganizes files scattered across a drive into flat "accessnumber" folders,
driven by an Excel sheet that lists which (uuid, accessnumber, file_name)
combinations are supposed to exist.

------------------------------------------------------------------------
NEW: OPTIONAL EXTRACTION STAGE
------------------------------------------------------------------------
If you pass --compressed-source, the script first walks that folder,
detects every ZIP / TAR (.tar, .tar.gz/.tgz, .tar.bz2/.tbz2, .tar.xz/.txz)
/ 7Z file it finds (by extension), and extracts each one into its own
subfolder under --source, named after the archive file (extension
stripped). That means an archive like "287_001-<uuid>.zip" becomes a
folder "287_001-<uuid>/" under --source -- which is exactly the folder
naming pattern the rest of the script already expects (it matches on the
leading alphanumeric token of the folder name). Once extraction is done,
the script proceeds exactly as before, scanning --source for archive
folders and moving files according to the Excel sheet.

7Z extraction requires the third-party 'py7zr' package:
    pip install py7zr
ZIP and TAR (and its compressed variants) are handled by the standard
library, no extra install needed.

Extraction is safe to re-run: if a target folder already exists and is
non-empty, that archive is skipped (assumed already extracted).
Extraction successes/failures are written to their own log files
(extract_log_<ts>.csv / extract_errors_<ts>.csv) in --export-dir.

------------------------------------------------------------------------
WHAT THE REST OF THE SCRIPT DOES (unchanged)
------------------------------------------------------------------------
1. Reads the Excel file and figures out the uuid / accessnumber / file_name
   columns (auto-detected, can be overridden with CLI flags).
2. Walks SOURCE_ROOT once, looking for any folder whose name STARTS WITH one
   of the archive numbers from the sheet (e.g. accessnumber "287" matches a
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
4. For every row in the Excel file, it looks for the expected file_name
   inside that archive's combined file index:
     - Exact file_name match (case-insensitive) is tried first. Each
       physical file can only be claimed by one sheet row; if the sheet
       needs the same name more than once and there are that many distinct
       physical copies, each row gets its own copy in turn. Once every
       physical copy of that name has already been claimed by earlier rows,
       any further row asking for it is flagged as "exact_duplicate" for
       manual review instead of being silently reused.
     - If no exact match exists, it falls back to matching on the file_name
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
  NOTE: --dry-run currently still runs real extraction if you pass
  --compressed-source, since the file-matching stage needs the files on
  disk to find anything at all. Extraction only ever reads the archives
  (it never modifies or deletes them), so this is safe, but be aware it
  will still write extracted files to --source even during a dry run of
  the move/copy stage.
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
    # with an extraction stage first:
    python organize_archive_files.py \
        --excel "Q:\path\to\overview.xlsx" \
        --compressed-source "D:\incoming_archives" \
        --source "D:\drive_root_extracted" \
        --dest   "D:\organized_by_archive" \
        --dry-run

    # without extraction (old behaviour, --source already has plain folders):
    python organize_archive_files.py \
        --excel "Q:\path\to\overview.xlsx" \
        --source "D:\drive_root" \
        --dest   "D:\organized_by_archive" \
        --dry-run

    # once you're happy with the dry run:
    python organize_archive_files.py \
        --excel "Q:\path\to\overview.xlsx" \
        --compressed-source "D:\incoming_archives" \
        --source "D:\drive_root_extracted" \
        --dest   "D:\organized_by_archive"

Optional flags:
    --sheet NAME_OR_INDEX     which sheet to read (default: first sheet)
    --uuid-col / --archive-col / --file_name-col
                              force column names if auto-detection fails
    --compressed-source PATH  folder containing ZIP/TAR/7Z archives to
                              extract into --source before the rest of
                              the script runs (omit to skip extraction)
    --no-skip-extracted       re-extract even if the target folder for an
                              archive already exists and is non-empty
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
import tarfile
import zipfile
from collections import defaultdict
from datetime import datetime

import pandas as pd

try:
    import py7zr
    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False

UUID_COL_CANDIDATES = ["uuid", "UUID"]
ARCHIVE_COL_CANDIDATES = [
    "accessnumber", "accessnumber"
]
file_name_COL_CANDIDATES = [
    "file_name", "file_name"
]

# Extensions recognized during the extraction stage, longest-first so that
# compound extensions like ".tar.gz" are stripped correctly before falling
# back to simple ones like ".tar".
COMPOUND_ARCHIVE_EXTS = (".tar.gz", ".tar.bz2", ".tar.xz")
SIMPLE_ARCHIVE_EXTS = (".tgz", ".tbz2", ".txz", ".tar", ".zip", ".7z")


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


def clean_accessnumber(value):
    """Excel sometimes turns '287' into 287.0 -- undo that, keep everything
    else (leading zeros, alphanumeric archive numbers, etc.) untouched."""
    s = str(value).strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s


def sanitize_folder_name(name):
    """Strip characters that are illegal in Windows folder names, just in
    case an accessnumber (or an archive-derived folder name) ever contains
    something unexpected."""
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
# extraction stage (new)
# --------------------------------------------------------------------------

def detect_archive_type(filename):
    """Returns 'zip', 'tar', '7z', or None (not a recognized archive)."""
    lower = filename.lower()
    if lower.endswith(COMPOUND_ARCHIVE_EXTS):
        return "tar"
    if lower.endswith((".tgz", ".tbz2", ".txz", ".tar")):
        return "tar"
    if lower.endswith(".zip"):
        return "zip"
    if lower.endswith(".7z"):
        return "7z"
    return None


def archive_target_name(filename):
    """Strips the archive extension to get the folder name it will be
    extracted into, e.g. '287_001-<uuid>.tar.gz' -> '287_001-<uuid>'."""
    lower = filename.lower()
    for ext in COMPOUND_ARCHIVE_EXTS + SIMPLE_ARCHIVE_EXTS:
        if lower.endswith(ext):
            return filename[: -len(ext)]
    return os.path.splitext(filename)[0]


def find_archives(compressed_source, logger):
    logger.info(f"Scanning {compressed_source} for ZIP/TAR/7Z archives...")
    archives = []
    for dirpath, _dirnames, file_names in os.walk(compressed_source):
        for fn in file_names:
            if detect_archive_type(fn):
                archives.append(os.path.join(dirpath, fn))
    logger.info(f"Found {len(archives)} archive(s) to extract.")
    return archives


def extract_one(archive_path, dest_dir, atype, logger):
    """Extracts a single archive into dest_dir. Raises on failure."""
    os.makedirs(dest_dir, exist_ok=True)
    if atype == "zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest_dir)
    elif atype == "tar":
        # tarfile.open with default mode "r" auto-detects gz/bz2/xz
        # compression, so this covers .tar, .tar.gz/.tgz, .tar.bz2/.tbz2,
        # and .tar.xz/.txz alike.
        with tarfile.open(archive_path) as tf:
            tf.extractall(dest_dir)
    elif atype == "7z":
        if not HAS_PY7ZR:
            raise RuntimeError(
                "py7zr is not installed; run 'pip install py7zr' to enable .7z extraction"
            )
        with py7zr.SevenZipFile(archive_path, mode="r") as zf:
            zf.extractall(path=dest_dir)
    else:
        raise RuntimeError(f"unrecognized archive type for {archive_path}")


def extract_archives(compressed_source, extract_to, logger, skip_existing=True):
    """Walks compressed_source, extracts every recognized archive into its
    own subfolder of extract_to (named after the archive, extension
    stripped). Returns (successes, errors) lists of dicts for logging."""
    archives = find_archives(compressed_source, logger)
    successes = []
    errors = []

    for i, archive_path in enumerate(archives, 1):
        fn = os.path.basename(archive_path)
        atype = detect_archive_type(fn)
        target_name = sanitize_folder_name(archive_target_name(fn))
        target_dir = os.path.join(extract_to, target_name)

        if i % 50 == 0 or i == len(archives):
            logger.info(f"Extraction progress: {i}/{len(archives)}...")

        if skip_existing and os.path.isdir(target_dir) and os.listdir(target_dir):
            logger.debug(f"'{fn}' already extracted at {target_dir}, skipping.")
            successes.append({
                "archive": archive_path, "type": atype,
                "target_dir": target_dir, "status": "already extracted (skipped)",
            })
            continue

        try:
            extract_one(archive_path, target_dir, atype, logger)
            successes.append({
                "archive": archive_path, "type": atype,
                "target_dir": target_dir, "status": "extracted",
            })
        except Exception as e:
            logger.error(f"Failed to extract '{archive_path}': {e}")
            errors.append({
                "archive": archive_path, "type": atype or "unknown",
                "target_dir": target_dir, "reason": str(e),
            })

    logger.info(f"Extraction stage complete: {len(successes)} succeeded, {len(errors)} failed.")
    return successes, errors


def write_extract_logs(successes, errors, export_dir, timestamp):
    ok_path = os.path.join(export_dir, f"extract_log{timestamp}.csv")
    err_path = os.path.join(export_dir, f"extract_errors{timestamp}.csv")

    with open(ok_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["archive", "type", "target_dir", "status"], delimiter=";")
        writer.writeheader()
        writer.writerows(successes)

    with open(err_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["archive", "type", "target_dir", "reason"], delimiter=";")
        writer.writeheader()
        writer.writerows(errors)

    return ok_path, err_path


# --------------------------------------------------------------------------
# core steps (unchanged from your working version)
# --------------------------------------------------------------------------

def load_excel(path, sheet, uuid_col, archive_col, file_name_col, logger):
    logger.info(f"Reading Excel file: {path}")
    df = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    uuid_col = uuid_col or find_column(df.columns, UUID_COL_CANDIDATES)
    archive_col = archive_col or find_column(df.columns, ARCHIVE_COL_CANDIDATES)
    file_name_col = file_name_col or find_column(df.columns, file_name_COL_CANDIDATES)

    missing = [
        name for name, col in
        [("uuid", uuid_col), ("accessnumber", archive_col), ("file_name", file_name_col)]
        if col is None
    ]
    if missing:
        raise SystemExit(
            f"Could not auto-detect column(s): {missing}. "
            f"Available columns are: {list(df.columns)}. "
            f"Re-run with --uuid-col / --archive-col / --file_name-col to specify them manually."
        )

    logger.info(f"Using columns -> uuid: '{uuid_col}', accessnumber: '{archive_col}', file_name: '{file_name_col}'")

    df = df[[uuid_col, archive_col, file_name_col]].copy()
    df.columns = ["uuid", "accessnumber", "file_name"]

    df["uuid"] = df["uuid"].astype(str).str.strip()
    df["accessnumber"] = df["accessnumber"].apply(clean_accessnumber)
    df["file_name"] = df["file_name"].astype(str).str.strip()
    for index, row in df.iterrows():
        missing_uuid = row.uuid == ""
        missing_accessnr = row.accessnumber == ""
        missing_file_name = row.file_name == ""
        if missing_uuid:
            logger.warning(f"row {missing_uuid} has missing values.")
        if missing_accessnr:
            logger.warning(f"row {missing_accessnr} has missing values.")
        if missing_file_name:
            logger.warning(f"row {missing_file_name} has missing values.")

    nr_of_uuid = []
    nr_of_uuid.append(str(df['uuid'].unique()))

    logger.info(f"Loaded {len(df)} row(s) covering {len(nr_of_uuid)} unique uuid(s) "
                f"and {df['accessnumber'].nunique()} unique accessnumber(s).")
    return df


def find_archive_folders(source_root, archive_numbers, logger):
    """Single pass over the whole tree. Any directory whose name STARTS WITH
    one of the archive numbers (as its full leading alphanumeric token, e.g.
    '287' matches '287_001-xxx' but not '2870-xxx') is registered under that
    archive number and NOT descended into further here -- its contents are
    indexed separately, per archive number, only for archive numbers we
    actually need. There can be multiple matching folders per archive
    number; all of them are kept."""
    logger.info(f"Scanning {source_root} for archive folders (this can take a while on large drives)...")

    archive_set = set(archive_numbers)
    normalized_lookup = defaultdict(list)
    # 287 matches 287 not 2870. 2870 matches 2870 not 28700 etc.
    for a in archive_set:
        normalized_lookup[a.lstrip("0") or "0"].append(a)

    archive_folders = defaultdict(list)
    matched_dirs = 0

    for dirpath, dirnames, file_names in os.walk(source_root):
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
                # do not keep -> os.walk will not descend into this folder here;
                # we index its contents separately in index_files_for_archive()
            else:
                keep.append(d)
        dirnames[:] = keep

    logger.info(f"Found {matched_dirs} matching folder(s) on the drive, covering {len(archive_folders)} "
                f"distinct archive number(s).")

    return archive_folders


def index_files_for_archive(archive_roots, logger):
    """Recursively index every file under all folders belonging to one
    archive number. Returns two dicts: exact file_name (lowercased) ->
    [full paths], and stem-without-extension (lowercased) -> [full paths]."""
    by_name = defaultdict(list)
    by_stem = defaultdict(list)
    for root in archive_roots:
        for dirpath, _dirnames, bestandsnamen in os.walk(root):
            for file in bestandsnamen:
                full = os.path.join(dirpath, file)
                stem = os.path.splitext(file)[0].lower()
                by_name[file].append(full)
                by_stem[stem].append(full)

    return by_name, by_stem


def resolve_file(file_name, by_name, by_stem):
    """Only ever resolves to file(s) that match the sheet's file_name.
    Returns (candidates, match_type):
        match_type = "exact"           -> exactly one exact file_name match
        match_type = "exact_duplicate" -> exact file_name matched MORE THAN
                                           ONCE in different locations within
                                           this archive -- these are treated
                                           as genuine files that both need to
                                           be transferred (flagged for manual
                                           review, not blocked)
        match_type = "stem"            -> sheet omitted the extension,
                                           exactly one file has that stem
        match_type = "ambiguous"       -> stem matched, but MORE THAN ONE
                                           file with different extensions
                                           shares it -- too risky to guess,
                                           nothing is moved, flagged as error
        match_type = "none"            -> no file matches at all
    Every other file physically present that is NOT listed in the sheet is
    never touched, matched, or considered.
    """
    key = file_name
    if key in by_name:
        candidates = by_name[key]
        # find the first unused candidate
        for path in candidates:
            if path not in unique_paths:
                unique_paths.add(path)
                return [path], "exact"
        return candidates, "exact_duplicate"

    stem_key = os.path.splitext(file_name)[0].lower()
    if stem_key in by_stem:
        candidates = by_stem[stem_key]
        if len(candidates) > 1:
            return candidates, "ambiguous"
        return candidates, "stem"

    return [], "none"


def safe_destination(dest_dir, file_name):
    """If file_name already exists in dest_dir for a reason unrelated to the
    intentional duplicate-suffixing below (e.g. re-running the script),
    append _dup1, _dup2, ... so we never silently overwrite a different
    file."""
    dest_path = os.path.join(dest_dir, file_name)
    if not os.path.exists(dest_path):
        return dest_path, False
    stem, ext = os.path.splitext(file_name)
    i = 1
    while True:
        candidate = os.path.join(dest_dir, f"{stem}_dup{i}{ext}")
        if not os.path.exists(candidate):
            return candidate, True
        i += 1


def duplicate_dest_name(basename, index):
    """index is 0 for the first (original) copy, 1, 2, ... for the rest.
    First copy keeps its name; subsequent copies get a '-2', '-3', ...
    suffix before the extension, as requested."""
    if index == 0:
        return basename
    stem, ext = os.path.splitext(basename)
    return f"{stem}-{index + 1}{ext}"


def transfer_one(src, dest_dir, dest_name, mode, dry_run, logger, allow_rename_on_collision=True):
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
    return dest_path, ("moved" if mode == "move" else "copied")


def process(df, source_root, dest_root, mode, dry_run, logger):
    successes = []  # dicts for success_log.csv
    errors = []     # dicts for error_log.csv

    needed_archives = sorted(df["accessnumber"].unique())
    archive_folders = find_archive_folders(source_root, needed_archives, logger)

    missing_accessnumber = []
    file_indexes = {}  # accessnumber -> (by_name, by_stem)
    # Loop through excel to find accessnumbers
    for i, accessnumber in enumerate(needed_archives, 1):
        # Loop through folders to find accessnumbers
        if accessnumber not in archive_folders:
            missing_accessnumber.append(accessnumber)
            continue
        # Log progress every 200 accessnumbers
        if i % 200 == 0 or i == len(needed_archives):
            logger.info(f"Indexed files for {i}/{len(needed_archives)} needed archive folders...")
        file_indexes[accessnumber] = index_files_for_archive(archive_folders[accessnumber], logger)

    missing_archive_folders = set(needed_archives) - set(archive_folders.keys())
    if missing_archive_folders:
        logger.warning(f"{len(missing_archive_folders)} archive number(s) from the sheet were not found "
                        f"as folders on the drive at all."
                        f"These are: {missing_accessnumber}")

    total = len(df)
    for n, row in enumerate(df.itertuples(index=False), 1):
        uuid, accessnumber, file_name = row.uuid, row.accessnumber, row.file_name

        # Log progress every 5000 rows
        if n % 5000 == 0 or n == total:
            logger.info(f"Processed {n}/{total} rows "
                        f"({len(successes)} moved, {len(errors)} errors so far)...")

        if accessnumber not in archive_folders:
            errors.append({
                "accessnumber": accessnumber, "uuid": uuid, "file_name": file_name,
                "reason": "archive folder not found on drive",
            })
            continue

        by_name, by_stem = file_indexes[accessnumber]
        candidates, match_type = resolve_file(file_name, by_name, by_stem)
        if match_type == "none":
            errors.append({
                "accessnumber": accessnumber, "uuid": uuid, "file_name": file_name,
                "reason": "file not found inside archive folder(s)",
            })
            continue

        if match_type == "ambiguous":
            errors.append({
                "accessnumber": accessnumber, "uuid": uuid, "file_name": file_name,
                "reason": f"ambiguous match - {len(candidates)} files with different extensions found "
                          f"matching '{file_name}' ({', '.join(candidates)}) - skipped, needs manual review",
            })
            continue

        if match_type == "exact_duplicate":
            errors.append({
                "accessnumber": accessnumber, "uuid": uuid, "file_name": file_name,
                "reason": f"duplicate match - {len(candidates)} duplicate files found "
                          f"matching '{file_name}' ({', '.join(candidates)}) - needs manual review",
            })
            continue

        # match_type is "exact", "exact_duplicate", or "stem" here.
        dest_dir = os.path.join(dest_root, sanitize_folder_name(accessnumber))
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
                    "accessnumber": accessnumber, "uuid": uuid,
                    "file_name_expected": file_name, "file_found": src_basename,
                    "source_path": src, "dest_path": dest_path,
                    "status": status, "match_type": match_type,
                    "duplicate_group_size": group_size,
                })

            except Exception as e:
                errors.append({
                    "accessnumber": accessnumber, "uuid": uuid, "file_name": file_name,
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
        safe_str(r["accessnumber"]),
        safe_str(r["file_name_expected"])))
    fieldnames= [
            "uuid", "accessnumber","file_name_expected", "file_found",
            "source_path", "dest_path", "status", "match_type", "duplicate_group_size",
        ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";" )
        #print("Delimiter:", repr(writer.dialect.delimiter))
        writer.writeheader()
        writer.writerows(successes_sorted)


def write_duplicates_log(successes, path):
    dup_rows = [r for r in successes if r["duplicate_group_size"] > 1]
    dup_rows_sorted = sorted(dup_rows, key=lambda r: (safe_str(r["uuid"]), safe_str(r["accessnumber"]), safe_str(r["file_name_expected"]), r["dest_path"]))
    fieldnames = ["accessnumber", "uuid", "file_name_expected", "file_found", "source_path", "dest_path", "duplicate_group_size"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows({k: r[k] for k in fieldnames} for r in dup_rows_sorted)
    return len(dup_rows_sorted)


def write_error_log(errors, path):
    errors_sorted = sorted(errors, key=lambda r: (safe_str(r["uuid"]), safe_str(r["accessnumber"]), safe_str(r["file_name"])))
    fieldnames=["accessnumber", "uuid", "file_name", "reason"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(errors_sorted)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Organize archive files by accessnumber, driven by an Excel manifest.")
    parser.add_argument("--excel", required=True, help="Path to the Excel file")
    parser.add_argument("--sheet", default=None, help="Sheet name or index (default: first sheet)")
    parser.add_argument("--source", required=True,
                         help="Root folder to search for archive folders (extraction target, if --compressed-source is used)")
    parser.add_argument("--dest", required=True, help="Root folder where accessnumber folders will be created")
    parser.add_argument("--uuid-col", default=None, help="Override: name of the uuid column")
    parser.add_argument("--archive-col", default=None, help="Override: name of the accessnumber column")
    parser.add_argument("--file_name-col", default=None, help="Override: name of the file_name column")
    parser.add_argument("--compressed-source", default=None,
                         help="Folder containing ZIP/TAR/7Z archives to extract into --source before organizing "
                              "(omit to skip extraction and treat --source as already-extracted folders)")
    parser.add_argument("--no-skip-extracted", action="store_true",
                         help="Re-extract archives even if their target folder already exists and is non-empty")
    parser.add_argument("--copy", action="store_true", help="Copy instead of move")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only, no files are touched")
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
    mode = "copy" if args.copy else "move"

    logger.info(f"Mode: {mode.upper()}{'  (DRY RUN - no files will be touched)' if args.dry_run else ''}")
    logger.info(f"Source: {args.source}")
    logger.info(f"Destination: {args.dest}")

    if args.compressed_source:
        if not os.path.isdir(args.compressed_source):
            raise SystemExit(f"Compressed-source folder does not exist: {args.compressed_source}")
        os.makedirs(args.source, exist_ok=True)
        logger.info(f"Extraction stage: extracting archives from {args.compressed_source} into {args.source}")
        ext_successes, ext_errors = extract_archives(
            args.compressed_source, args.source, logger, skip_existing=not args.no_skip_extracted
        )
        timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        ok_path, err_path = write_extract_logs(ext_successes, ext_errors, args.export_dir, timestamp)
        logger.info(f"Extraction log: {ok_path}")
        logger.info(f"Extraction errors: {err_path}")
        if ext_errors:
            logger.warning(f"{len(ext_errors)} archive(s) failed to extract; see {err_path} before proceeding.")

    if not os.path.isdir(args.source):
        raise SystemExit(f"Source folder does not exist: {args.source}")
    if not args.dry_run:
        os.makedirs(args.dest, exist_ok=True)

    df = load_excel(args.excel, args.sheet, args.uuid_col, args.archive_col, args.file_name_col, logger)

    successes, errors = process(df, args.source, args.dest, mode, args.dry_run, logger)

    current_datetime = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    success_csv = os.path.join(args.export_dir, f"success_log{str(current_datetime)}.csv")
    error_csv = os.path.join(args.export_dir, f"error_log{str(current_datetime)}.csv")
    duplicates_csv = os.path.join(args.export_dir, f"duplicates_log{str(current_datetime)}.csv")
    write_success_log(successes, success_csv)
    write_error_log(errors, error_csv)
    dup_count = write_duplicates_log(successes, duplicates_csv)

    archives_touched = len({s["accessnumber"] for s in successes})
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
