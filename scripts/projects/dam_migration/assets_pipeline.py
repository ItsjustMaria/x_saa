import sys
import json
import csv
import time
import os
import logging
from pathlib import Path
from datetime import datetime

import click
import pandas as pd
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
from modules import wrapper

# Dit script automatiseert het ophalen, verwerken en koppelen van DAM-assets aan Memorix-records op basis van CSV-bestanden en bestandsnamen.
# Het kan bestanddelen van een fonds exporteren, deze combineren met een mappingbestand en vervolgens in de DAM zoeken naar bijbehorende assets op basis van exacte bestandsnaam-matches.
# Gevonden asset_id’s kunnen daarna automatisch aan record_id’s worden gekoppeld, waarbij ondersteuning aanwezig is voor dry-runs, logging en retry-mechanismen bij API-fouten.
# Dubbele of ambigue DAM-resultaten worden apart opgeslagen zodat deze eerst gecontroleerd kunnen worden voordat koppelingen worden uitgevoerd.

#### Example commands:
# only files_per_fonds (1) ->              python assets.py files-per-fonds 5075 prod
# only find_assetid_by_filename_csv (2) -> python assets.py find-assetid input.csv output.csv prod (optional:--max-retries 3)
# only link_assetid_to_recordid_csv (3) -> python assets.py link-assetid links.csv --env prod --no-dryrun
# uses (2) & (3) ->                        python assets.py find-and-link input.csv output.csv --env prod --no-dryrun
# uses (1), (2) & (3) ->                   python assets.py files-assets-link 5075 mapping.csv merged.csv assets.csv --env prod --join-on uuid --no-dryrun

# python assets_pipeline.py find-and-link /opt/lampp/htdocs/test/data/aip_downloads/source/15009.csv /opt/lampp/htdocs/test/data/aip_downloads/output/15009_output.csv --env prod --no-dryrun


project = 'aip_downloads'
log_path = f"{HOME_REPO}/data/{project}/logs"

def get_settings_file(env):
    if env == "acc":
        return "settings.temp.json"
    if env == "prod":
        return "settings.prod.json"
    raise ValueError("env must be 'acc' or 'prod'")


def get_api(env):
    if env == 'acc':
        PREFIX = 'https://ams-migrate.memorix.io'
        settings_file = Path(WORK_REPO, 'settings.json') 
    elif env == 'prod':
        PREFIX = 'https://stadsarchiefamsterdam.memorix.io'
        settings_file = Path(WORK_REPO, 'settings.prod.json') 
    elif env == 'tst':
        settings_file = print(f'test output')
    else:
        raise ValueError("Environment must be 'acc' or 'prod'")

    settings = saa.readJsonFile(settings_file) 
    #api = memorix.ApiClient(settings)
    return memorix.ApiClient(settings)


def get_helper(env):
    api = get_api(env)
    helper = wrapper.ApiBuildingBlocks(api)
    return api, helper


def files_per_fonds(toegangsnummer, env, output_file=None):
    # Haalt alle bestanddelen op voor een fonds
    api, helper = get_helper(env)

    if output_file is None:
        output_file = f"{toegangsnummer}_lijst.csv"

    fonds_uuid = helper.find_fonds_uuid(toegangsnummer)
    print(f"Fonds uuid = {fonds_uuid}")

    all_rows = []

    # Eerste pagina ophalen
    response = api.search_files_per_fonds(fonds_uuid=fonds_uuid, limit=10000)
    data = json.loads(response.text)

    while True:
        rows = data.get("rows", [])
        all_rows.extend(rows)
        print(f"{len(rows)} records opgehaald, totaal nu: {len(all_rows)}")

        next_token = data.get("pagination", {}).get("next")
        if not next_token:
            break

        response = api.search_files_per_fonds(
            fonds_uuid=fonds_uuid,
            next=next_token
        )
        data = json.loads(response.text)

    print(f"Totaal aantal gevonden bestanddelen: {len(all_rows)}")

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["uuid", "invnr", "title", "description"]
        writer = csv.DictWriter(
            csvfile,
            fieldnames=fieldnames,
            delimiter=";",
            quotechar='"',
            quoting=csv.QUOTE_NONNUMERIC,
        )
        writer.writeheader()

        for row in all_rows:
            writer.writerow(
                {
                    "uuid": row["recordId"],
                    "invnr": row["meta"]["identifier"],
                    "title": row["title"],
                    "description": row["description"],
                }
            )

    print(f"Bestand klaar: {output_file}")
    return output_file

def merge_records_with_filenames(files_csv, mapping_csv, output_file, join_on="uuid"):
    if not Path(files_csv).is_file():
        raise FileNotFoundError(f"Files CSV not found: {files_csv}")

    if not Path(mapping_csv).is_file():
        raise FileNotFoundError(f"Mapping CSV not found: {mapping_csv}")

    files_df = pd.read_csv(files_csv, delimiter=";", na_filter=False, dtype=str)
    mapping_df = pd.read_csv(mapping_csv, delimiter=";", na_filter=False, dtype=str)

    if join_on not in files_df.columns:
        raise ValueError(f"Column '{join_on}' not found in files CSV.")

    if join_on not in mapping_df.columns:
        raise ValueError(f"Column '{join_on}' not found in mapping CSV.")

    if "filename" not in mapping_df.columns:
        raise ValueError("Mapping CSV must contain a 'filename' column.")

    merged_df = files_df.merge(mapping_df, on=join_on, how="inner")

    if join_on == "uuid":
        merged_df["record_id"] = merged_df["uuid"]
    elif join_on == "record_id":
        merged_df["record_id"] = merged_df["record_id"]

    if merged_df.empty:
        print("Waarschuwing: merge result is empty. No matching rows found.")

    merged_df.to_csv(output_file, index=False, sep=";", quoting=csv.QUOTE_ALL)
    print(f"Merged file written to {output_file}")
    return output_file


def write_ambiguous_assets_csv(ambiguous_records, output_file):
    # Als het voorkomt, dubbele DAM namen opvangen
    if not ambiguous_records:
        print("No ambiguous assets found.")
        return None

    ambiguous_df = pd.DataFrame(ambiguous_records)

    preferred_order = [
        "record_id",
        "filename",
        "match_count",
        "matched_uids",
        "matched_paths",
    ]
    existing_columns = [col for col in preferred_order if col in ambiguous_df.columns]
    remaining_columns = [col for col in ambiguous_df.columns if col not in existing_columns]
    ambiguous_df = ambiguous_df[existing_columns + remaining_columns]

    ambiguous_df.to_csv(output_file, index=False, sep=";", quoting=csv.QUOTE_ALL)
    print(f"Ambiguous assets written to {output_file}")
    return output_file


def find_assetid_by_filename(input_file, output_file, env, max_retries, ambiguous_output_file=None):
    api = get_api(env)

    if not Path(input_file).is_file():
        raise FileNotFoundError(f"File not found: {input_file}")

    df = pd.read_csv(input_file, delimiter=";", na_filter=False, dtype=str)

    if "filename" not in df.columns:
        raise ValueError("Input CSV must contain a 'filename' column.")

    results = []
    ambiguous_records = []

    for _, row in df.iterrows():
        filename = str(row["filename"]).strip()

        record_id = ""
        if "record_id" in df.columns:
            record_id = row["record_id"]
        elif "uuid" in df.columns:
            record_id = row["uuid"]

        print(f"Searching DAM for filename: {filename}")

        found = False

        for attempt in range(max_retries):
            try:
                response = api.search_dam(filename)

                if response.status_code != 200:
                    print(
                        f"API error while searching for '{filename}' "
                        f"(Attempt {attempt + 1}/{max_retries}): {response.text}"
                    )
                    time.sleep(1)
                    continue

                data = json.loads(response.text)
                entries = data.get("entries", [])

                if not entries:
                    print(f"No assets found for filename '{filename}'")

                    results.append(
                        {
                            "record_id": record_id,
                            "filename": filename,
                            "asset_id": "",
                        }
                    )

                    found = True
                    break

                exact_matches = [
                    asset
                    for asset in entries
                    if os.path.basename(asset.get("path", "")).strip() == filename
                ]

                match_count = len(exact_matches)

                if match_count == 0:
                    print(
                        f"No exact filename match found for '{filename}' "
                        f"among {len(entries)} DAM entries"
                    )

                    results.append(
                        {
                            "record_id": record_id,
                            "filename": filename,
                            "asset_id": "",
                        }
                    )

                    found = True
                    break

                if match_count == 1:
                    asset = exact_matches[0]
                    asset_id = str(asset.get("uid", ""))

                    print(f"Single exact match found for '{filename}': Asset ID = {asset_id}")

                    results.append(
                        {
                            "record_id": record_id,
                            "filename": filename,
                            "asset_id": asset_id,
                        }
                    )

                    found = True
                    break

                print(f"Multiple exact matches found for '{filename}': {match_count}")

                ambiguous_record = {
                    "record_id": record_id,
                    "filename": filename,
                    "match_count": match_count,
                    "matched_uids": ";".join(str(a.get("uid", "")) for a in exact_matches),
                    "matched_paths": ";".join(a.get("path", "") for a in exact_matches),
                }
                ambiguous_records.append(ambiguous_record)

                for asset in exact_matches:
                    print(
                        f" - UID: {asset.get('uid')}, "
                        f"path: {asset.get('path', '')}"
                    )

                # Keep main output safe for possible linking:
                # ambiguous rows get an empty asset_id
                results.append(
                    {
                        "record_id": record_id,
                        "filename": filename,
                        "asset_id": "",
                    }
                )

                found = True
                break

            except Exception as e:
                print(
                    f"Error while searching for '{filename}' "
                    f"(Attempt {attempt + 1}/{max_retries}): {e}"
                )
                time.sleep(1)

        if not found:
            print(f"Failed to retrieve asset for '{filename}' after {max_retries} attempts.")

            results.append(
                {
                    "record_id": record_id,
                    "filename": filename,
                    "asset_id": "",
                }
            )

    output_df = pd.DataFrame(results)

    column_order = ["record_id", "filename", "asset_id"]
    output_df = output_df[column_order]

    output_df.to_csv(output_file, index=False, sep=";", quoting=csv.QUOTE_ALL)
    print(f"Output written to {output_file}")

    if ambiguous_output_file is None:
        output_path = Path(output_file)
        ambiguous_output_file = str(
            output_path.with_name(f"{output_path.stem}_ambiguous{output_path.suffix}")
        )

    write_ambiguous_assets_csv(ambiguous_records, ambiguous_output_file)

    return output_file


def link_assetid_to_recordid(csv_file, env="acc", dryrun=True, log_file=None):
   
    # Dynamic logfile name if no name is provided
    if log_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fonds = Path(csv_file).stem.split("_")[0]
        log_file = Path(log_path, f"{fonds}_{timestamp}.log")     
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )
    logger = logging.getLogger(__name__)

    logger.info("Script started.")

    api = get_api(env)

    try:
        data = pd.read_csv(csv_file, delimiter=";", na_filter=False, dtype=str)
    except Exception as e:
        raise RuntimeError(f"Error reading CSV file: {e}")

    if "record_id" not in data.columns or "asset_id" not in data.columns:
        raise ValueError("CSV must contain 'record_id' and 'asset_id' columns.")

    logger.info(f"Read {len(data)} rows from {csv_file}")

    if dryrun:
        logger.info("Dry run mode: No actions will be performed.")
    else:
        logger.info("Execution mode: Links will be created.")

    success_count = 0
    error_count = 0
    skipped_count = 0

    for index, row in data.iterrows():
        record_id = row["record_id"]
        asset_id = str(row["asset_id"]).strip()

        logger.info(f"Processing: record_id={record_id}, asset_id={asset_id}")

        if not asset_id:
            skipped_count += 1
            logger.warning(
                f"Skipping row because asset_id is empty for record_id={record_id}"
            )
            continue

        if dryrun:
            logger.info(f"Dry run: Would link record_id={record_id} to asset_id={asset_id}")
            continue

        response = api.link_assets_to_record(record_id, str(asset_id), index + 1)
        if response.status_code == 200:
            success_count += 1
            logger.info(f"Successfully linked asset_id={asset_id} to record_id={record_id}")
        else:
            error_count += 1
            logger.error(f"Error linking asset_id={asset_id} to record_id={record_id}: {response.text}")

    logger.info("All done!")
    logger.info(f"Total successful links: {success_count}")
    logger.info(f"Total errors: {error_count}")
    logger.info(f"Total skipped rows (empty asset_id): {skipped_count}")


@click.group()
def cli():
    """CLI for files_per_fonds, find_assetid_by_filename, and link_assetid_to_recordid."""
    pass


@cli.command("files-per-fonds")
@click.argument("toegangsnummer")
@click.argument("env", type=click.Choice(["acc", "prod"]))
@click.option("--output-file", default=None, help="Output CSV file")
def cmd_files_per_fonds(toegangsnummer, env, output_file):
    """Haal bestanddelen op voor een toegangsnummer."""
    files_per_fonds(toegangsnummer, env, output_file)


@cli.command("find-assetid")
@click.argument("input_file")
@click.argument("output_file")
@click.argument("env", type=click.Choice(["acc", "prod"]))
@click.option("--max-retries", default=3, type=int, show_default=True)
@click.option(
    "--ambiguous-output-file",
    default=None,
    help="Optional CSV file for ambiguous asset matches",
)
def cmd_find_assetid(input_file, output_file, env, max_retries, ambiguous_output_file):
    """Zoek asset_id op basis van filename in een CSV."""
    find_assetid_by_filename(
        input_file,
        output_file,
        env,
        max_retries,
        ambiguous_output_file=ambiguous_output_file,
    )


@cli.command("link-assetid")
@click.argument("csv_file")
@click.option("--env", default="acc", type=click.Choice(["acc", "prod"]), show_default=True)
@click.option("--dryrun/--no-dryrun", default=True, show_default=True)
@click.option("--log-file", default=None, help="Optional custom log file")
def cmd_link_assetid(csv_file, env, dryrun, log_file):
    """Link asset_id aan record_id op basis van een CSV."""
    link_assetid_to_recordid(csv_file, env=env, dryrun=dryrun, log_file=log_file)


@cli.command("find-and-link")
@click.argument("input_file")
@click.argument("output_file")
@click.option("--env", default="acc", type=click.Choice(["acc", "prod"]), show_default=True)
@click.option("--max-retries", default=3, type=int, show_default=True)
@click.option("--dryrun/--no-dryrun", default=True, show_default=True)
@click.option("--log-file", default=None, help="Optional custom log file")
@click.option(
    "--ambiguous-output-file",
    default=None,
    help="Optional CSV file for ambiguous asset matches",
)
def cmd_find_and_link(
    input_file,
    output_file,
    env,
    max_retries,
    dryrun,
    log_file,
    ambiguous_output_file,
):
    """
    Zoek asset_id's en link ze daarna aan record_id's.

    Input CSV must contain:
    - filename
    - record_id
    """
    #input_file = Path(HOME_REPO, 'data', 'aip_downloads', 'source', input_file)
    #output_file =Path(HOME_REPO, 'data', 'aip_downloads', 'output', output_file)

    find_assetid_by_filename(
        input_file,
        output_file,
        env,
        max_retries,
        ambiguous_output_file=ambiguous_output_file,
    )
    link_assetid_to_recordid(output_file, env=env, dryrun=dryrun, log_file=log_file)


@cli.command("files-assets-link")
@click.argument("toegangsnummer")
@click.argument("mapping_csv")
@click.argument("merged_output")
@click.argument("asset_output")
@click.option("--env", default="acc", type=click.Choice(["acc", "prod"]), show_default=True)
@click.option("--join-on", default="uuid", show_default=True, help="Column used to join with mapping CSV")
@click.option("--max-retries", default=3, type=int, show_default=True)
@click.option("--dryrun/--no-dryrun", default=True, show_default=True)
@click.option("--log-file", default=None, help="Optional custom log file")
@click.option(
    "--ambiguous-output-file",
    default=None,
    help="Optional CSV file for ambiguous asset matches",
)
def cmd_files_assets_link(
    toegangsnummer,
    mapping_csv,
    merged_output,
    asset_output,
    env,
    join_on,
    max_retries,
    dryrun,
    log_file,
    ambiguous_output_file,
):
    """
    Pipeline:
    1. Get files per fonds
    2. Merge with separate filename CSV
    3. Find asset IDs
    4. Link asset IDs to record IDs
    """
    files_csv = files_per_fonds(toegangsnummer, env)
    merged_csv = merge_records_with_filenames(files_csv, mapping_csv, merged_output, join_on=join_on)
    find_assetid_by_filename(
        merged_csv,
        asset_output,
        env,
        max_retries,
        ambiguous_output_file=ambiguous_output_file,
    )
    link_assetid_to_recordid(asset_output, env=env, dryrun=dryrun, log_file=log_file)




if __name__ == "__main__":
    cli()