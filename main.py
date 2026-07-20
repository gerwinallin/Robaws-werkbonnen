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
    headers = ["Werkbon ID", "Nummer", "Datum", "Medewerker", "Uren Sjon Koster", "Status", "Omschrijving"]
    worksheet.append_row(headers)

    print("Werkbonnen ophalen uit Robaws (inclusief archief)...")
    robaws_url = "https://app.robaws.com/api/v2/work-orders?includeArchived=true" 

    response = requests.get(robaws_url, auth=HTTPBasicAuth(robaws_key, robaws_secret))
    if response.status_code != 200:
        print(f"Fout bij Robaws API: {response.status_code} - {response.text}")
        return

    data = response.json()
    
    # Zoek flexibel naar de lijst (Robaws v2 gebruikt 'items')
    werkbonnen = []
    if isinstance(data, list):
        werkbonnen = data
    elif isinstance(data, dict):
        for sleutel in ["items", "data", "results", "content"]:
            if sleutel in data and isinstance(data[sleutel], list):
                werkbonnen = data[sleutel]
                break

    if not werkbonnen:
        print("Geen werkbonnen gevonden in de Robaws API response.")
        return

    sjon_rijen = []

    for bon in werkbonnen:
        if not isinstance(bon, dict):
            continue
            
        # FILTER: Alleen vanaf 1 juli 2026
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        is_van_sjon = False
        totaal_uren_sjon = 0.0

        # 1. Check de medewerkers die aan de bon gekoppeld zijn
        for key in ["employee", "assignedTo", "employees", "workers"]:
            val = bon.get(key)
            if isinstance(val, dict):
                name = val.get("name", "") or val.get("firstName", "")
                if "sjon" in name.lower() or "koster" in name.lower():
                    is_van_sjon = True
            elif isinstance(val, list):
                for emp in val:
                    if isinstance(emp, dict):
                        name = emp.get("name", "") or emp.get("firstName", "")
                        if "sjon" in name.lower() or "koster" in name.lower():
                            is_van_sjon = True

        # 2. Check de urenregistraties binnen de bon
        uren_lijst = bon.get("hourRegistrations", []) or bon.get("hours", []) or bon.get("timeRegistrations", [])
        if isinstance(uren_lijst, list):
            for registratie in uren_lijst:
                reg_employee = registratie.get("employee", {})
                reg_name = ""
                if isinstance(reg_employee, dict):
                    reg_name = reg_employee.get("name", "") or reg_employee.get("firstName", "")
                elif isinstance(reg_employee, str):
                    reg_name = reg_employee

                if "sjon" in reg_name.lower() or "koster" in reg_name.lower():
                    is_van_sjon = True
                    aantal_uren = registratie.get("hours") or registratie.get("duration") or registratie.get("quantity") or 0
                    try:
                        totaal_uren_sjon += float(aantal_uren)
                    except (ValueError, TypeError):
                        pass

        # Als Sjon uren heeft of gekoppeld is, en er zijn uren bekend op de bon
        if is_van_sjon:
            # Als er via de regels geen uren kwamen, pak dan de hoofdhon-uren
            if totaal_uren_sjon == 0.0:
                hoofd_uren = bon.get("hours") or bon.get("totalHours") or 0
                try:
                    totaal_uren_sjon = float(hoofd_uren)
                except (ValueError, TypeError):
                    pass

            status = bon.get("status", "")
            if isinstance(status, dict):
                status = status.get("name", "") or status.get("label", "")
                
            if bon.get("archived") or bon.get("isArchived"):
                status = f"{status} (Gearchiveerd)"

            # Pak nummer en titel (omschrijving) flexibel mee
            bon_number = bon.get("number") or bon.get("code") or ""
            bon_title = bon.get("title") or bon.get("description") or ""

            rij = [
                str(bon.get("id")),
                bon_number,
                bon_date,
                "Sjon Koster",
                totaal_uren_sjon,
                status,
                bon_title
            ]
            sjon_rijen.append(rij)

    # Wegschrijven naar Google Sheets
    if sjon_rijen:
        worksheet.append_rows(sjon_rijen)
        print(f"Succes! {len(sjon_rijen)} werkbonnen vanaf 1 juli toegevoegd.")
    else:
        print("Geen werkbonnen gevonden voor Sjon Koster vanaf 1 juli.")

if __name__ == "__main__":
    main()
