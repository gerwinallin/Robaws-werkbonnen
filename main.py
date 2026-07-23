import os
import requests
import gspread
from requests.auth import HTTPBasicAuth

def extract_employee_name(reg):
    """Zoekt slim in de gehele urenregistratie naar de naam van de monteur."""
    if not isinstance(reg, dict):
        return "Onbekend"
    
    reg_str = str(reg).lower()
    
    if "sjon" in reg_str or "koster" in reg_str:
        return "Sjon"
    elif "ramazan" in reg_str:
        return "Ramazan"
    elif "rik" in reg_str:
        return "Rik"
    elif "mark" in reg_str:
        return "Mark"
    elif "remco" in reg_str:
        return "Remco"
        
    for key in ["employeeName", "workerName", "userName", "createdByName", "displayName", "name"]:
        val = reg.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
            
    for dict_key in ["employee", "worker", "user", "createdBy"]:
        obj = reg.get(dict_key)
        if isinstance(obj, dict):
            fn = obj.get("firstName") or obj.get("first_name") or ""
            ln = obj.get("lastName") or obj.get("last_name") or ""
            full = f"{fn} {ln}".strip()
            if full:
                return full
            for name_key in ["name", "label", "displayName", "username", "formattedName"]:
                val = obj.get(name_key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
                    
    return "Onbekend"

def bepaal_ketelmerk(titel):
    """Herken het merk van de CV-ketel/installatie uit de titel."""
    titel_lower = str(titel).lower()
    
    if "remeha" in titel_lower:
        return "Remeha"
    elif "nefit" in titel_lower:
        return "Nefit"
    elif "intergas" in titel_lower:
        return "Intergas"
    elif "vaillant" in titel_lower:
        return "Vaillant"
    elif "atag" in titel_lower:
        return "Atag"
    elif "brink" in titel_lower:
        return "Brink"
    elif "ferroli" in titel_lower:
        return "Ferroli"
    elif "itho" in titel_lower or "daalderop" in titel_lower:
        return "Itho Daalderop"
    else:
        return "Overig / Onbekend"

def bepaal_voorrijtijd_uren(zoek_tekst):
    """Bepaalt de vaste voorrijtijd in uren uitsluitend voor STORINGEN."""
    tekst = str(zoek_tekst).lower()
    
    if "biddinghuizen" in tekst:
        return 0.25  # 15 minuten
    elif "dronten" in tekst:
        return 0.50  # 30 minuten
    elif "swifterbant" in tekst:
        return 0.50  # 30 minuten
    elif "lelystad" in tekst:
        return 0.75  # 45 minuten
    elif "almere" in tekst:
        return 1.00  # 60 minuten
    else:
        return 0.75  # Overig = 45 minuten

def bereken_totale_opbrengst_onderhoud(titel):
    """Scant de titel van een ONDERHOUDSBEURT en telt alle apparaten/contracten op."""
    titel_lower = titel.lower()
    totale_opbrengst = 0.0

    # 1. Comfort Plus (€ 362)
    aantal_comfort_plus = titel_lower.count("comfort plus")
    totale_opbrengst += aantal_comfort_plus * 362.00
    titel_verwerkt = titel_lower.replace("comfort plus", "")

    # 2. Comfort (€ 309)
    aantal_comfort = titel_verwerkt.count("comfort")
    totale_opbrengst += aantal_comfort * 309.00

    # 3. Basis (€ 223)
    aantal_basis = titel_verwerkt.count("basis")
    totale_opbrengst += aantal_basis * 223.00

    # 4. Eenmalig (€ 110)
    aantal_eenmalig = titel_verwerkt.count("eenmalig")
    totale_opbrengst += aantal_eenmalig * 110.00

    if totale_opbrengst == 0.0:
        return 300.00
    
    return totale_opbrengst

def bereken_opbrengst_storing(titel):
    """Bepaalt de opbrengst bij STORINGEN op basis van de contractvorm."""
    titel_lower = titel.lower()

    if "comfort plus" in titel_lower or "comfort" in titel_lower:
        return 0.00
    elif "basis" in titel_lower:
        return 223.00
    elif "eenmalig" in titel_lower:
        return 110.00
    else:
        return 300.00

def main():
    # 1. Inloggegevens en Omgevingsvariabelen ophalen
    robaws_key = os.environ.get("ROBAWS_API_KEY")
    robaws_secret = os.environ.get("ROBAWS_SECRET")
    sheet_id = os.environ.get("SHEET_ID")
    sheet_name = os.environ.get("SHEET_NAME", "Blad1")
    credentials_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if not robaws_key or not robaws_secret or not sheet_id:
        print("Fout: Inloggegevens ontbreken.")
        return

    auth = HTTPBasicAuth(robaws_key, robaws_secret)

    # === GOOGLE SHEETS VOORBEREIDEN ===
    gc = gspread.service_account(filename=credentials_file)
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.worksheet(sheet_name)
    
    headers = [
        "Werkbon ID", "Nummer", "Datum", "Werknemer", "Uren", 
        "Opmerking Werknemer", "Status Werkbon", "Titel / Omschrijving", 
        "Ketelmerk", "Onderhoud", "Type Werkbon", "Opbrengst (€)", "Kosten (€)", "Marge (€)"
    ]
    
    bestaande_data = worksheet.get_all_values()
    
    # 🗑️ SCHONE LEI LATER GARANDEREN:
    # We bewaren alleen historische data van vóór 1 juli 2026 (indien aanwezig).
    # Alles vanaf 1 juli 2026 wordt vers opgebouwd uit Robaws. 
    # Als een bon in Robaws is gewist, verdwijnt hij hierdoor automatisch uit de Sheet!
    nieuwe_rijen_dict = {}
    if bestaande_data:
        for i, rij in enumerate(bestaande_data):
            if i == 0: continue
            if len(rij) > 2 and rij[2] < "2026-07-01":
                sleutel = f"{rij[0]}_{rij[3]}"
                nieuwe_rijen_dict[sleutel] = rij

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
            items_base = d_base.get("items", d_base.get("data", [])) if isinstance(d_base, dict) else d_base
            process_items(items_base)
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
                its = d.get("items", d.get("data", [])) if isinstance(d, dict) else d
                process_items(its)
        except Exception:
            pass

    if len(all_found_work_orders) > 0:
        known_ids = [int(i) for i in all_found_work_orders.keys() if str(i).isdigit()]
        if known_ids:
            min_id, max_id = min(known_ids), max(known_ids)
            for test_id in range(max(1, min_id - 100), max_id + 100):
                if test_id not in all_found_work_orders:
                    try:
                        r_single = requests.get(f"https://app.robaws.com/api/v2/work-orders/{test_id}", auth=auth)
                        if r_single.status_code == 200:
                            item_single = r_single.json()
                            if isinstance(item_single, dict) and "id" in item_single:
                                all_found_work_orders[item_single["id"]] = item_single
                    except Exception:
                        pass

    if len(all_found_work_orders) == 0:
        print("WAARSCHUWING: 0 werkbonnen opgehaald. Google Sheets blijft ongewijzigd.")
        return

    # STAP 2: Filteren op datum (vanaf 1 juli 2026) en titel-matchen
    target_work_orders = []
    for item_id, bon in all_found_work_orders.items():
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        bon_title = bon.get("title") or bon.get("description") or ""
        bon_title_lower = bon_title.lower()
        
        if "storing:" in bon_title_lower or "onderhoudsbeurt cv:" in bon_title_lower:
            target_work_orders.append(bon)

    if len(target_work_orders) == 0:
        print("Geen relevante werkbonnen gevonden.")
        return

    # STAP 3: Uren verzamelen, Ketelmerk bepalen & Voorrijtijd berekenen
    print("\n=== STAP 3: UREN, KETELMERK & VOORRIJTIJD VERZAMELEN ===")
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

        # 🏷️ KETELMERK BEPALEN
        ketelmerk = bepaal_ketelmerk(bon_title)

        # 🎯 TYPE WERKBON, OPBRENGST & VOORRIJTIJD BEPALEN
        bon_title_lower = bon_title.lower()
        if "storing:" in bon_title_lower:
            type_werkbon = "Storing"
            opbrengst = bereken_opbrengst_storing(bon_title)
            
            # Voorrijtijd ALLEEN ophalen bij STORINGEN:
            zoek_locatie_tekst = f"{bon_title} {bon.get('city', '')} {bon.get('address', '')} {bon.get('customerName', '')}"
            voorrijtijd_extra = bepaal_voorrijtijd_uren(zoek_locatie_tekst)
        else:
            type_werkbon = "Onderhoud"
            opbrengst = bereken_totale_opbrengst_onderhoud(bon_title)
            voorrijtijd_extra = 0.0

        time_entries = []
        try:
            r_detail = requests.get(
                f"https://app.robaws.com/api/v2/work-orders/{bon_id}?include=timeEntries,timeEntries.employee,hourRegistrations,hourRegistrations.employee,employee",
                auth=auth
            )
            if r_detail.status_code == 200:
                d_detail = r_detail.json()
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

                if index == 0 and type_werkbon == "Storing":
                    aantal_uren = round(basis_uren + voorrijtijd_extra, 2)
                else:
                    aantal_uren = basis_uren

                if "sjon" in werknemer_naam.lower():
                    sjon_dag_uren[bon_date] = sjon_dag_uren.get(bon_date, 0.0) + aantal_uren

                tijdelijke_registraties.append({
                    "bon_id": bon_id,
                    "bon_number": bon_number,
                    "bon_date": bon_date,
                    "werknemer_naam": werknemer_naam,
                    "aantal_uren": aantal_uren,
                    "opmerking": opmerking,
                    "status": status,
                    "bon_title": bon_title,
                    "ketelmerk": ketelmerk,
                    "onderhoud_waarde": onderhoud_waarde,
                    "type_werkbon": type_werkbon,
                    "opbrengst": opbrengst
                })
        else:
            totaal_uren = voorrijtijd_extra if type_werkbon == "Storing" else 0.0
            tijdelijke_registraties.append({
                "bon_id": bon_id,
                "bon_number": bon_number,
                "bon_date": bon_date,
                "werknemer_naam": "Geen uren geregistreerd",
                "aantal_uren": totaal_uren,
                "opmerking": "",
                "status": status,
                "bon_title": bon_title,
                "ketelmerk": ketelmerk,
                "onderhoud_waarde": onderhoud_waarde,
                "type_werkbon": type_werkbon,
                "opbrengst": opbrengst
            })

    # STAP 4: Financiën Berekenen
    print("=== STAP 4: KOSTEN EN MARGE BEREKENEN ===")
    for item in tijdelijke_registraties:
        werknemer_naam = item["werknemer_naam"]
        naam_klein = werknemer_naam.lower()
        aantal_uren = item["aantal_uren"]
        bon_date = item["bon_date"]
        opbrengst = item["opbrengst"]

        if "sjon" in naam_klein:
            totale_uren_sjon_vandaag = sjon_dag_uren.get(bon_date, 0.0)
            if totale_uren_sjon_vandaag > 0:
                kosten = round((aantal_uren / totale_uren_sjon_vandaag) * 240.00, 2)
            else:
                kosten = 0.0
        elif "ramazan" in naam_klein:
            kosten = 60.00
        elif "rik" in naam_klein:
            kosten = round(aantal_uren * 40.00, 2)
        elif "mark" in naam_klein or "remco" in naam_klein:
            kosten = round(aantal_uren * 45.00, 2)
        else:
            kosten = round(aantal_uren * 30.00, 2)

        marge = round(opbrengst - kosten, 2)

        rij = [
            item["bon_id"], item["bon_number"], item["bon_date"], werknemer_naam,
            aantal_uren, item["opmerking"], item["status"], item["bon_title"],
            item["ketelmerk"], item["onderhoud_waarde"], item["type_werkbon"],
            opbrengst, kosten, marge
        ]

        sleutel = f"{item['bon_id']}_{werknemer_naam}"
        nieuwe_rijen_dict[sleutel] = rij

    # STAP 5: WEGSCHRIJVEN NAAR GOOGLE SHEETS
    definitieve_rijen = list(nieuwe_rijen_dict.values())
    definitieve_rijen.sort(key=lambda x: str(x[2]))
    
    worksheet.clear()
    worksheet.append_rows([headers] + definitieve_rijen)
    print(f"Succes! Google Sheets opschoond, ketelmerk toegevoegd en geüpdatet ({len(definitieve_rijen)} rijen opgeslagen).")

if __name__ == "__main__":
    main()
