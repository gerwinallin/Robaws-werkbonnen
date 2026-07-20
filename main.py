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
        print("Fout: Robaws inloggegevens of SHEET_ID ontbreeken.")
        return

    print("Verbinden met Google Sheets...")
    gc = gspread.service_account(filename=credentials_file)
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.worksheet(sheet_name)

    # Sheet leegmaken voor het nieuwe overzicht
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
    werkbonnen = data.get("data", data) if isinstance(data, dict) else data

    if not werkbonnen or not isinstance(werkbonnen, list):
        print("Geen werkbonnen gevonden.")
        return

    sjon_rijen = []

    for bon in werkbonnen:
        if not isinstance(bon, dict):
            continue
            
        # FILTER: Sla bonnen over die vóór 1 juli 2026 zijn aangemaakt
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        is_van_sjon = False
        totaal_uren_sjon = 0.0

        # 1. Check hoofdverantwoordelijke
        employee_info = bon.get("employee", {}) or bon.get("assignedTo", {})
        employee_name = ""
        if isinstance(employee_info, dict):
            employee_name = employee_info.get("name", "") or employee_info.get("firstName", "")
        elif isinstance(employee_info, str):
            employee_name = employee_info

        if "sjon" in employee_name.lower() or "koster" in employee_name.lower():
            is_van_sjon = True

        # 2. Check urenregistraties binnen de bon
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

        if is_van_sjon:
            status = bon.get("status", "")
            if bon.get("archived") or bon.get("isArchived"):
                status = f"{status} (Gearchiveerd)"

            rij = [
                str(bon.get("id")),
                bon.get("number", ""),
                bon_date,
                "Sjon Koster",
                totaal_uren_sjon,
                status,
                bon.get("description", "")
            ]
            sjon_rijen.append(rij)

    # Wegschrijven naar Google Sheets
    if sjon_rijen:
        worksheet.append_rows(sjon_rijen)
        print(f"Succes! {len(sjon_rijen)} werkbonnen van Sjon Koster vanaf 1 juli toegevoegd.")
    else:
        print("Geen werkbonnen of urenregistraties gevonden voor Sjon Koster vanaf 1 juli.")

if __name__ == "__main__":
    main()
