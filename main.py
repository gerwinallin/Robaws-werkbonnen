import os
import requests
import gspread

def main():
    robaws_api_key = os.environ.get("ROBAWS_API_KEY")
    sheet_id = os.environ.get("SHEET_ID")
    sheet_name = os.environ.get("SHEET_NAME", "Blad1")  # Verander naar je tabbladnaam indien nodig
    credentials_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if not robaws_api_key or not sheet_id:
        print("Fout: ROBAWS_API_KEY of SHEET_ID ontbreekt.")
        return

    print("Verbinden met Google Sheets...")
    gc = gspread.service_account(filename=credentials_file)
    sh = gc.open_by_key(sheet_id)
    
    try:
        worksheet = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=sheet_name, rows="1000", cols="10")
        worksheet.append_row(["ID", "Nummer", "Klant", "Datum", "Status", "Omschrijving"])

    print("Werkbonnen ophalen uit Robaws...")
    robaws_url = "https://app.robaws.com/api/v2/work-orders" 
    headers = {
        "Authorization": f"Bearer {robaws_api_key}",
        "Accept": "application/json"
    }

    response = requests.get(robaws_url, headers=headers)
    if response.status_code != 200:
        print(f"Fout bij Robaws API: {response.status_code} - {response.text}")
        return

    data = response.json()
    werkbonnen = data.get("data", data) if isinstance(data, dict) else data

    if not werkbonnen:
        print("Geen werkbonnen gevonden.")
        return

    bestaande_ids = worksheet.col_values(1)
    nieuwe_rijen = []

    for bon in werkbonnen:
        bon_id = str(bon.get("id"))
        
        if bon_id in bestaande_ids:
            continue
            
        rij = [
            bon_id,
            bon.get("number", ""),
            bon.get("clientName", "") or bon.get("customer", {}).get("name", ""),
            bon.get("date", ""),
            bon.get("status", ""),
            bon.get("description", "")
        ]
        nieuwe_rijen.append(rij)

    if nieuwe_rijen:
        worksheet.append_rows(nieuwe_rijen)
        print(f"Succes! {len(nieuwe_rijen)} nieuwe werkbonnen toegevoegd.")
    else:
        print("Alles is al up-to-date.")

if __name__ == "__main__":
    main()
