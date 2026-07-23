import os
import requests
import gspread
from requests.auth import HTTPBasicAuth

def extract_employee_name(reg):
    """Zoekt slim in alle mogelijke Robaws-velden naar de naam van de monteur."""
    if not isinstance(reg, dict):
        return "Onbekend"
    
    # 1. Directe tekstvelden
    for key in ["employeeName", "workerName", "userName", "createdByName"]:
        val = reg.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
            
    # 2. Geneste objecten (employee, worker, user)
    for dict_key in ["employee", "worker", "user", "createdBy"]:
        obj = reg.get(dict_key)
        if isinstance(obj, dict):
            fn = obj.get("firstName") or obj.get("first_name") or ""
            ln = obj.get("lastName") or obj.get("last_name") or ""
            full = f"{fn} {ln}".strip()
            if full:
                return full
            for name_key in ["name", "label", "displayName", "username"]:
                val = obj.get(name_key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
                    
    return "Onbekend"

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

    # === GOOGLE SHEETS VOORBEREIDEN (Huidige data uitlezen) ===
    gc = gspread.service_account(filename=credentials_file)
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.worksheet(sheet_name)
    
    bestaande_data = worksheet.get_all_values()
    headers = ["Werkbon ID", "Nummer", "Datum", "Werknemer", "Uren", "Opmerking Werknemer", "Status Werkbon", "Titel / Omschrijving", "Onderhoud", "Opbrengst (€)", "Kosten (€)", "Marge (€)"]
    
    if not bestaande_data:
        bestaande_data = [headers]
        
    bestaande_rijen_dict = {}
    for i, rij in enumerate(bestaande_data):
        if i == 0: continue
        if len(rij) > 3:
            sleutel = f"{rij[0]}_{rij[3]}"
            bestaande_rijen_dict[sleutel] = rij

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
        {"q": "Onderhoudsbeurt"}, {"search": "Onderhoudsbeurt"}
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

    # STAP 2: Filteren op datum en titel
    target_work_orders = []
    for item_id, bon in all_found_work_orders.items():
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        bon_title = bon.get("title") or bon.get("description") or ""
        if "onderhoudsbeurt" in bon_title.lower():
            target_work_orders.append(bon)

    if len(target_work_orders) == 0:
        print("Geen relevante onderhoudsbeurten gevonden.")
        return

    # STAP 3: Uren verzamelen & Sjon dag-totalen opbouwen
    print("\n=== STAP 3: UREN VERZAMELEN & DAGTOTALEN BEPALEN ===")
    tijdelijke_registraties = []
    sjon_dag_uren = {}  # Onthoudt per datum de totale uren van Sjon

    for bon in target_work_orders:
        bon_id = str(bon.get("id"))
        bon_number = bon.get("number") or bon.get("code") or ""
        bon_date = bon.get("date", "")
        bon_title = bon.get("title") or bon.get("description") or ""

        # Verwijder oude versies van deze werkbon uit de tijdelijke dict (voorkomt dubbele Onbekend rijen)
        keys_to_remove = [k for k in bestaande_rijen_dict.keys() if k.startswith(f"{bon_id}_")]
        for k in keys_to_remove:
            del bestaande_rijen_dict[k]

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
                
        # Opbrengst bepalen
        titel_lower = bon_title.lower()
        opbrengst = 0.0
        
        if "comfort plus" in titel_lower:
            opbrengst = 362.00
        elif "comfort" in titel_lower:
            opbrengst = 309.00
        elif "basis" in titel_lower:
            opbrengst = 223.00
        elif "eenmalig" in titel_lower:
            opbrengst = 110.00
        elif "huurketel" in titel_lower:
            opbrengst = 150.00

        time_entries = []
        try:
            r_detail = requests.get(f"https://app.robaws.com/api/v2/work-orders/{bon_id}?include=timeEntries,employee,worker,user", auth=auth)
            if r_detail.status_code == 200:
                d_detail = r_detail.json()
                for k in ["timeEntries", "hourRegistrations", "timeRegistrations", "activities"]:
                    if k in d_detail and isinstance(d_detail[k], list) and len(d_detail[k]) > 0:
                        time_entries = d_detail[k]
                        break
        except Exception:
            pass

        if isinstance(time_entries, list) and len(time_entries) > 0:
            for reg in time_entries:
                if not isinstance(reg, dict): continue
                
                werknemer_naam = extract_employee_name(reg)
                aantal_uren = float(reg.get("hours") or reg.get("duration") or 0.0)
                opmerking = reg.get("remark") or reg.get("comment") or ""

                # Optellen uren Sjon per dag
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
                    "onderhoud_waarde": onderhoud_waarde,
                    "opbrengst": opbrengst
                })
        else:
            tijdelijke_registraties.append({
                "bon_id": bon_id,
                "bon_number": bon_number,
                "bon_date": bon_date,
                "werknemer_naam": "Geen uren geregistreerd",
                "aantal_uren": 0.0,
                "opmerking": "",
                "status": status,
                "bon_title": bon_title,
                "onderhoud_waarde": onderhoud_waarde,
                "opbrengst": opbrengst
            })

    # STAP 4: Financiën Berekenen (Inclusief Pro-Rata Vaste Kosten Sjon)
    print("=== STAP 4: PRO-RATA KOSTEN BEREKENEN ===")
    for item in tijdelijke_registraties:
        werknemer_naam = item["werknemer_naam"]
        naam_klein = werknemer_naam.lower()
        aantal_uren = item["aantal_uren"]
        bon_date = item["bon_date"]
        opbrengst = item["opbrengst"]

        if "sjon" in naam_klein:
            # Pro-Rata verdeling van € 240,- vaste dagkosten (8u x €30)
            totale_uren_sjon_vandaag = sjon_dag_uren.get(bon_date, 0.0)
            if totale_uren_sjon_vandaag > 0:
                kosten = round((aantal_uren / totale_uren_sjon_vandaag) * 240.00, 2)
            else:
                kosten = 0.0
        elif "ramazan" in naam_klein:
            kosten = 60.00  # Vaste kosten per beurt
        elif "rik" in naam_klein:
            kosten = round(aantal_uren * 40.00, 2)  # € 40 / uur
        else:
            kosten = round(aantal_uren * 30.00, 2)  # Standaard uurtarief

        marge = round(opbrengst - kosten, 2)

        rij = [
            item["bon_id"], item["bon_number"], item["bon_date"], werknemer_naam,
            aantal_uren, item["opmerking"], item["status"], item["bon_title"],
            item["onderhoud_waarde"], opbrengst, kosten, marge
        ]

        sleutel = f"{item['bon_id']}_{werknemer_naam}"
        bestaande_rijen_dict[sleutel] = rij

    # STAP 5: WEGSCHRIJVEN NAAR GOOGLE SHEETS
    definitieve_rijen = list(bestaande_rijen_dict.values())
    definitieve_rijen.sort(key=lambda x: str(x[2]))
    
    worksheet.clear()
    worksheet.append_rows([headers] + definitieve_rijen)
    print(f"Succes! Google Sheets geüpdatet met pro-rata dagkosten voor Sjon ({len(definitieve_rijen)} rijen bewaard).")

if __name__ == "__main__":
    main()
