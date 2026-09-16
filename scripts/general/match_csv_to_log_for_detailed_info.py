#!/usr/bin/env python3
"""
Join log events back to input-file rows, per-uuid, in occurrence order.

Row-consuming events (each pops one filename from that uuid's queue):
  - outcome   : INFO success or terminal ERROR (incl. 'already linked')
  - row_skip  : WARNING 'Skipping row because asset_id is empty'
  - token_skip: INFO 'Probably outdated access token' (if record_id present)

Non-consuming events:
  - retry     : ERROR matching token/connection pattern (attached to the
                next consuming event of the same uuid)

Usage: python log_join.py <logfile> <inputfile>
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
path_exists = os.makedirs(Path(HOME_REPO, 'data', project_name, log_path_name, 'output' ), exist_ok=True)
output_path = Path(HOME_REPO, 'data', project_name, log_path_name, 'output')

LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)"
    r"\s+\[(?P<level>[A-Z]+)\]\s+(?P<message>.*)$"
)
# NOTE: '*' so that a trailing 'record_id=' with EMPTY id still matches
RECORD_ID_RE = re.compile(r"record_id=(?P<record_id>[A-Za-z0-9-]*)")
ASSET_ID_RE = re.compile(r"asset_id=(\d+)")

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
]


def main(log: str, source_file: str) -> None:
    log_file = Path(HOME_REPO, log_path, log)
    source_file = Path(HOME_REPO, source_path, source_file)
    print(log_file)
    if not log_file.is_file() or not source_file.is_file():
        sys.exit(f"Log file not found: {log_file}")
    #log_file, source_file = Path(log_path), Path(source_file)

    # 1) Filenames per uuid from input, in row order -------------------------
    filename_by_uuid = defaultdict(deque)
    input_counts = Counter()
    empty_uuid_input_rows = 0
    with source_file.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
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
    events, retries_pending = [], defaultdict(list)
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

            if TOKEN_HINT_RE.search(message):
                if uid:
                    base.update(type="token_skip", record_id=uid,
                                asset_id="", retry_linenos="")
                    events.append(base)          # consumes a row
                else:
                    unattributed_hints.append((lineno, stripped))
                continue

            if not rm:
                continue                          # log line without record_id

            retries = ";".join(map(str, retries_pending.pop(uid, [])))

            if level == "ERROR" and RETRY_RE.search(message):
                retries_pending[uid].append(lineno)   # attempt, not outcome
                continue

            if level == "WARNING" and SKIP_WARN_RE.search(message):
                if not uid:
                    empty_id_skips.append(base)
                    continue                    # handled via empty-uuid check
                base.update(type="row_skip", record_id=uid,
                            asset_id="", retry_linenos=retries)
                events.append(base)             # consumes a row
                continue

            if level == "ERROR" or level == "INFO":
                am = ASSET_ID_RE.search(message)
                base.update(type="outcome", record_id=uid,
                            asset_id=am.group(1) if am else "",
                            retry_linenos=retries)
                events.append(base)             # consumes a row

    # 3) Join positionally -----------------------------------------------------
    unmatched_events, leftover_report = [], []
    for e in events:
        q = filename_by_uuid.get(e["record_id"])
        if q:
            e["filename"] = q.popleft()
        else:
            e["filename"] = "<NO MATCHING INPUT ROW>"
            unmatched_events.append(e)
    leftover = {u: list(v) for u, v in filename_by_uuid.items() if v}

    # 4) Report -----------------------------------------------------------------
    type_counts = Counter(e["type"] for e in events)
    print(f"Outcome events:             {type_counts['outcome']}")
    print(f"Skipped-row warnings:       {type_counts['row_skip']}")
    print(f"Token-skip rows:            {type_counts['token_skip']}")
    print(f"Retry attempts (isolated):  {sum(len(v) for v in retries_pending.values()) + type_counts.get('_attached', 0)}")
    print(f"Input rows:                 {sum(input_counts.values())} (+{empty_uuid_input_rows} empty-uuid)")
    print(f"Joined to filename:         {len(events) - len(unmatched_events)}")
    print(f"Events without input row:   {len(unmatched_events)}")
    print(f"Input rows without event:   {sum(len(v) for v in leftover.values())}")

    if retries_pending or any(e["retry_linenos"] for e in events):
        n_retry_lines = sum(1 for e in events if e["retry_linenos"])
        print(f"\n*** WARNING: retry events detected; {n_retry_lines} outcome(s) "
              "were preceded by token/connection retries. Retries were excluded "
              "from the alignment stream, so integrity should hold — verify the "
              "per-uuid counts below.")

    if unattributed_hints:
        print(f"\n*** CRITICAL: {len(unattributed_hints)} token-hint line(s) WITHOUT "
              "a record_id were found. These consume an input row but cannot be "
              "attributed to a uuid — per-uuid alignment is unreliable from the "
              "first occurrence onward:")
        for ln, txt in unattributed_hints:
            print(f"  line {ln}: {txt[:120]}")

    if empty_id_skips:
        print(f"\n*** NOTE: {len(empty_id_skips)} 'asset_id is empty' warning(s) with an "
              f"EMPTY record_id; input file has {empty_uuid_input_rows} row(s) with an "
              "empty uuid. "
              + ("Counts match — consistent."
                 if len(empty_id_skips) == empty_uuid_input_rows
                 else "Counts MISMATCH — inspect these rows manually."))

    # Per-uuid sanity check (outcomes + skips must equal input rows)
    consumed = Counter(e["record_id"] for e in events)
    mismatches = {
        u: (input_counts[u], consumed.get(u, 0))
        for u in input_counts if input_counts[u] != consumed.get(u, 0)
    }
    if mismatches:
        print("\nPer-uuid mismatches (input_rows, log_events):")
        for u, (ni, ne) in sorted(mismatches.items()):
            print(f"  {u}: {ni} vs {ne}")

    # 5) Output ------------------------------------------------------------------
    match = re.search(r"^(?P<number>\d+_)", log_file)
    fund = match.group(1)
    out_csv = Path(HOME_REPO, output_path, f"{fund}errors.csv")
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "lineno", "timestamp", "type", "record_id", "asset_id",
            "filename", "retry_linenos", "line"])
        w.writeheader()
        w.writerows(events)
    print(f"\nJoined output: {out_csv.resolve()}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"Usage: python {Path(__file__).name} <logfile> <inputfile>")
    main(sys.argv[1], sys.argv[2])