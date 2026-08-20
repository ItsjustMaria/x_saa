def obtain_values(inst, g):
    # get street and house number begin and end
    street_concept = g.value(subject=inst, predicate=IMAGE['street'])
    street_name_memorix = str(g.value(subject=street_concept, predicate=SKOS['prefLabel']))
    street_alternatief_manual = streets_memorix['alternatieve naam'][streets_memorix['concept']==street_concept.split('/')[-1]].item()
    if street_alternatief_manual!=street_alternatief_manual:
        street_alternatief_manual=""
    streets_alternatief_adamlink = alternatieve_straatnamen['altlabel'][alternatieve_straatnamen['label']==street_name_memorix].to_list()
    streets_alternatief_adamlink = list(map(str.lower,streets_alternatief_adamlink))
    housenr_begin = g.value(subject=inst, predicate=IMAGE['houseNumberBegin'])
    housenr_end = g.value(subject=inst, predicate=IMAGE['houseNumberEnd'])
    #logging.info(f"\t\t{print_streets(street_name_memorix,street_alternatief_manual,streets_alternatief_adamlink)}, {housenr_begin}, {housenr_end}")
    logging.info(f"\t\t{street_name_memorix}, {housenr_begin}, {housenr_end}")
    return street_name_memorix,street_alternatief_manual,streets_alternatief_adamlink,housenr_begin,housenr_end


def read_concept_turtle(s, g, s_str):
    
    match = re.search(r'/vocabularies/concepts/([^/>]+)', s_str)
    uuid = match.group(1) if match else ""

    prefLabel = next((str(lab) for lab in g.objects(s, SKOS.prefLabel)), "")
    exactMatch = next((str(em) for em in g.objects(s, SKOS.exactMatch)), "") # <-- fout: want exactMatch kan nu meer dan 1 waarde hebben
    scopeNote = next((str(sn) for sn in g.objects(s, SKOS.scopeNote)), "")

    concept_list.append({
        'concept_uuid' : uuid,
        'streetTextualValue' : prefLabel,
        'adamlink' : exactMatch,
        'scope' : scopeNote
    }) 
    
    total_concept_uuids.append(uuid)   
    return concept_list, total_concept_uuids