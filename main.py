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

    # Sheet volledig leegmaken voor het nieuwe gedetailleerde urenoverzicht
    worksheet.clear()
    headers = ["Werkbon ID", "Nummer", "Datum", "Werknemer", "Uren", "Opmerking Werknemer", "Status Werkbon", "Titel / Omschrijving"]
    worksheet.append_row(headers)

    print("Werkbonnen ophalen uit Robaws (alle pagina's)...")
    
    all_werkbonnen = []
    for page in range(1, 50):
        robaws_url = f"https://app.robaws.com/api/v2/work-orders?includeArchived=true&page={page}&limit=100"
        response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
        
        if response.status_code != 200:
            if page == 1:
                print(f"Fout bij Robaws API: {response.status_code} - {response.text}")
                return
            break
            
        data = response.json()
        items = data.get("items", data.get("data", [])) if isinstance(data, dict) else data
            
        if not items:
            break
            
        all_werkbonnen.extend(items)
        print(f"Pagina {page} ingeladen ({len(items)} bonnen)...")

    print(f"Totaal {len(all_werkbonnen)} bonnen ingeladen. Filteren op datum en 'Onderhoudsbeurt'...")

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
            
            # Haal de diepe details van deze specifieke werkbon op om de urenregels te lezen
            detail_url = f"https://app.robaws.com/api/v2/work-orders/{bon_id}"
            detail_response = requests.get(detail_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
            
            if detail_response.status_code == 200:
                bon_detail = detail_response.json()
            else:
                bon_detail = bon

            # Metadata van de bon ophalen
            bon_number = bon_detail.get("number") or bon_detail.get("code") or ""
            bon_title_def = bon_detail.get("title") or bon_detail.get("description") or ""
            
            status = bon_detail.get("status", "")
            if isinstance(status, dict):
                status = status.get("name") or status.get("label") or str(status)
            if bon_detail.get("archived") or bon_detail.get("isArchived"):
                if "gearchiveerd" not in str(status).lower():
                    status = f"{status} (Gearchiveerd)"

            # Haal de lijst met geschreven uren op uit de bon
            uren_lijst = bon_detail.get("hourRegistrations", []) or bon_detail.get("hours", []) or bon_detail.get("timeRegistrations", [])
            
            if isinstance(uren_lijst, list) and uren_lijst:
                # Loop door elke losse urenregel heen (zoals de 3 regels van Sjon Koster)
                for reg in uren_lijst:
                    if not isinstance(reg, dict):
                        continue
                        
                    # 1. Werknemer van deze specifieke regel achterhalen
                    emp_info = reg.get("employee", {})
                    werknemer_naam = "Onbekend"
                    if isinstance(emp_info, dict):
                        first = emp_info.get("firstName", "")
                        last = emp_info.get("lastName", "")
                        full = emp_info.get("name", "")
                        werknemer_naam = f"{first} {last} {full}".strip() or "Onbekend"
                        werknemer_naam = " ".join(werknemer_naam.split())
                    elif isinstance(emp_info, str):
                        werknemer_naam = emp_info

                    # 2. Aantal uren van deze regel
                    aantal_uren = reg.get("hours") or reg.get("duration") or reg.get("quantity") or 0.0
                    try:
                        aantal_uren = float(aantal_uren)
                    except (ValueError, TypeError):
                        aantal_uren = 0.0

                    # 3. Wat heeft de werknemer ingevuld in de bon (Opmerkingen / Activiteit)
                    opmerking = reg.get("comment") or reg.get("description") or reg.get("remarks") or reg.get("activity", "") or ""

                    # Maak een rij voor deze specifieke tijdregistratie
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
                # Als de bon wel bestaat maar er zijn nog helemaal geen uren op geschreven
                rij = [
                    bon_id,
                    bon_number,
                    bon_date,
                    "Geen uren geschreven",
                    0.0,
                    "",
                    status,
                    bon_title_def
                ]
                uren_rijen.append(rij)

    # Schrijf alle regels weg naar Google Sheets
    if uren_rijen:
        # Sorteer netjes op datum van de bon
        uren_rijen.sort(key=lambda x: x[2])
        worksheet.append_rows(uren_rijen)
        print(f"Succes! {len(uren_rijen)} urenregels uit onderhoudsbeurten toegevoegd.")
    else:
        print("Geen onderhoudsbeurten gevonden vanaf 1 juli.")

if __name__ == "__main__":
    main()
