import os
import requests
import gspread
import json
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

    print("Werkbonnen ophalen uit Robaws...")
    robaws_url = "https://app.robaws.com/api/v2/work-orders" 

    response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
    if response.status_code != 200:
        print(f"Fout bij Robaws API: {response.status_code}")
        return

    data = response.json()
    werkbonnen = data.get("data", data) if isinstance(data, dict) else data

    if not werkbonnen or not isinstance(werkbonnen, list):
        print("Geen werkbonnen gevonden.")
        return

    # --- DIAGNOSTIEK: DIT PRINT DE INDELING IN JOUW LOGBOEK ---
    print("\n--- DIAGNOSTIEK: EERSTE WERKBON STRUCTUUR ---")
    print(json.dumps(werkbonnen[0], indent=2))
    print("----------------------------------------------\n")
    # ---------------------------------------------------------

    bestaande_ids = worksheet.col_values(1)
    nieuwe_rijen = []

    for bon in werkbonnen:
        if not isinstance(bon, dict):
            continue
        bon_id = str(bon.get("id"))
        if bon_id in bestaande_ids:
            continue
            
        rij = [
            bon_id,
            bon.get("number", ""),
            bon.get("clientName", ""),
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
