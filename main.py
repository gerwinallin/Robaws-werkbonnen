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
        print("Fout: Inloggegevens ontbreken.")
        return

    auth = HTTPBasicAuth(robaws_key, robaws_secret)

    print("=== STAP 1: WERKBONNEN VERZAMELEN UIT ROBAWS ===")
    all_found_work_orders = {}

    def process_items(items):
        added = 0
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and "id" in item:
                    item_id = item["id"]
                    if item_id not in all_found_work_orders:
                        all_found_work_orders[item_id] = item
                        added += 1
        return added

    # 1. Basis-oproep (bewezen stabiel)
    try:
        r_base = requests.get("https://app.robaws.com/api/v2/work-orders?includeArchived=true", auth=auth)
        if r_base.status_code == 200:
            d_base = r_base.json()
            items_base = d_base.get("items", d_base.get("data", [])) if isinstance(d_base, dict) else d_base
            n_base = process_items(items_base)
            print(f"Basispagina ingeladen: {len(items_base)} bonnen gevonden.")
        else:
            print(f"Let op: basispagina gaf statuscode {r_base.status_code}")
    except Exception as e:
        print(f"Fout bij basis-oproep: {e}")

    # 2. Veilige zoek- en pagineringsvarianten
    pagination_tests = [
        {"page": 0, "size": 100},
        {"page": 1, "size": 100},
        {"page": 2, "size": 100},
        {"offset": 20, "limit": 100},
        {"offset": 100, "limit": 100},
        {"q": "Onderhoudsbeurt"},
        {"search": "Onderhoudsbeurt"}
    ]

    for params in pagination_tests:
        p_params = {"includeArchived": "true"}
        p_params.update(params)
        try:
            resp = requests.get("https://app.robaws.com/api/v2/work-orders", auth=auth, params=p_params)
            if resp.status_code == 200:
                d = resp.json()
                its = d.get("items", d.get("data", [])) if isinstance(d, dict) else d
                n_added = process_items(its)
                if n_added > 0:
                    print(f"Test met {params}: {n_added} nieuwe unieke bonnen toegevoegd!")
        except Exception:
            pass

    # 3. ID-Range Scanner (garandeert dat alle (gearchiveerde) bonnen worden gevonden)
    if len(all_found_work_orders) > 0:
        known_ids = [int(i) for i in all_found_work_orders.keys() if str(i).isdigit()]
        if known_ids:
            min_id = min(known_ids)
            max_id = max(known_ids)
            start_scan = max(1, min_id - 100)
            end_scan = max_id + 100
            print(f"\nScan range gestart rond bekende ID's ({start_scan} t/m {end_scan})...")
            scan_count = 0
            for test_id in range(start_scan, end_scan):
                if test_id not in all_found_work_orders:
                    try:
                        r_single = requests.get(f"https://app.robaws.com/api/v2/work-orders/{test_id}", auth=auth)
                        if r_single.status_code == 200:
                            item_single = r_single.json()
                            if isinstance(item_single, dict) and "id" in item_single:
                                all_found_work_orders[item_single["id"]] = item_single
                                scan_count += 1
                    except Exception:
                        pass
            print(f"ID-scanner heeft {scan_count} extra werkbonnen opgehaald!")

    print(f"\n=== TOTAAL {len(all_found_work_orders)} WERKBONNEN VERZAMELD ===")

    # VEILIGHEIDSVENTIEL 1:
    if len(all_found_work_orders) == 0:
        print("WAARSCHUWING: 0 werkbonnen opgehaald uit Robaws. Google Sheets wordt NIET gewist!")
        return

    # STAP 2: Filteren op datum (vanaf 1 juli 2026) en titel
    target_work_orders = []
    for item_id, bon in all_found_work_orders.items():
        bon_date = bon.get("date", "")
        if not bon_date or bon_date < "2026-07-01":
            continue

        bon_title = bon.get("title") or bon.get("description") or ""
        if "onderhoudsbeurt" in bon_title.lower():
            target_work_orders.append(bon)

    print(f"Aantal relevante onderhoudsbeurten vanaf 1 juli 2026: {len(target_work_orders)}")

    # VEILIGHEIDSVENTIEL 2:
    if len(target_work_orders) == 0:
        print("WAARSCHUWING: Geen relevante onderhoudsbeurten gevonden. Google Sheets wordt NIET gewist!")
        return

    # STAP 3: Uren & Extra veld 'Onderhoud' ophalen
    print("\n=== STAP 3: UREN, WERKNEMERS EN EXTRA VELDEN OPRAPEN ===")
    uren_rijen = []

    for bon in target_work_orders:
        bon_id = str(bon.get("id"))
        bon_number = bon.get("number") or bon.get("code") or ""
        bon_date = bon.get("date", "")
        bon_title = bon.get("title") or bon.get("description") or ""

        status = bon.get("status", "")
        if isinstance(status, dict):
            status = status.get("name") or status.get("label") or str(status)
        if bon.get("archivedAt") or bon.get("archived") or bon.get("isArchived"):
            if "gearchiveerd" not in str(status).lower():
                status = f"{status} (Gearchiveerd)"

        # Extra veld 'Onderhoud' ophalen
        extra_fields = bon.get("extraFields", {})
        onderhoud_waarde = ""
        for key, value in extra_fields.items():
            if key.lower() == "onderhoud":
                if isinstance(value, dict):
                    field_type = value.get("type", "")
                    if field_type == "BOOLEAN":
                        onderhoud_waarde = "Ja" if value.get("booleanValue") else "Nee"
                    else:
                        onderhoud_waarde = value.get("stringValue") or value.get("dateValue") or value.get("decimalValue") or value.get("integerValue") or ""
                else:
                    onderhoud_waarde = str(value)
                break

        # Uren ophalen
        time_entries = []
        try:
            r_te1 = requests.get(f"https://app.robaws.com/api/v2/work-orders/{bon_id}/time-entries?include=employee", auth=auth)
            if r_te1.status_code == 200:
                d1 = r_te1.json()
                items1 = d1.get("items", d1.get("data", d1)) if isinstance(d1, dict) else d1
                if isinstance(items1, list) and len(items1) > 0:
                    time_entries = items1
        except Exception:
            pass

        if not time_entries:
            try:
                r_detail = requests.get(f"https://app.robaws.com/api/v2/work-orders/{bon_id}?include=timeEntries,employee", auth=auth)
                if r_detail.status_code == 200:
                    d_detail = r_detail.json()
                    for k in ["timeEntries", "hourRegistrations", "timeRegistrations", "activities"]:
                        if k in d_detail and isinstance(d_detail[k], list) and len(d_detail[k]) > 0:
                            time_entries = d_detail[k]
                            break
            except Exception:
                pass

        if isinstance(time_entries, list) and len(time_entries) > 0:
            for reg in time_entries:
                if not isinstance(reg, dict):
                    continue
                
                werknemer_naam = "Onbekend"
                emp_info = reg.get("employee") or reg.get("worker")
                if isinstance(emp_info, dict):
                    werknemer_naam = f"{emp_info.get('firstName', '')} {emp_info.get('lastName', '')} {emp_info.get('name', '')}".strip()
                elif isinstance(emp_info, str):
                    werknemer_naam = emp_info

                if not werknemer_naam or werknemer_naam == "Onbekend":
                    werknemer_naam = reg.get("employeeName") or reg.get("employeeId") or "Onbekend"
                werknemer_naam = " ".join(werknemer_naam.split())

                aantal_uren = reg.get("hours") or reg.get("duration") or reg.get("quantity") or 0.0
                try:
                    aantal_uren = float(aantal_uren)
                except (ValueError, TypeError):
                    aantal_uren = 0.0

                opmerking = reg.get("remark") or reg.get("comment") or ""

                rij = [bon_id, bon_number, bon_date, werknemer_naam, aantal_uren, opmerking, status, bon_title, onderhoud_waarde]
                uren_rijen.append(rij)
        else:
            rij = [bon_id, bon_number, bon_date, "Geen uren geregistreerd", 0.0, "", status, bon_title, onderhoud_waarde]
            uren_rijen.append(rij)

    # STAP 4: WEGSCHRIJVEN NAAR GOOGLE SHEETS
    print("\n=== STAP 4: WEGSCHRIJVEN NAAR GOOGLE SHEETS ===")
    gc = gspread.service_account(filename=credentials_file)
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.worksheet(sheet_name)

    headers = ["Werkbon ID", "Nummer", "Datum", "Werknemer", "Uren", "Opmerking Werknemer", "Status Werkbon", "Titel / Omschrijving", "Onderhoud"]
    
    uren_rijen.sort(key=lambda x: x[2])
    
    worksheet.clear()
    worksheet.append_rows([headers] + uren_rijen)
    print(f"Succes! {len(uren_rijen)} urenregels uit {len(target_work_orders)} onderhoudsbeurten succesvol in Google Sheets geplaatst.")

if __name__ == "__main__":
    main()
