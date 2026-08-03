import os
import requests
import gspread
from requests.auth import HTTPBasicAuth

def extract_employee_name(reg):
    """Zoekt slim in de gehele urenregistratie naar de naam van de monteur."""
    if not isinstance(reg, dict): return "Onbekend"
    reg_str = str(reg).lower()
    
    if "sjon" in reg_str or "koster" in reg_str: return "Sjon"
    elif "ramazan" in reg_str: return "Ramazan"
    elif "rik" in reg_str: return "Rik"
    elif "mark" in reg_str: return "Mark"
    elif "remco" in reg_str: return "Remco"
        
    for key in ["employeeName", "workerName", "userName", "createdByName", "displayName", "name"]:
        val = reg.get(key)
        if isinstance(val, str) and val.strip(): return val.strip()
            
    for dict_key in ["employee", "worker", "user", "createdBy"]:
        obj = reg.get(dict_key)
        if isinstance(obj, dict):
            full = f"{obj.get('firstName', '')} {obj.get('lastName', '')}".strip()
            if full: return full
            for name_key in ["name", "label", "displayName", "username", "formattedName"]:
                val = obj.get(name_key)
                if isinstance(val, str) and val.strip(): return val.strip()
    return "Onbekend"

def bepaal_ketelmerk(titel):
    titel_lower = str(titel).lower()
    if "remeha" in titel_lower: return "Remeha"
    elif "nefit" in titel_lower: return "Nefit"
    elif "intergas" in titel_lower: return "Intergas"
    elif "vaillant" in titel_lower: return "Vaillant"
    elif "atag" in titel_lower: return "Atag"
    elif "brink" in titel_lower: return "Brink"
    elif "ferroli" in titel_lower: return "Ferroli"
    elif "itho" in titel_lower or "daalderop" in titel_lower: return "Itho Daalderop"
    else: return "Overig / Onbekend"

def bepaal_contract_soort(titel):
    """Herken het soort contract uit de titel van de werkbon."""
    titel_lower = str(titel).lower()
    if "comfort plus" in titel_lower: return "Comfort Plus"
    elif "comfort" in titel_lower: return "Comfort"
    elif "basis" in titel_lower: return "Basis"
    elif "eenmalig" in titel_lower: return "Eenmalig"
    else: return "Geen / Onbekend"

def bepaal_voorrijtijd_uren(zoek_tekst):
    tekst = str(zoek_tekst).lower()
    if "biddinghuizen" in tekst: return 0.25  # 15 minuten
    elif "dronten" in tekst: return 0.50      # 30 minuten
    elif "swifterbant" in tekst: return 0.50  # 30 minuten
    elif "lelystad" in tekst: return 0.75     # 45 minuten
    elif "almere" in tekst: return 1.00       # 60 minuten
    else: return 0.75                         # Overig = 45 minuten

def bereken_totale_opbrengst_onderhoud(titel):
    titel_lower = titel.lower()
    totale_opbrengst = 0.0
    aantal_comfort_plus = titel_lower.count("comfort plus")
    totale_opbrengst += aantal_comfort_plus * 362.00
    titel_verwerkt = titel_lower.replace("comfort plus", "")
    aantal_comfort = titel_verwerkt.count("comfort")
    totale_opbrengst += aantal_comfort * 309.00
    aantal_basis = titel_verwerkt.count("basis")
    totale_opbrengst += aantal_basis * 223.00
    aantal_eenmalig = titel_verwerkt.count("eenmalig")
    totale_opbrengst += aantal_eenmalig * 110.00
    return 300.00 if totale_opbrengst == 0.0 else totale_opbrengst

def bereken_opbrengst_storing(contract_soort, totale_uren):
    """
    Bij Comfort (Plus) is de opbrengst €0. 
    Bij andere contracten rekenen we €75 * (Gemaakte uren + Voorrijtijd).
    """
    UURLOON_KLANT = 75.00
    if contract_soort in ["Comfort Plus", "Comfort"]:
        return 0.00
    else:
        return round(totale_uren * UURLOON_KLANT, 2)

def vind_stad(bon):
    """Zoekt de stad op basis van de officiële Robaws OpenAPI specificatie."""
    if not isinstance(bon, dict): return "Onbekend"
    addr = bon.get("address")
    if isinstance(addr, dict) and addr.get("city"): return str(addr.get("city")).strip().title()
    p_addr = bon.get("projectAddress")
    if isinstance(p_addr, dict) and p_addr.get("city"): return str(p_addr.get("city")).strip().title()
    cust = bon.get("client") or bon.get("customer")
    if isinstance(cust, dict):
        if cust.get("city"): return str(cust.get("city")).strip().title()
        c_addr = cust.get("address")
        if isinstance(c_addr, dict) and c_addr.get("city"): return str(c_addr.get("city")).strip().title()
    if bon.get("city"): return str(bon.get("city")).strip().title()
    return "Onbekend"

def main():
    robaws_key = os.environ.get("ROBAWS_API_KEY")
    robaws_secret = os.environ.get("ROBAWS_SECRET")
    sheet_id = os.environ.get("SHEET_ID")
    sheet_name = os.environ.get("SHEET_NAME", "Blad1")
    credentials_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if not robaws_key or not robaws_secret or not sheet_id:
        print("Fout: Inloggegevens ontbreken.")
        return

    auth = HTTPBasicAuth(robaws_key, robaws_secret)
    gc = gspread.service_account(filename=credentials_file)
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.worksheet(sheet_name)
    
    # 🎯 17 KOLOMMEN (VOORRIJTIJD GEHEEL ACHTERAAN TOEGEVOEGD)
    headers = [
        "Werkbon ID",           # 1
        "Nummer",               # 2
        "Datum",                # 3
        "Werknemer",            # 4
        "Uren",                 # 5 (Puur de gemaakte uren uit Robaws!)
        "Opmerking Werknemer",  # 6
        "Status Werkbon",       # 7
        "Titel / Omschrijving", # 8
        "Onderhoud",            # 9
        "Opbrengst (€)",        # 10
        "Kosten (€)",           # 11
        "Marge (€)",            # 12
        "Type Werkbon",         # 13
        "Ketelmerk",            # 14
        "Stad",                 # 15
        "Contract",             # 16
        "Voorrijtijd (uren)"    # 17 (NIEUW ACHTERAAN)
    ]
    
    bestaande_data = worksheet.get_all_values()
    nieuwe_rijen_dict = {}
    
    if bestaande_data:
        oude_headers = bestaande_data[0]
        for i, rij in enumerate(bestaande_data):
            if i == 0: continue
            if len(rij) > 2 and rij[2] < "2026-07-01":
                sleutel = f"{rij[0]}_{rij[3]}"
                
                def get_val(kolom_naam):
                    try:
                        idx = oude_headers.index(kolom_naam)
                        return rij[idx] if idx < len(rij) else ""
                    except ValueError:
                        return ""

                herbouwde_rij = [
                    get_val("Werkbon ID"), get_val("Nummer"), get_val("Datum"), get_val("Werknemer"), 
                    get_val("Uren"), get_val("Opmerking Werknemer"), get_val("Status Werkbon"), 
                    get_val("Titel / Omschrijving"), get_val("Onderhoud"), get_val("Opbrengst (€)"), 
                    get_val("Kosten (€)"), get_val("Marge (€)"), get_val("Type Werkbon"), get_val("Ketelmerk"),
                    get_val("Stad"), get_val("Contract"), get_val("Voorrijtijd (uren)")
                ]
                nieuwe_rijen_dict[sleutel] = herbouwde_rij

    print("=== STAP 1: WERKBONNEN VERZAMELEN UIT ROBAWS ===")
    all_found_work_orders = {}

    def process_items(items):
        added = 0
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and "id" in item:
                    item_id = item["id"]
                    if item_id not in all_found_work_orders:
                        all_found_work_orders[item_id] = item
                        added += 1
        return added

    try:
        r_base = requests.get("https://app.robaws.com/api/v2/work-orders?includeArchived=true", auth=auth)
        if r_base.status_code == 200:
            d_base = r_base.json()
            process_items(d_base.get("items", d_base.get("data", [])) if isinstance(d_base, dict) else d_base)
    except Exception:
        pass

    pagination_tests = [
        {"page": 0, "size": 100}, {"page": 1, "size": 100}, {"page": 2, "size": 100},
        {"offset": 20, "limit": 100}, {"offset": 100, "limit": 100},
        {"q": "Onderhoudsbeurt CV:"}, {"q": "Storing:"}, {"search": "Onderhoudsbeurt CV:"}, {"search": "Storing:"}
    ]

    for params in pagination_tests:
        p_params = {"includeArchived": "true"}
        p_params.update(params)
        try:
            resp = requests.get("https://app.robaws.com/api/v2/work-orders", auth=auth, params=p_params)
            if resp.status_code == 200:
                d = resp.json()
                process_items(d.get("items", d.get("data", [])) if isinstance(d, dict) else d)
        except Exception:
            pass

    if len(all_found_work_orders) > 0:
        known_ids = [int(i) for i in all_found_work_orders.keys() if str(i).isdigit()]
        if known_ids:
            min_id, max_id = min(known_ids), max(known_ids)
            for test_id in range(max(1, min_id - 100), max_id + 100):
                if test_id not in all_found_work_orders:
                    try:
                        r_single = requests.get(f"https://app.robaws.com/api/v2/work-orders/{test_id}?include=address,client", auth=auth)
                        if r_single.status_code == 200:
                            item_single = r_single.json()
                            if isinstance(item_single, dict) and "id" in item_single:
                                all_found_work_orders[item_single["id"]] = item_single
                    except Exception:
                        pass

    if len(all_found_work_orders) == 0:
        print("WAARSCHUWING: 0 werkbonnen opgehaald. Google Sheets blijft ongewijzigd.")
        return

    # STAP 2: Filteren op datum
    target_work_orders = []
    for item_id, bon in all_found_work_orders.items():
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        bon_title_lower = (bon.get("title") or bon.get("description") or "").lower()
        if "storing:" in bon_title_lower or "onderhoudsbeurt cv:" in bon_title_lower:
            target_work_orders.append(bon)

    if len(target_work_orders) == 0:
        print("Geen relevante werkbonnen gevonden.")
        return

    # STAP 3: Uren & Eigenschappen verzamelen
    print("\n=== STAP 3: UREN, STAD, CONTRACT & FINANCIËN BEREKENEN ===")
    tijdelijke_registraties = []
    sjon_dag_uren = {}

    for bon in target_work_orders:
        bon_id = str(bon.get("id"))
        bon_number = bon.get("number") or bon.get("code") or ""
        bon_date = bon.get("date", "")
        bon_title = bon.get("title") or bon.get("description") or ""

        status = bon.get("status", "")
        if isinstance(status, dict):
            status = status.get("name") or status.get("label") or str(status)
        if bon.get("archivedAt") or bon.get("archived") or bon.get("isArchived"):
            if "gearchiveerd" not in str(status).lower():
                status = f"{status} (Gearchiveerd)"

        extra_fields = bon.get("extraFields", {})
        onderhoud_waarde = ""
        for key, value in extra_fields.items():
            if key.lower() == "onderhoud":
                if isinstance(value, dict):
                    onderhoud_waarde = "Ja" if value.get("booleanValue") else value.get("stringValue", "")
                else:
                    onderhoud_waarde = str(value)
                break

        stad = vind_stad(bon)
        ketelmerk = bepaal_ketelmerk(bon_title)
        contract = bepaal_contract_soort(bon_title)
        bon_title_lower = bon_title.lower()
        type_werkbon = "Storing" if "storing:" in bon_title_lower else "Onderhoud"
        
        zoek_locatie_tekst = f"{bon_title} {stad} {bon.get('address', '')} {bon.get('customerName', '')}"
        voorrijtijd_extra = bepaal_voorrijtijd_uren(zoek_locatie_tekst) if type_werkbon == "Storing" else 0.0

        time_entries = []
        try:
            r_detail = requests.get(
                f"https://app.robaws.com/api/v2/work-orders/{bon_id}?include=address,client,projectAddress,timeEntries,timeEntries.employee,hourRegistrations,hourRegistrations.employee,employee",
                auth=auth
            )
            if r_detail.status_code == 200:
                d_detail = r_detail.json()
                if stad == "Onbekend": stad = vind_stad(d_detail)
                    
                for k in ["timeEntries", "hourRegistrations", "timeRegistrations", "activities"]:
                    if k in d_detail and isinstance(d_detail[k], list) and len(d_detail[k]) > 0:
                        time_entries = d_detail[k]
                        break
        except Exception:
            pass

        if isinstance(time_entries, list) and len(time_entries) > 0:
            for index, reg in enumerate(time_entries):
                if not isinstance(reg, dict): continue
                
                werknemer_naam = extract_employee_name(reg)
                basis_uren = float(reg.get("hours") or reg.get("duration") or 0.0)
                opmerking = reg.get("remark") or reg.get("comment") or ""

                # PUUR GEMAAKTE UREN (ZONDER VOORRIJTIJD)
                aantal_uren = basis_uren
                
                # Voorrijtijd op de 1e regel zetten van een storing
                rij_voorrijtijd = voorrijtijd_extra if (index == 0 and type_werkbon == "Storing") else 0.0
                
                # Totale inzettijd voor de kosten/opbrengst berekening
                totale_inzet_uren = aantal_uren + rij_voorrijtijd

                if type_werkbon == "Storing":
                    rij_opbrengst = bereken_opbrengst_storing(contract, totale_inzet_uren)
                else:
                    rij_opbrengst = bereken_totale_opbrengst_onderhoud(bon_title) if index == 0 else 0.0

                if "sjon" in werknemer_naam.lower():
                    sjon_dag_uren[bon_date] = sjon_dag_uren.get(bon_date, 0.0) + totale_inzet_uren

                tijdelijke_registraties.append({
                    "bon_id": bon_id, "bon_number": bon_number, "bon_date": bon_date, "werknemer_naam": werknemer_naam,
                    "aantal_uren": aantal_uren, "voorrijtijd": rij_voorrijtijd, "totale_inzet_uren": totale_inzet_uren,
                    "opmerking": opmerking, "status": status, "bon_title": bon_title,
                    "ketelmerk": ketelmerk, "onderhoud_waarde": onderhoud_waarde, "type_werkbon": type_werkbon,
                    "stad": stad, "contract": contract, "opbrengst": rij_opbrengst
                })
        else:
            tijdelijke_registraties.append({
                "bon_id": bon_id, "bon_number": bon_number, "bon_date": bon_date, "werknemer_naam": "Geen uren geregistreerd",
                "aantal_uren": 0.0, "voorrijtijd": voorrijtijd_extra if type_werkbon == "Storing" else 0.0,
                "totale_inzet_uren": voorrijtijd_extra if type_werkbon == "Storing" else 0.0,
                "opmerking": "", "status": status, "bon_title": bon_title,
                "ketelmerk": ketelmerk, "onderhoud_waarde": onderhoud_waarde, "type_werkbon": type_werkbon,
                "stad": stad, "contract": contract, "opbrengst": 0.0
            })

    # STAP 4: Financiën Berekenen
    for item in tijdelijke_registraties:
        naam_klein = item["werknemer_naam"].lower()
        uren_voor_kosten = item["totale_inzet_uren"]
        bon_date = item["bon_date"]

        if "sjon" in naam_klein:
            totale_uren_sjon_vandaag = sjon_dag_uren.get(bon_date, 0.0)
            kosten = round((uren_voor_kosten / totale_uren_sjon_vandaag) * 240.00, 2) if totale_uren_sjon_vandaag > 0 else 0.0
        elif "ramazan" in naam_klein: kosten = 60.00
        elif "rik" in naam_klein: kosten = round(uren_voor_kosten * 40.00, 2)
        elif "mark" in naam_klein or "remco" in naam_klein: kosten = round(uren_voor_kosten * 45.00, 2)
        else: kosten = round(uren_voor_kosten * 30.00, 2)

        marge = round(item["opbrengst"] - kosten, 2)

        rij = [
            item["bon_id"],            # 1
            item["bon_number"],        # 2
            item["bon_date"],          # 3
            item["werknemer_naam"],    # 4
            item["aantal_uren"],       # 5 (Puur gemaakte uren)
            item["opmerking"],         # 6
            item["status"],            # 7
            item["bon_title"],         # 8
            item["onderhoud_waarde"],  # 9
            item["opbrengst"],         # 10
            kosten,                    # 11
            marge,                     # 12
            item["type_werkbon"],      # 13
            item["ketelmerk"],         # 14
            item["stad"],              # 15
            item["contract"],          # 16
            item["voorrijtijd"]        # 17 (NIEUW ACHTERAAN)
        ]
        sleutel = f"{item['bon_id']}_{item['werknemer_naam']}"
        nieuwe_rijen_dict[sleutel] = rij

    # STAP 5: Wegschrijven naar Google Sheets
    definitieve_rijen = list(nieuwe_rijen_dict.values())
    definitieve_rijen.sort(key=lambda x: str(x[2]))
    
    worksheet.clear()
    worksheet.append_rows([headers] + definitieve_rijen)
    print(f"Succes! Voorrijtijd losgekoppeld van gemaakte uren en als Kolom 17 achteraan toegevoegd! ({len(definitieve_rijen)} rijen opgeslagen).")

if __name__ == "__main__":
    main()
