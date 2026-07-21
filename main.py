import os
import requests
import gspread
from requests.auth import HTTPBasicAuth

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

    print("=== STAP 1: HUIDIGE HISTORIE IN GOOGLE SHEETS VEILIGSTELLEN ===")
    try:
        bestaande_data = worksheet.get_all_values()
    except Exception:
        bestaande_data = []

    headers = bestaande_data[0] if bestaande_data else ["Werkbon ID", "Nummer", "Datum", "Werknemer", "Uren", "Opmerking Werknemer", "Status Werkbon", "Titel / Omschrijving", "Onderhoud"]
    
    oude_rijen = []
    if len(bestaande_data) > 1:
        for rij in bestaande_data[1:]:
            if len(rij) >= 3:
                datum = rij[2]
                # We bewaren de bonnen van vóór 1 juli, zodat historische data nooit verdwijnt
                if datum < "2026-07-01":
                    oude_rijen.append(rij)
                    
    print(f"{len(oude_rijen)} oude rijen (van vóór 1 juli) succesvol veiliggesteld.")

    print("\n=== STAP 2: WERKBONNEN OPHALEN UIT ROBAWS (TOT 1 JULI) ===")
    all_found_work_orders = {}

    # We lopen chronologisch terug in de tijd totdat we 1 juli passeren
    for page in range(1, 50):
        params = {
            "includeArchived": "true",
            "page": page,
            "limit": 100,
            "sort": "-date" # Haalt de nieuwste bonnen als eerste op
        }
        resp = requests.get("https://app.robaws.com/api/v2/work-orders", auth=auth, params=params)
        
        if resp.status_code != 200:
            break
            
        data = resp.json()
        items = data.get("items", data.get("data", [])) if isinstance(data, dict) else data
        
        if not items:
            break
            
        new_count = 0
        oudste_datum = "9999-12-31"
        
        for item in items:
            if isinstance(item, dict) and "id" in item:
                bon_id = item["id"]
                if bon_id not in all_found_work_orders:
                    all_found_work_orders[bon_id] = item
                    new_count += 1
                    
                bon_date = item.get("date", "9999-12-31")
                if bon_date and bon_date < oudste_datum:
                    oudste_datum = bon_date
                    
        print(f"Pagina {page} ingeladen: {new_count} nieuwe bonnen (Oudste datum gevonden: {oudste_datum})")
        
        if new_count == 0:
            break
            
        # Zodra de oudste datum op de pagina vóór 1 juli is, hebben we de hele maand te pakken en stoppen we
        if oudste_datum != "9999-12-31" and oudste_datum < "2026-07-01":
            print("Datumgrens van 1 juli 2026 gepasseerd. Ophalen is compleet.")
            break

    # ID Scanner Fallback: extra check om verborgen gearchiveerde bonnen rond begin juli mee te pakken
    known_ids = [int(i) for i in all_found_work_orders.keys() if str(i).isdigit()]
    if known_ids:
        min_id = min(known_ids)
        max_id = max(known_ids)
        start_scan = max(1, min_id - 200) # Scan nog 200 ID's extra terug
        end_scan = max_id + 50
        print(f"\nExtra scan voor verborgen bonnen tussen ID {start_scan} en {end_scan}...")
        for test_id in range(start_scan, end_scan):
            if test_id not in all_found_work_orders:
                try:
                    r_single = requests.get(f"https://app.robaws.com/api/v2/work-orders/{test_id}", auth=auth)
                    if r_single.status_code == 200:
                        item_single = r_single.json()
                        if isinstance(item_single, dict) and "id" in item_single:
                            all_found_work_orders[item_single["id"]] = item_single
                except Exception:
                    pass

    print(f"\n=== TOTAAL {len(all_found_work_orders)} WERKBONNEN VERZAMELD ===")

    # STAP 3: Filteren op Onderhoudsbeurt en uren/extra velden ophalen
    target_work_orders = []
    for item_id, bon in all_found_work_orders.items():
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        bon_title = bon.get("title") or bon.get("description") or ""
        if "onderhoudsbeurt" in bon_title.lower():
            target_work_orders.append(bon)

    print(f"Starten met uren & extra velden ophalen van {len(target_work_orders)} relevante onderhoudsbeurten...")
    uren_rijen = []

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

        # Extra veld 'Onderhoud' ophalen
        extra_fields = bon.get("extraFields", {})
        onderhoud_waarde = ""
        for key, value in extra_fields.items():
            if key.lower() == "onderhoud":
                if isinstance(value, dict):
                    field_type = value.get("type", "")
                    if field_type == "BOOLEAN":
                        onderhoud_waarde = "Ja" if value.get("booleanValue") else "Nee"
                    else:
                        onderhoud_waarde = value.get("stringValue") or value.get("dateValue") or value.get("decimalValue") or value.get("integerValue") or ""
                else:
                    onderhoud_waarde = str(value)
                break

        # Uren ophalen
        time_entries = []
        try:
            r_te1 = requests.get(f"https://app.robaws.com/api/v2/work-orders/{bon_id}/time-entries?include=employee", auth=auth)
            if r_te1.status_code == 200:
                d1 = r_te1.json()
                items1 = d1.get("items", d1.get("data", d1)) if isinstance(d1, dict) else d1
                if isinstance(items1, list) and len(items1) > 0:
                    time_entries = items1
        except Exception:
            pass

        if not time_entries:
            try:
                r_detail = requests.get(f"https://app.robaws.com/api/v2/work-orders/{bon_id}?include=timeEntries,employee", auth=auth)
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
                if not isinstance(reg, dict):
                    continue
                
                werknemer_naam = "Onbekend"
                emp_info = reg.get("employee") or reg.get("worker")
                if isinstance(emp_info, dict):
                    werknemer_naam = f"{emp_info.get('firstName', '')} {emp_info.get('lastName', '')} {emp_info.get('name', '')}".strip()
                elif isinstance(emp_info, str):
                    werknemer_naam = emp_info

                if not werknemer_naam or werknemer_naam == "Onbekend":
                    werknemer_naam = reg.get("employeeName") or reg.get("employeeId") or "Onbekend"
                werknemer_naam = " ".join(werknemer_naam.split())

                aantal_uren = reg.get("hours") or reg.get("duration") or reg.get("quantity") or 0.0
                try:
                    aantal_uren = float(aantal_uren)
                except (ValueError, TypeError):
                    aantal_uren = 0.0

                opmerking = reg.get("remark") or reg.get("comment") or ""

                rij = [bon_id, bon_number, bon_date, werknemer_naam, aantal_uren, opmerking, status, bon_title, onderhoud_waarde]
                uren_rijen.append(rij)
        else:
            rij = [bon_id, bon_number, bon_date, "Geen uren geregistreerd", 0.0, "", status, bon_title, onderhoud_waarde]
            uren_rijen.append(rij)

    print("\n=== STAP 4: GOOGLE SHEETS UPDATEN ===")
    
    # We voegen de opgeslagen oude rijen en de verse nieuwe rijen samen
    alle_rijen_compleet = oude_rijen + uren_rijen
    
    # We sorteren het geheel strak op datum
    alle_rijen_compleet.sort(key=lambda x: x[2])

    worksheet.clear()
    worksheet.append_rows([headers] + alle_rijen_compleet)
    
    print(f"Succes! Dashboard is perfect geüpdatet met in totaal {len(alle_rijen_compleet)} rijen.")

if __name__ == "__main__":
    main()
