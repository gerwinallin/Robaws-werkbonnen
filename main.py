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

    # Sheet volledig schoonmaken voor de schone start
    worksheet.clear()
    headers = ["Werkbon ID", "Nummer", "Datum", "Werknemer", "Uren", "Opmerking Werknemer", "Status Werkbon", "Titel / Omschrijving"]
    worksheet.append_row(headers)

    print("Werkbonnen ophalen uit Robaws (inclusief archief)...")
    
    all_werkbonnen = []
    seen_ids = set()
    
    # We lopen handmatig door de pagina's met een schone parameter-set om 500-fouten te voorkomen
    for page in range(1, 40):
        robaws_url = f"https://app.robaws.com/api/v2/work-orders?includeArchived=true&page={page}&limit=100"
        response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
        
        if response.status_code != 200:
            print(f"Paginering gestopt op pagina {page} (Status: {response.status_code})")
            break
            
        data = response.json()
        items = data.get("items", data.get("data", [])) if isinstance(data, dict) else data
            
        if not items:
            break
            
        new_items_on_page = 0
        for item in items:
            if isinstance(item, dict):
                bon_id = item.get("id")
                if bon_id not in seen_ids:
                    all_werkbonnen.append(item)
                    seen_ids.add(bon_id)
                    new_items_on_page += 1
                    
        print(f"Pagina {page} verwerkt. {new_items_on_page} nieuwe bonnen gevonden. Totaal uniek: {len(all_werkbonnen)}")
        
        # Als een pagina geen enkele nieuwe bon bevat, zijn we klaar
        if new_items_on_page == 0:
            break

    print(f"\nFilteren op datum (vanaf 1 juli 2026) en 'Onderhoudsbeurt'...")

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
            
            # Controleer of de bon gearchiveerd is op basis van je nieuwe screenshot veld
            if bon.get("archivedAt") or bon.get("archived") or bon.get("isArchived"):
                if "gearchiveerd" not in str(status).lower():
                    status = f"{status} (Gearchiveerd)"

            # NU MET INCLUDE: We roepen de urenregistratie aan én vragen expliciet om de werknemergegevens
            time_entries_url = f"https://app.robaws.com/api/v2/work-orders/{bon_id}/time-entries?include=employee"
            te_response = requests.get(time_entries_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
            
            uren_lijst = []
            if te_response.status_code == 200:
                te_data = te_response.json()
                uren_lijst = te_data.get("items", te_data.get("data", te_data)) if isinstance(te_data, dict) else te_data

            if isinstance(uren_lijst, list) and uren_lijst:
                for reg in uren_lijst:
                    if not isinstance(reg, dict):
                        continue
                        
                    # 1. Werknemer naam ophalen (dit werkt nu perfect dankzij ?include=employee!)
                    werknemer_naam = "Onbekend"
                    emp_info = reg.get("employee")
                    if isinstance(emp_info, dict):
                        first = emp_info.get("firstName", "") or ""
                        last = emp_info.get("lastName", "") or ""
                        full = emp_info.get("name", "") or ""
                        werknemer_naam = f"{first} {last} {full}".strip()
                    
                    if not werknemer_naam or werknemer_naam == "Onbekend":
                        werknemer_naam = reg.get("employeeName") or "Onbekend"
                    
                    werknemer_naam = " ".join(werknemer_naam.split())

                    # 2. Uren uitlezen (exact conform 'hours' uit screenshot)
                    aantal_uren = reg.get("hours") or 0.0
                    try:
                        aantal_uren = float(aantal_uren)
                    except (ValueError, TypeError):
                        aantal_uren = 0.0

                    # 3. Opmerking uitlezen (exact conform 'remark' uit screenshot)
                    opmerking = reg.get("remark") or ""

                    rij = [bon_id, bon_number, bon_date, werknemer_naam, aantal_uren, opmerking, status, bon_title]
                    uren_rijen.append(rij)
            else:
                rij = [bon_id, bon_number, bon_date, "Geen uren geregistreerd", 0.0, "", status, bon_title]
                uren_rijen.append(rij)

    # Schrijf alles chronologisch weg naar Google Sheets
    if uren_rijen:
        uren_rijen.sort(key=lambda x: x[2])
        worksheet.append_rows(uren_rijen)
        print(f"Succes! {len(uren_rijen)} regels toegevoegd aan de sheet.")
    else:
        print("Geen onderhoudsbeurten gevonden vanaf 1 juli 2026.")

if __name__ == "__main__":
    main()
