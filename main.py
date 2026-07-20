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

    # Sheet leegmaken voor het schone overzicht
    worksheet.clear()
    headers = ["Werkbon ID", "Nummer", "Datum", "Verantwoordelijke", "Uren", "Status", "Titel / Omschrijving"]
    worksheet.append_row(headers)

    print("Werkbonnen ophalen uit Robaws (alle pagina's)...")
    
    all_werkbonnen = []
    # We lopen door meerdere pagina's heen om alle bonnen op te halen
    for page in range(1, 11):
        robaws_url = f"https://app.robaws.com/api/v2/work-orders?includeArchived=true&page={page}&limit=100"
        response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
        
        if response.status_code != 200:
            if page == 1:
                print(f"Fout bij Robaws API: {response.status_code} - {response.text}")
                return
            break
            
        data = response.json()
        items = []
        if isinstance(data, dict):
            items = data.get("items", data.get("data", []))
        elif isinstance(data, list):
            items = data
            
        if not items:
            break
            
        all_werkbonnen.extend(items)
        if len(items) < 100:
            break

    print(f"Totaal {len(all_werkbonnen)} bonnen ingeladen. Nu filteren op 'Onderhoudsbeurt'...")

    geselecteerde_rijen = []

    for bon in all_werkbonnen:
        if not isinstance(bon, dict):
            continue
            
        # FILTER 1: Alleen werkbonnen vanaf 1 juli 2026
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        # Pak de titel of omschrijving van de bon
        bon_title = bon.get("title") or bon.get("description") or ""

        # FILTER 2: Het woord 'Onderhoudsbeurt' moet in de titel staan
        if "onderhoudsbeurt" in bon_title.lower():
            
            # Haal de naam van de verantwoordelijke (employee) dynamisch op
            verantwoordelijke = "Onbekend"
            verantwoordelijke_info = bon.get("employee") or bon.get("responsibleEmployee")
            if isinstance(verantwoordelijke_info, dict):
                first = verantwoordelijke_info.get("firstName", "")
                last = verantwoordelijke_info.get("lastName", "")
                full = verantwoordelijke_info.get("name", "")
                # Voeg naamdelen samen en haal dubbele spaties weg
                naam_totaal = f"{first} {last} {full}".strip()
                if naam_totaal:
                    verantwoordelijke = " ".join(naam_totaal.split())
            elif isinstance(verantwoordelijke_info, str):
                verantwoordelijke = verantwoordelijke_info

            # Uren flexibel uitlezen
            uren = bon.get("hours") or bon.get("totalHours") or 0.0
            if isinstance(uren, (dict, list)):
                uren = 0.0
            try:
                uren = float(uren)
            except (ValueError, TypeError):
                uren = 0.0

            # Status flexibel uitlezen
            status = bon.get("status", "")
            if isinstance(status, dict):
                status = status.get("name") or status.get("label") or str(status)
                
            if bon.get("archived") or bon.get("isArchived"):
                if "gearchiveerd" not in str(status).lower():
                    status = f"{status} (Gearchiveerd)"

            bon_number = bon.get("number") or bon.get("code") or ""

            rij = [
                str(bon.get("id", "")),
                bon_number,
                bon_date,
                verantwoordelijke,
                uren,
                status,
                bon_title
            ]
            geselecteerde_rijen.append(rij)

    # Alles wegschrijven naar Google Sheets
    if geselecteerde_rijen:
        # Sorteer netjes op datum
        geselecteerde_rijen.sort(key=lambda x: x[2])
        worksheet.append_rows(geselecteerde_rijen)
        print(f"Succes! {len(geselecteerde_rijen)} onderhoudsbeurten vanaf 1 juli toegevoegd.")
    else:
        print("Geen werkbonnen gevonden met 'Onderhoudsbeurt' in de titel vanaf 1 juli.")

if __name__ == "__main__":
    main()
