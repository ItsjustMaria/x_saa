

import pandas as pd
import ast
import sys
from rdflib import Graph, URIRef, Literal, Namespace, RDF, BNode, XSD

### initialize things ###
file = sys.argv[1]
toegangsnr = sys.argv[2]

# Define a namespace
record = Namespace("/resources/records/")
rt = Namespace("/resources/recordtypes/")
rico = Namespace("https://www.ica.org/standards/RiC/ontology#")
mmx = Namespace("http://memorix.io/ontology#") 
saa_nm = Namespace("https://data.archief.amsterdam/ontology#")
xsd = Namespace("http://www.w3.org/2001/XMLSchema#")
# concept = Namespace("/resources/vocabularies/concepts/")
# vocabularies = Namespace("/resources/vocabularies/conceptschemes/")
dr = Namespace("/resources/recordtypes/DigitalRecord#")
dd = Namespace("/resources/recordtypes/DigitalDossier#")
skos = Namespace("http://www.w3.org/2004/02/skos/core#")

df = pd.read_csv(file, encoding='utf-8', na_filter=False)

df_dd_dr = df[df["aggregatieniveau"].isin(["Dossier", "Record"])]

for index, row in df_dd_dr.iterrows():
    g = Graph()

    g.bind("record", record)
    g.bind("rt", rt)
    g.bind("rico", rico)
    g.bind("memorix", mmx)
    g.bind("saa", saa_nm)
    # g.bind("concept", concept)
    # g.bind("vocabularies", vocabularies)
    # g.bind("dd", dd)
    g.bind("skos", skos)

    ar_uri = BNode()
    g.add((ar_uri, RDF.type, mmx.AccessibilityAndRightsComponent))
    g.add((ar_uri, mmx.accessModeDisplay, mmx.DisplayAssets))
    g.add((ar_uri, mmx.accessModeDownload, Literal(True, datatype=XSD.boolean)))
    g.add((ar_uri, mmx.accessModeReservation, Literal(False, datatype=XSD.boolean)))
    g.add((ar_uri, mmx.accessModeScanningOnDemand, Literal(False, datatype=XSD.boolean)))
    g.add((ar_uri, mmx.attributionRequired, Literal(False, datatype=XSD.boolean)))
    g.add((ar_uri, mmx.audience, mmx.AudienceExternal))
    use_uri = URIRef(concept["e8a92b13-efaf-4b2e-e053-b784100a3466"])
    g.add((use_uri, RDF.type, skos.Concept))
    g.add((ar_uri, mmx.limitationOfUse, use_uri))
    g.add((ar_uri, mmx.physicallyAvailable, Literal(False, datatype=XSD.boolean)))
    raw_value = row.get("openbaarheid", None)
    openbaarheid_dict = ast.literal_eval(raw_value)
    if openbaarheid_dict.get("omschrijvingBeperkingen") == "Aanvraagformulier":
        access_uri = URIRef(concept["56b6ffe6-f801-4715-872b-303db35f48f9"])
        g.add((ar_uri, mmx.limitationOfAccess, access_uri))
        g.add((access_uri, RDF.type, skos.Concept))
        g.add((ar_uri, mmx.restrictionsExpire, Literal(openbaarheid_dict.get("datum"), datatype=XSD.date)))
    if openbaarheid_dict.get("omschrijvingBeperkingen") is None:
        access_uri = URIRef(concept["b91d25b5-a1b4-4bc9-a15c-d48883a95d0b"])
        g.add((ar_uri, mmx.limitationOfAccess, access_uri))
        g.add((access_uri, RDF.type, skos.Concept))

    g.serialize(f"E:/wabo/bwt/{toegangsnr}/rechten/{row["uuid"]}.ttl", format="turtle", encoding='utf-8')
    print(f"Turtle gemaakt voor rechten {row["uuid"]}")
