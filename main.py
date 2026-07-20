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
    
    # We lopen door de pagina's heen. Als een pagina geen nieuwe bonnen oplevert, stopt de loop direct.
    for page in range(1, 30):
        robaws_url = f"https://app.robaws.com/api/v2/work-orders?includeArchived=true&page={page}&limit=100"
        response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
        
        if response.status_code != 200:
            break
            
        data = response.json()
        items = data.get("items", data.get("data", [])) if isinstance(data, dict) else data
            
        if not items:
            break
            
        # Controleer of deze pagina nieuwe bonnen bevat om herhalingen te voorkomen
        new_items_found = False
        for item in items:
            if isinstance(item, dict):
                bon_id = item.get("id")
                if bon_id not in seen_ids:
                    all_werkbonnen.append(item)
                    seen_ids.add(bon_id)
                    new_items_found = True
                    
        # Als Robaws ons dezelfde pagina blijft sturen (geen nieuwe ID's gevonden), breken we de loop
        if not new_items_found:
            print(f"Paginering gestopt op pagina {page} (geen nieuwe unieke bonnen meer).")
            break

    print(f"Totaal {len(all_werkbonnen)} unieke bonnen ingeladen. Filteren op datum vanaf 1 juli 2026 en 'Onderhoudsbeurt'...")

    uren_rijen = []

    for bon in all_werkbonnen:
        if not isinstance(bon, dict):
            continue
            
        # FILTER 1: Alleen werkbonnen vanaf 1 juli 2026
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        # FILTER 2: Alleen titels met 'Onderhoudsbeurt'
        bon_title = bon.get("title") or bon.get("description") or ""
        if "onderhoudsbeurt" in bon_title.lower():
            bon_id = str(bon.get("id", ""))
            
            # Haal de diepe details van deze specifieke werkbon op om de timeEntries te kunnen lezen
            detail_url = f"https://app.robaws.com/api/v2/work-orders/{bon_id}"
            detail_response = requests.get(detail_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
            
            if detail_response.status_code == 200:
                bon_detail = detail_response.json()
            else:
                bon_detail = bon

            bon_number = bon_detail.get("number") or bon_detail.get("code") or ""
            bon_title_def = bon_detail.get("title") or bon_detail.get("description") or ""
            
            status = bon_detail.get("status", "")
            if isinstance(status, dict):
                status = status.get("name") or status.get("label") or str(status)
            if bon_detail.get("archived") or bon_detail.get("isArchived"):
                if "gearchiveerd" not in str(status).lower():
                    status = f"{status} (Gearchiveerd)"

            # Haal de urenregistraties (timeEntries) op uit de bon op basis van de documentatie
            uren_lijst = bon_detail.get("timeEntries") or bon_detail.get("hourRegistrations") or bon_detail.get("timeRegistrations") or []
            
            if isinstance(uren_lijst, list) and uren_lijst:
                for reg in uren_lijst:
                    if not isinstance(reg, dict):
                        continue
                        
                    # 1. Werknemer naam achterhalen
                    werknemer_naam = "Onbekend"
                    emp_info = reg.get("employee") or reg.get("worker") or reg.get("user")
                    if isinstance(emp_info, dict):
                        first = emp_info.get("firstName", "") or ""
                        last = emp_info.get("lastName", "") or ""
                        full = emp_info.get("name", "") or ""
                        werknemer_naam = f"{first} {last} {full}".strip()
                    elif isinstance(emp_info, str):
                        werknemer_naam = emp_info
                        
                    if not werknemer_naam or werknemer_naam == "Onbekend":
                        # Fallback op ID of naamvelden direct in de regel als het object niet is uitgeklapt
                        werknemer_naam = reg.get("employeeName") or reg.get("employeeId") or "Onbekend"
                    
                    werknemer_naam = " ".join(werknemer_naam.split())

                    # 2. Aantal uren uitlezen (exact conform 'hours' uit jouw documentatie)
                    aantal_uren = reg.get("hours") or reg.get("duration") or reg.get("quantity") or 0.0
                    try:
                        aantal_uren = float(aantal_uren)
                    except (ValueError, TypeError):
                        aantal_uren = 0.0

                    # 3. Opmerking van de werknemer uitlezen (exact conform 'remark' uit jouw documentatie)
                    opmerking = reg.get("remark") or reg.get("comment") or reg.get("description") or ""

                    rij = [
                        bon_id,
                        bon_number,
                        bon_date,
                        werknemer_naam,
                        aantal_uren,
                        opmerking,
                        status,
                        bon_title_def
                    ]
                    uren_rijen.append(rij)
            else:
                # Als er wel een bon is maar (nog) geen urenregels onder timeEntries staan
                rij = [
                    bon_id,
                    bon_number,
                    bon_date,
                    "Geen uren geregistreerd",
                    0.0,
                    "",
                    status,
                    bon_title_def
                ]
                uren_rijen.append(rij)

    # Schrijf de gefilterde urenregels weg naar Google Sheets
    if uren_rijen:
        # Sorteer de lijst netjes chronologisch op datum
        uren_rijen.sort(key=lambda x: x[2])
        worksheet.append_rows(uren_rijen)
        print(f"Succes! {len(uren_rijen)} urenregels uit de onderhoudsbeurten toegevoegd aan de sheet.")
    else:
        print("Geen onderhoudsbeurten gevonden vanaf 1 juli 2026.")

if __name__ == "__main__":
    main()
