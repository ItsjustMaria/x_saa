import csv
import re
import shutil
from pathlib import Path

def clean_id_column(input_file, output_file=None, column_identifier=None):
    """
    Clean ID column by removing prefixes and leading zeros, keeping only the actual number.
    
    Args:
        input_file: Path to the input CSV file
        output_file: Optional path for cleaned output. Defaults to input_file.
        column_identifier: Column name OR column index (starting from 0).
                           If None, asks interactively.
    
    Regex pattern: Removes everything up to the first non-zero digit (1-9)
                    Example: "0/010012007" -> "7", "0/0100120150" -> "150"
    """
    # Backup original file
    backup_path = f"{input_file}.bak"
    shutil.copy2(input_file, backup_path)
    print(f"✓ Backed up original to: {backup_path}")
    
    if output_file is None:
        output_file = input_file
    
    pattern = re.compile(r'.*?([1-9]\d*)$')
    
    with open(input_file, 'r', newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        
        # Determine header and target column
        headers = reader.fieldnames
        
        if column_identifier is None:
            print("\nAvailable columns:")
            for i, h in enumerate(headers):
                print(f"  [{i}] {h}")
            
            choice = input("\nEnter column number or name: ").strip()
            
            if choice.isdigit():
                col_idx = int(choice)
                if 0 <= col_idx < len(headers):
                    col_name = headers[col_idx]
                else:
                    raise ValueError(f"Invalid column index: {col_idx}")
            elif choice.lower() in [h.lower() for h in headers]:
                col_name = next(h for h in headers if h.lower() == choice.lower())
            else:
                raise ValueError(f"Unknown column identifier: {choice}")
            
            selected_col = col_name
        else:
            # Handle programmatic specification
            if isinstance(column_identifier, str):
                if column_identifier in headers:
                    selected_col = column_identifier
                elif any(h.lower() == column_identifier.lower() for h in headers):
                    selected_col = next(h for h in headers 
                                      if h.lower() == column_identifier.lower())
                else:
                    raise ValueError(f"Column '{column_identifier}' not found")
            elif isinstance(column_identifier, int):
                if 0 <= column_identifier < len(headers):
                    selected_col = headers[column_identifier]
                else:
                    raise ValueError(f"Column index out of range: {column_identifier}")
            else:
                raise ValueError("column_identifier must be string (name) or int (index)")
        
        print(f"\nTarget column: '{selected_col}'")
        processed_count = 0
        unchanged_count = 0
        
        rows = []
        for row_num, row in enumerate(reader, start=2):  # Row 1 is header
                
            raw_value = row[selected_col]
            
            match = pattern.match(raw_value.strip())
            if match:
                cleaned_value = match.group(1)
                row[selected_col] = cleaned_value
                if raw_value != cleaned_value:
                    processed_count += 1
                else:
                    unchanged_count += 1
            
            rows.append(row)
    
    # Write output
    with open(output_file, 'w', newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"\n{'='*50}")
    print(f"Processing complete!")
    print(f"  Rows processed: {processed_count + unchanged_count}")
    print(f"  Changed values: {processed_count}")
    print(f"  Unchanged:      {unchanged_count}")
    print(f"  Output saved to: {output_file}")
    print(f"{'='*50}\n")

# ============================================================================
# USAGE EXAMPLES (modify below as needed)
# ============================================================================

if __name__ == "__main__":
    
    # ── CONFIGURATION AREA ────────────────────────────────────────────────
    INPUT_FILE = "your_data.csv"           # Change to your actual file path
    OUTPUT_FILE = None                      # Set to new filename or keep None to overwrite
    COLUMN_NAME = "id_nr"                   # Or use column index, e.g., 3 for 4th column
    
    # Examples:
    # COLUMN_NAME = "ID"                     # Use exact column header name
    # COLUMN_NAME = 3                        # Use zero-based column index
    # COLUMN_NAME = None                     # Interactive selection at runtime
    
    # ── EXECUTION ─────────────────────────────────────────────────────────
    try:
        clean_id_column(INPUT_FILE, OUTPUT_FILE, COLUMN_NAME)
    except Exception as e:
        print(f"❌ Error: {e}")
        print("Restoring from backup...")
        # Restore function if things go wrong
        pass