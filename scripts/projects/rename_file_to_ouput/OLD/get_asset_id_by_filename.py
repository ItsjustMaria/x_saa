## Import libraries
import os 
import sys
import csv
import simplejson as json
from datetime import time, datetime
from tqdm import tqdm
from uuid import uuid4
import pandas as pd
import re
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace, RDF, BNode, XSD
from collections import defaultdict
import logging
from rapidfuzz import fuzz
from pathlib import Path
import math, numpy as np
import time
#WORK_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\saa-nexus-scripts") # Adjust base path based on location
#HOME_REPO = Path(r"C:\\Users\\swart053\\Documents\\VSC\\test\\cli_module") # Adjust base path based on location
HOME_REPO = Path("/opt/lampp/htdocs/test/street_to_concept")
WORK_REPO = Path("/opt/lampp/htdocs/saa-nexus-scripts")
sys.path.append(str(WORK_REPO))
from modules import memorix
from modules import saa
from modules import wrapper

# -----------------------------------
# ENVIRONMENT SETUP
# -----------------------------------
def get_settings_file(env):
    if env == 'acc':
        PREFIX = 'https://ams-migrate.memorix.io'
        settings_file = Path(WORK_REPO, 'settings.json') 
        return settings_file
    elif env == 'prod':
        PREFIX = 'https://stadsarchiefamsterdam.memorix.io'
        settings_file = Path(WORK_REPO, 'settings.prod.json') 
        return settings_file
    elif env == 'tst':
        output = print(f'test output')
        return output
    else:
        raise ValueError("Environment must be 'acc' or 'prod'")

def get_api(env):
    settings_file = get_settings_file(env)
    settings = saa.readJsonFile(settings_file)
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