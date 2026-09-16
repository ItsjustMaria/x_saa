#Write summary to txt file
    text_path = Path(HOME_REPO, output_path, f"{fund}summary.txt")
    txt_out = open(text_path, 'w')

    txt_out.write(f"\n=== Error overview for {fund} ===\n")
    txt_out.write(f"Total errors = {total_errors}\n\n")
    for msg_type, count in message_types.most_common():
        pct = (count / total_errors * 100) if total_errors else 0
        txt_out.write(f"{msg_type}: {count} ({pct:.1f}%)\n")
    
    type_counts = Counter(e["type"] for e in events)
    txt_out(f"Outcome events:             {type_counts['outcome']}")
    txt_out(f"Skipped-row warnings:       {type_counts['row_skip']}")
    txt_out(f"Token-skip rows:            {type_counts['token_skip']}")
    txt_out(f"Retry attempts (isolated):  {sum(len(v) for v in retries_pending.values()) + type_counts.get('_attached', 0)}")
    txt_out(f"Input rows:                 {sum(input_counts.values())} (+{empty_uuid_input_rows} empty-uuid)")
    txt_out(f"Joined to filename:         {len(events) - len(unmatched_events)}")
    txt_out(f"Events without input row:   {len(unmatched_events)}")
    txt_out(f"Input rows without event:   {sum(len(v) for v in leftover.values())}")

    if retries_pending or any(e["retry_linenos"] for e in events):
        n_retry_lines = sum(1 for e in events if e["retry_linenos"])
        txt_out(f"\n*** WARNING: retry events detected; {n_retry_lines} outcome(s) "
              "were preceded by token/connection retries. Retries were excluded "
              "from the alignment stream, so integrity should hold — verify the "
              "per-uuid counts below.")

    if unattributed_hints:
        txt_out(f"\n*** CRITICAL: {len(unattributed_hints)} token-hint line(s) WITHOUT "
              "a record_id were found. These consume an input row but cannot be "
              "attributed to a uuid — per-uuid alignment is unreliable from the "
              "first occurrence onward:")
        for ln, txt in unattributed_hints:
            txt_out(f"  line {ln}: {txt[:120]}")

    if empty_id_skips:
        txt_out(f"\n*** NOTE: {len(empty_id_skips)} 'asset_id is empty' warning(s) with an "
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
        txt_out("\nPer-uuid mismatches (input_rows, log_events):")
        for u, (ni, ne) in sorted(mismatches.items()):
            txt_out(f"  {u}: {ni} vs {ne}")

    txt_out.write(f"\nDetailed CSV written to: {out_csv.resolve()}")

    txt_out.close()