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
    
    try:
        worksheet = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=sheet_name, rows="1000", cols="10")
        worksheet.append_row(["ID", "Nummer", "Klant", "Datum", "Status", "Omschrijving"])

    print("Werkbonnen ophalen uit Robaws...")
    robaws_url = "https://app.robaws.com/api/v2/work-orders" 

    response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
    
    if response.status_code != 200:
        print(f"Fout bij Robaws API: {response.status_code} - {response.text}")
        return

    data = response.json()
    
    # Zoek flexibel naar de lijst met werkbonnen in de Robaws data
    werkbonnen = []
    if isinstance(data, list):
        werkbonnen = data
    elif isinstance(data, dict):
        for sleutel in ["data", "items", "results", "content"]:
            if sleutel in data and isinstance(data[sleutel], list):
                werkbonnen = data[sleutel]
                break
        else:
            # Als er geen lijst wordt gevonden, printen we de structuur voor hulp
            print("Fout: Kon geen lijst met werkbonnen vinden in de Robaws data.")
            print(f"Beschikbare velden in de reactie: {list(data.keys())}")
            print(f"Inhoud van de reactie (eerste 300 tekens): {str(data)[:300]}")
            return

    if not werkbonnen:
        print("Geen werkbonnen gevonden of de lijst is leeg.")
        return

    bestaande_ids = worksheet.col_values(1)
    nieuwe_rijen = []

    for bon in werkbonnen:
        # Extra controle of 'bon' wel echt een object/dictionary is
        if not isinstance(bon, dict):
            continue
            
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
