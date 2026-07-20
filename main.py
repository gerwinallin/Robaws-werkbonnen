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
        print("Fout: Robaws inloggegevens of SHEET_ID ontbreekt.")
        return

    print("Verbinden met Google Sheets...")
    gc = gspread.service_account(filename=credentials_file)
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.worksheet(sheet_name)

    # Sheet volledig schoonmaken voor het complete overzicht
    worksheet.clear()
    headers = ["Werkbon ID", "Nummer", "Datum", "Werknemer", "Uren", "Opmerking Werknemer", "Status Werkbon", "Titel / Omschrijving"]
    worksheet.append_row(headers)

    print("Werkbonnen ophalen uit Robaws (inclusief gearchiveerde bonnen via JSON:API)...")
    
    all_werkbonnen = []
    seen_ids = set()
    
    # We lopen door de pagina's heen met de juiste JSON:API parameters
    for page in range(1, 20):
        robaws_url = "https://app.robaws.com/api/v2/work-orders"
        
        # We sturen alle mogelijke varianten mee zodat Robaws de paginering en het archief MOET activeren
        params = {
            "includeArchived": "true",
            "archived": "true",
            "filter[archived]": "true",
            "page": page,
            "page[number]": page,
            "limit": 100,
            "page[size]": 100,
            "sort": "-date"  # Zorgt dat de nieuwste bonnen vanaf 1 juli direct bovenaan staan
        }
        
        response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret), params=params)
        
        if response.status_code != 200:
            print(f"Stop op pagina {page} wegens statuscode {response.status_code}")
            break
            
        data = response.json()
        items = data.get("items", data.get("data", [])) if isinstance(data, dict) else data
            
        if not items:
            print(f"Geen bonnen meer gevonden op pagina {page}.")
            break
            
        new_items_found = False
        for item in items:
            if isinstance(item, dict):
                bon_id = item.get("id")
                if bon_id not in seen_ids:
                    all_werkbonnen.append(item)
                    seen_ids.add(bon_id)
                    new_items_found = True
                    
        print(f"Pagina {page} succesvol verwerkt. Unieke bonnen tot nu toe: {len(all_werkbonnen)}")
        
        # Als er geen nieuwe bonnen op deze pagina stonden, zijn we aan het einde van de lijst
        if not new_items_found:
            break

    print(f"\nFilteren van {len(all_werkbonnen)} bonnen op datum vanaf 1 juli 2026 en 'Onderhoudsbeurt'...")

    uren_rijen = []

    for bon in all_werkbonnen:
        if not isinstance(bon, dict):
            continue
            
        # FILTER 1: Alleen vanaf 1 juli 2026
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        # FILTER 2: Alleen titels met 'Onderhoudsbeurt'
        bon_title = bon.get("title") or bon.get("description") or ""
        if "onderhoudsbeurt" in bon_title.lower():
            bon_id = str(bon.get("id", ""))
            bon_number = bon.get("number") or bon.get("code") or ""
            
            status = bon.get("status", "")
            if isinstance(status, dict):
                status = status.get("name") or status.get("label") or str(status)
            if bon.get("archived") or bon.get("isArchived"):
                if "gearchiveerd" not in str(status).lower():
                    status = f"{status} (Gearchiveerd)"

            # Diepe urenregistraties ophalen per gevonden onderhoudsbon
            time_entries_url = f"https://app.robaws.com/api/v2/work-orders/{bon_id}/time-entries"
            te_response = requests.get(time_entries_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
            
            uren_lijst = []
            if te_response.status_code == 200:
                te_data = te_response.json()
                uren_lijst = te_data.get("items", te_data.get("data", te_data)) if isinstance(te_data, dict) else te_data

            if isinstance(uren_lijst, list) and uren_lijst:
                for reg in uren_lijst:
                    if not isinstance(reg, dict):
                        continue
                        
                    # Werknemer naam
                    werknemer_naam = "Onbekend"
                    emp_info = reg.get("employee") or reg.get("worker")
                    if isinstance(emp_info, dict):
                        first = emp_info.get("firstName", "") or ""
                        last = emp_info.get("lastName", "") or ""
                        full = emp_info.get("name", "") or ""
                        werknemer_naam = f"{first} {last} {full}".strip()
                    elif isinstance(emp_info, str):
                        werknemer_naam = emp_info
                        
                    if not werknemer_naam or werknemer_naam == "Onbekend":
                        werknemer_naam = reg.get("employeeName") or reg.get("employeeId") or "Onbekend"
                    
                    werknemer_naam = " ".join(werknemer_naam.split())

                    # Aantal uren (conform 'hours')
                    aantal_uren = reg.get("hours") or reg.get("duration") or 0.0
                    try:
                        aantal_uren = float(aantal_uren)
                    except (ValueError, TypeError):
                        aantal_uren = 0.0

                    # Opmerking werknemer (conform 'remark')
                    opmerking = reg.get("remark") or reg.get("comment") or ""

                    rij = [bon_id, bon_number, bon_date, werknemer_naam, aantal_uren, opmerking, status, bon_title]
                    uren_rijen.append(rij)
            else:
                # Mocht er een bon zijn zonder geregistreerde urenregels
                rij = [bon_id, bon_number, bon_date, "Geen uren geregistreerd", 0.0, "", status, bon_title]
                uren_rijen.append(rij)

    # Schrijf alle regels chronologisch weg naar Google Sheets
    if uren_rijen:
        uren_rijen.sort(key=lambda x: x[2])
        worksheet.append_rows(uren_rijen)
        print(f"Succes! {len(uren_rijen)} urenregels uit actieve en gearchiveerde onderhoudsbeurten toegevoegd.")
    else:
        print("Geen onderhoudsbeurten gevonden vanaf 1 juli 2026.")

if __name__ == "__main__":
    main()
