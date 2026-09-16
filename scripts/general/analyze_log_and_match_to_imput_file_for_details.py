#!/usr/bin/env python3
"""
Combined log analyzer + joiner.

Given a python-logging generated log file and the CSV input file the script
consumed (columns: uuid, filename), this script:

  1) Writes <log>_errors.csv — one row per terminal ERROR, with separate
     columns for asset_id, record_id (uuid) and the parsed JSON error message.
  2) Prints an overview: total errors, grouped by normalized message type
     (asset numbers replaced by <n> so identical message types aggregate).
  3) Writes <log>_joined.csv — every row-consuming log event (outcomes,
     row-skips, token-skips) matched positionally per-uuid to its filename.

Usage: python log_combined.py <logfile> <inputfile>
"""

import csv
import os
import json
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
#sys.path.append(str(HOME_REPO))
print(HOME_REPO)
project_name = 'analyze_logs'
log_path_name = 'aip_downloads'
log_path = f'data/{log_path_name}/logs/'
source_path = f'data/{log_path_name}/source/'
os.makedirs(Path(HOME_REPO, 'data', project_name, log_path_name, 'output' ), exist_ok=True)
os.makedirs(Path(HOME_REPO, 'data', project_name, log_path_name, 'errors' ), exist_ok=True)
output_path = Path(HOME_REPO, 'data', project_name, log_path_name, 'output')
error_path = Path(HOME_REPO, 'data', project_name, log_path_name, 'errors')

LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)"
    r"\s+\[(?P<level>[A-Z]+)\]\s+(?P<message>.*)$"
)
# '*' allows a trailing 'record_id=' with an EMPTY id to match
RECORD_ID_RE = re.compile(r"record_id=(?P<record_id>[A-Za-z0-9-]*)")
ASSET_ID_RE = re.compile(r"asset_id=(\d+)")

# "Error linking asset_id=X to record_id=Y: {json}"
LINK_ERROR_RE = re.compile(
    r"Error linking asset_id=\d+ to record_id=[A-Za-z0-9-]*:\s*(?P<payload>\{.*)"
)

RETRY_RE = re.compile(
    r"Client request\(.*\) invalid: \d{3} .*(invalid_token|Bad Request)",
    re.IGNORECASE,
)
TOKEN_HINT_RE = re.compile(r"Probably outdated access token", re.IGNORECASE)
SKIP_WARN_RE = re.compile(r"Skipping row because asset_id is empty", re.IGNORECASE)

NOISE_PATTERNS = [
    re.compile(r"start processing", re.IGNORECASE),
    re.compile(r"summary", re.IGNORECASE),
    re.compile(r"skipped rows", re.IGNORECASE),
    re.compile(r"succes{1,2}ful links", re.IGNORECASE),
    re.compile(r"Processing: record_id="),
    re.compile(r"Probably outdated access token. Try refresh token."),
]

def extract_json_error_message(payload: str) -> str:
    """Pull error.message out of the JSON payload; fall back to raw text."""
    try:
        data = json.loads(payload.strip())
        return data["error"]["message"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return payload.strip()

def normalize(message: str) -> str:
    """'Asset 96828097 already linked' -> 'Asset <n> already linked'."""
    return re.sub(r"\d+", "<n>", message)

def main(log: str, source: str) -> None:
    log_file = Path(HOME_REPO, log_path, log)
    source_file = Path(HOME_REPO, source_path, source)
    print(log_file)
    if not log_file.is_file() or not source_file.is_file():
        sys.exit(f"Log file not found: {log_file}")
    #log_file, source_file = Path(log_path), Path(source_file)

    # 1) Filenames per uuid from input, in row order -------------------------
    filename_by_uuid = defaultdict(deque)
    input_counts = Counter()
    empty_uuid_input_rows = 0
    with source_file.open(newline="", encoding="utf-8", ) as f:
        reader = csv.reader(f, delimiter=';')
        header = next(reader)
        uuid_col = header.index("uuid")        # adjust column names
        file_col = header.index("filename")
        for row in reader:
            uid = row[uuid_col].strip()
            if not uid:
                empty_uuid_input_rows += 1
                continue
            filename_by_uuid[uid].append(row[file_col])
            input_counts[uid] += 1

    # 2) Classify log lines in order ------------------------------------------
    events = []                                # all row-consuming events
    csv_rows = []                              # detailed rows for output 1
    total_errors = 0                           # every [ERROR] line
    message_types = Counter()
    retries_pending = defaultdict(list)
    unattributed_hints, empty_id_skips = [], []

    with log_file.open(encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            stripped = line.strip()
            if any(p.search(stripped) for p in NOISE_PATTERNS):
                continue

            lm = LINE_RE.match(stripped)
            if not lm:
                continue
            level, message = lm.group("level"), lm.group("message")
            rm = RECORD_ID_RE.search(message)
            uid = rm.group("record_id") if rm else ""

            base = {"lineno": lineno, "timestamp": lm.group("timestamp"),
                    "line": stripped}

            # --- INFO: token hint, consumes a row when attributable --------
            if TOKEN_HINT_RE.search(message):
                if uid:
                    base.update(type="token_skip", record_id=uid, asset_id="",
                                message="Probably outdated access token",
                                retry_linenos="")
                    events.append(base)
                else:
                    unattributed_hints.append((lineno, stripped))
                continue

            if not rm:
                continue

            # --- retries are attempts, NOT outcomes: no pop, just record ---
            if level == "ERROR" and RETRY_RE.search(message):
                retries_pending[uid].append(lineno)
                continue

            # --- WARNING: skipped row — consumes a row ----------------------
            if level == "WARNING" and SKIP_WARN_RE.search(message):
                if not uid:
                    empty_id_skips.append(base)
                    continue
                retry_linenos = ";".join(map(str, retries_pending.pop(uid, [])))
                base.update(type="row_skip", record_id=uid, asset_id="",
                            message="skipped: asset_id empty",
                            retry_linenos=retry_linenos)
                events.append(base)
                continue

            # --- outcomes: terminal INFO success or terminal ERROR ---------
            if level in ("ERROR", "INFO"):
                am = ASSET_ID_RE.search(message)
                link_m = LINK_ERROR_RE.search(message)
                err_msg = (
                    extract_json_error_message(link_m.group("payload"))
                    if link_m else message
                )
                retry_linenos = ";".join(map(str, retries_pending.pop(uid, [])))
                base.update(type="outcome", record_id=uid,
                            asset_id=am.group(1) if am else "",
                            message=err_msg,
                            retry_linenos=retry_linenos)
                events.append(base)

                if level == "ERROR":
                    total_errors += 1
                    message_types[normalize(err_msg)] += 1
                    csv_rows.append({
                        "timestamp": base["timestamp"],
                        "asset_id": am.group(1) if am else "",
                        "record_id": uid,
                        "message": err_msg,
                        "raw_message": message,
                    })

    # 3) Join positionally: attach filename to BOTH lists, each with its
    #    own copy of the queues so consuming twice doesn't double-deplete.
    n_retries_total = sum(len(v) for v in retries_pending.values())

    filename_by_uuid_for_csv = {u: deque(v) for u, v in filename_by_uuid.items()} 
    unmatched_events = []
    for e in events:
        q = filename_by_uuid.get(e["record_id"])
        if q:
            e["filename"] = q.popleft()
        else:
            e["filename"] = "<NO MATCHING INPUT ROW>"
            unmatched_events.append(e)
    for row in csv_rows:
        q = filename_by_uuid_for_csv.get(row["record_id"])
        row["filename"] = q.popleft() if q else "<NO MATCHING INPUT ROW>"
    leftover = {u: list(v) for u, v in filename_by_uuid.items() if v}

    # 4) Report ------------------------------------------------------------------
    type_counts = Counter(e["type"] for e in events)
    print(f"Outcome events:             {type_counts['outcome']}")
    print(f"Total [ERROR] lines:        {total_errors}")
    print(f"Skipped-row warnings:       {type_counts['row_skip']}")
    print(f"Token-skip rows:            {type_counts['token_skip']}")
    print(f"Input rows:                 {sum(input_counts.values())} (+{empty_uuid_input_rows} empty-uuid)")
    print(f"Joined to filename:         {len(events) - len(unmatched_events)}")
    print(f"Events without input row:   {len(unmatched_events)}")
    print(f"Input rows without event:   {sum(len(v) for v in leftover.values())}")

    n_retried = sum(1 for e in events if e["retry_linenos"])
    if n_retries_total:
        print(f"\n*** WARNING: {n_retries_total} token/connection retry event(s) "
              f"detected, preceding {n_retried} consuming event(s). Retries were "
              "excluded from the alignment stream, so integrity should hold.")

    if unattributed_hints:
        print(f"\n*** CRITICAL: {len(unattributed_hints)} token-hint line(s) without "
              "a record_id — alignment unreliable from first occurrence:")
        for ln, txt in unattributed_hints:
            print(f"  line {ln}: {txt[:120]}")

    if empty_id_skips:
        print(f"\n*** NOTE: {len(empty_id_skips)} 'asset_id is empty' warning(s) with EMPTY "
              f"record_id vs {empty_uuid_input_rows} empty-uuid input row(s). "
              + ("Consistent." if len(empty_id_skips) == empty_uuid_input_rows
                 else "Counts MISMATCH — inspect these rows manually."))

    consumed = Counter(e["record_id"] for e in events)
    mismatches = {
        u: (input_counts[u], consumed.get(u, 0))
        for u in input_counts if input_counts[u] != consumed.get(u, 0)
    }
    if mismatches:
        print("\nPer-uuid mismatches (input_rows, log_events):")
        for u, (ni, ne) in sorted(mismatches.items()):
            print(f"  {u}: {ni} vs {ne}")

    # === OUTPUT 1: detailed errors CSV =======================================
    match = re.search(r"^(?P<number>\d+)", source)
    fund = match.group(1)
    csv_path = Path(HOME_REPO, error_path, f"{fund}_errors.csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp", "asset_id", "record_id", "message", "filename",
            "raw_message"])
        w.writeheader()
        w.writerows(csv_rows)

    # === OUTPUT 2: overview ==================================================
    print(f"\n=== Error overview for {log_file.name} ===")
    print(f"Total errors = {total_errors}\n")
    for msg_type, count in message_types.most_common():
        pct = (count / total_errors * 100) if total_errors else 0
        print(f"{msg_type}: {count} ({pct:.1f}%)")

    # === OUTPUT 3: joined file ===============================================
    out_csv = Path(HOME_REPO, output_path, f"{fund}__joined.csv")
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "lineno", "timestamp", "type", "record_id", "asset_id",
            "message", "filename", "retry_linenos", "line"])
        w.writeheader()
        w.writerows(events)
    print(f"\nDetailed errors CSV: {csv_path.resolve()}")
    print(f"Joined output: {out_csv.resolve()}")

### Write summary of all above to txt file
    text_path = Path(HOME_REPO, output_path, f"{fund}_summary.txt")
    txt_out = open(text_path, 'w')

    txt_out.write(f"\n=== Error overview for {fund} ===\n")
    txt_out.write(f"Total errors = {total_errors}\n\n")
    for msg_type, count in message_types.most_common():
        pct = (count / total_errors * 100) if total_errors else 0
        txt_out.write(f"{msg_type}: {count} ({pct:.1f}%)\n\n")
    
    type_counts = Counter(e["type"] for e in events)
    txt_out.write(f"Outcome events:             {type_counts[' outcome']}\n\n")
    txt_out.write(f"Skipped-row warnings:       {type_counts[' row_skip']}\n\n")
    txt_out.write(f"Token-skip rows:            {type_counts[' token_skip']}\n\n")
    txt_out.write(f"Retry attempts (isolated):  {sum(len(v) for v in retries_pending.values()) + type_counts.get('_attached', 0)}\n\n")
    txt_out.write(f"Input rows:                 {sum(input_counts.values())} (+{empty_uuid_input_rows} empty-uuid)\n\n")
    txt_out.write(f"Joined to filename:         {len(events) - len(unmatched_events)}\n\n")
    txt_out.write(f"Events without input row:   {len(unmatched_events)}\n\n")
    txt_out.write(f"Input rows without event:   {sum(len(v) for v in leftover.values())}\n\n")

    n_retried = sum(1 for e in events if e["retry_linenos"])
    if n_retries_total:
        txt_out.write(f"\n*** WARNING: {n_retries_total} token/connection retry event(s) \n"
             f"detected, preceding {n_retried} consuming event(s). Retries were \n"
             "excluded from the alignment stream, so integrity should hold.\n\n")

    if unattributed_hints:
        txt_out.write(f"\n*** CRITICAL: {len(unattributed_hints)} token-hint line(s) WITHOUT \n"
              "a record_id were found. These consume an input row but cannot be \n"
              "attributed to a uuid — per-uuid alignment is unreliable from the \n"
              "first occurrence onward:\n\n")
        for ln, txt in unattributed_hints:
            txt_out.write(f"  line {ln}: {txt[:120]}\n\n")

    if empty_id_skips:
        txt_out.write(f"\n*** NOTE: {len(empty_id_skips)} 'asset_id is empty' warning(s) with an \n"
              f"EMPTY record_id; input file has {empty_uuid_input_rows} row(s) with an \n"
              "empty uuid. \n"
              + ("Counts match — consistent.\n"
                 if len(empty_id_skips) == empty_uuid_input_rows
                 else "Counts MISMATCH — inspect these rows manually.\n\n"))

# Per-uuid sanity check (outcomes + skips must equal input rows)
    consumed = Counter(e["record_id"] for e in events)
    mismatches = {
        u: (input_counts[u], consumed.get(u, 0))
        for u in input_counts if input_counts[u] != consumed.get(u, 0)
    }
    if mismatches:
        txt_out.write("\nPer-uuid mismatches (input_rows, log_events):\n")
        for u, (ni, ne) in sorted(mismatches.items()):
            txt_out.write(f"  {u}: {ni} vs {ne}\n\n")

    txt_out.write(f"\nDetailed CSV written to: {out_csv.resolve()}")

    txt_out.close()



if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"Usage: python {Path(__file__).name} <logfile> <inputfile>")
    main(sys.argv[1], sys.argv[2])