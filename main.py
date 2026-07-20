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

    # Sheet volledig schoonmaken voor het nieuwe urenoverzicht
    worksheet.clear()
    headers = ["Werkbon ID", "Nummer", "Datum", "Werknemer", "Uren", "Opmerking Werknemer", "Status Werkbon", "Titel / Omschrijving"]
    worksheet.append_row(headers)

    print("Werkbonnen ophalen uit Robaws...")
    
    all_werkbonnen = []
    seen_ids = set()
    
    for page in range(1, 30):
        robaws_url = f"https://app.robaws.com/api/v2/work-orders?includeArchived=true&page={page}&limit=100"
        response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
        
        if response.status_code != 200:
            break
            
        data = response.json()
        items = data.get("items", data.get("data", [])) if isinstance(data, dict) else data
            
        if not items:
            break
            
        new_items_found = False
        for item in items:
            if isinstance(item, dict):
                bon_id = item.get("id")
                if bon_id not in seen_ids:
                    all_werkbonnen.append(item)
                    seen_ids.add(bon_id)
                    new_items_found = True
                    
        if not new_items_found:
            break

    print(f"Totaal {len(all_werkbonnen)} unieke bonnen ingeladen. Filteren en uren ophalen per bon...")

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

            # EXTRACTIE: Ophalen van de losse urenregels (time-entries) via de specifieke endpoint
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
                        
                    # 1. Werknemer naam achterhalen
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

                    # 2. Aantal uren uitlezen (exact conform 'hours' uit documentatie)
                    aantal_uren = reg.get("hours") or reg.get("duration") or 0.0
                    try:
                        aantal_uren = float(aantal_uren)
                    except (ValueError, TypeError):
                        aantal_uren = 0.0

                    # 3. Opmerking van de werknemer (exact conform 'remark' uit documentatie)
                    opmerking = reg.get("remark") or reg.get("comment") or ""

                    rij = [bon_id, bon_number, bon_date, werknemer_naam, aantal_uren, opmerking, status, bon_title]
                    uren_rijen.append(rij)
            else:
                # Als er in de time-entries endpoint (nog) geen uren staan
                rij = [bon_id, bon_number, bon_date, "Geen uren geregistreerd", 0.0, "", status, bon_title]
                uren_rijen.append(rij)

    # Schrijf alles weg naar Google Sheets
    if uren_rijen:
        uren_rijen.sort(key=lambda x: x[2])
        worksheet.append_rows(uren_rijen)
        print(f"Succes! {len(uren_rijen)} urenregels toegevoegd.")
    else:
        print("Geen onderhoudsbeurten gevonden vanaf 1 juli 2026.")

if __name__ == "__main__":
    main()
