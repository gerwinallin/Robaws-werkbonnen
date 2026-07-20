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

    # Sheet leegmaken voor het schone Sjon Koster overzicht
    worksheet.clear()
    headers = ["Werkbon ID", "Nummer", "Datum", "Verantwoordelijke", "Uren", "Status", "Titel / Omschrijving"]
    worksheet.append_row(headers)

    print("Werkbonnen ophalen uit Robaws (inclusief archief)...")
    robaws_url = "https://app.robaws.com/api/v2/work-orders?includeArchived=true" 

    response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
    if response.status_code != 200:
        print(f"Fout bij Robaws API: {response.status_code} - {response.text}")
        return

    data = response.json()
    
    # Veilig de lijst met werkbonnen uit de v2 API pakken
    werkbonnen = []
    if isinstance(data, dict):
        if "items" in data:
            werkbonnen = data["items"]
        elif "data" in data:
            werkbonnen = data["data"]
    elif isinstance(data, list):
        werkbonnen = data

    if not werkbonnen:
        print("Geen werkbonnen gevonden in de Robaws API.")
        return

    sjon_rijen = []

    for bon in werkbonnen:
        if not isinstance(bon, dict):
            continue
            
        # FILTER 1: Alleen werkbonnen vanaf 1 juli 2026
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        # FILTER 2: Kijken of Sjon Koster de 'Verantwoordelijke' (employee) is
        is_van_sjon = False
        verantwoordelijke_info = bon.get("employee")
        
        if isinstance(verantwoordelijke_info, dict):
            first = verantwoordelijke_info.get("firstName", "") or ""
            last = verantwoordelijke_info.get("lastName", "") or ""
            full = verantwoordelijke_info.get("name", "") or ""
            
            naam_totaal = f"{first} {last} {full}".lower()
            if "sjon" in naam_totaal or "koster" in naam_totaal:
                is_van_sjon = True

        # Als Sjon de verantwoordelijke is, voegen we de bon toe
        if is_van_sjon:
            # Uren ophalen uit de hoofdgegevens van de bon
            uren = bon.get("hours") or bon.get("totalHours") or 0.0
            try:
                uren = float(uren)
            except (ValueError, TypeError):
                uren = 0.0

            # Status netjes tekstueel maken
            status = bon.get("status", "")
            if isinstance(status, dict):
                status = status.get("name", "") or status.get("label", "")
                
            if bon.get("archived") or bon.get("isArchived"):
                status = f"{status} (Gearchiveerd)"

            # Nummer en Titel ophalen
            bon_number = bon.get("number") or bon.get("code") or ""
            bon_title = bon.get("title") or bon.get("description") or ""

            rij = [
                str(bon.get("id")),
                bon_number,
                bon_date,
                "Sjon Koster",
                uren,
                status,
                bon_title
            ]
            sjon_rijen.append(rij)

    # Alles wegschrijven naar Google Sheets
    if sjon_rijen:
        # Sorteer netjes op datum
        sjon_rijen.sort(key=lambda x: x[2])
        worksheet.append_rows(sjon_rijen)
        print(f"Succes! {len(sjon_rijen)} werkbonnen van verantwoordelijke Sjon Koster toegevoegd.")
    else:
        print("Geen werkbonnen gevonden waar Sjon Koster verantwoordelijk voor is vanaf 1 juli.")

if __name__ == "__main__":
    main()
