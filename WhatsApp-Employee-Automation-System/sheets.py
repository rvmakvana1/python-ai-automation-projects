import os
import json
import traceback
import gspread
from datetime import datetime
from config import GOOGLE_SHEET_ID

# Absolute path to the service account JSON key file (same folder as this file)
_SERVICE_ACCOUNT_PATH = os.path.join(os.path.dirname(__file__), "service_account.json")

# Expected column order in the Google Sheet (must match sheet header row)
_COLUMNS = [
    "Date",
    "Employee Name",
    "Phone",
    "Brands Found",
    "Brands Platform",
    "Brands Messaged",
    "Brand Replies",
    "Influencers Found",
    "Influencer Platform",
    "Influencers Messaged",
    "Influencer Replies",
    "Screenshot Link",
    "Timestamp",
]


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def _print_service_account_info() -> str:
    """Read service_account.json and print client_email + project_id.

    Returns the client_email so callers can reference it in error messages.
    """
    if not os.path.exists(_SERVICE_ACCOUNT_PATH):
        print(f"[Sheets] ❌ service_account.json NOT FOUND at {_SERVICE_ACCOUNT_PATH}")
        return ""

    try:
        with open(_SERVICE_ACCOUNT_PATH, "r", encoding="utf-8") as f:
            sa = json.load(f)

        client_email = sa.get("client_email", "(missing)")
        project_id   = sa.get("project_id",   "(missing)")
        sa_type      = sa.get("type",         "(missing)")

        print("=" * 60)
        print("[Sheets] Service Account Info:")
        print(f"          type:         {sa_type}")
        print(f"          project_id:   {project_id}")
        print(f"          client_email: {client_email}")
        print("=" * 60)
        return client_email
    except Exception as e:
        print(f"[Sheets] ❌ Could not read service_account.json: {e}")
        traceback.print_exc()
        return ""


def _list_all_accessible_sheets(gc) -> None:
    """List every spreadsheet this service account has access to.

    This helps diagnose whether the sheet was actually shared with the
    service account email — if the list is empty, nothing is shared.
    """
    try:
        print("[Sheets] Listing all spreadsheets accessible to the service account...")
        all_sheets = gc.openall()

        if not all_sheets:
            print("[Sheets] ⚠️  No spreadsheets accessible!")
            print("           → The sheet has NOT been shared with the service account email.")
            print("           → Fix: Open your sheet → Share → add the client_email as Editor.")
            return

        print(f"[Sheets] ✅ {len(all_sheets)} spreadsheet(s) accessible:")
        for s in all_sheets:
            print(f"           • title='{s.title}'  id='{s.id}'")
    except Exception as e:
        print(f"[Sheets] ❌ Could not list spreadsheets: {e}")
        print("           → This often means the Google Drive API is NOT enabled.")
        print("           → Enable it at: https://console.cloud.google.com/apis/library/drive.googleapis.com")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_sheet():
    """Authenticate, run diagnostics, and return the first worksheet of the target sheet."""
    sheet_id = (GOOGLE_SHEET_ID or "").strip()

    print("\n" + "=" * 60)
    print(f"[Sheets] GOOGLE_SHEET_ID (from .env): '{sheet_id}'")
    print(f"[Sheets] Length of sheet_id: {len(sheet_id)} chars")
    print("=" * 60)

    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID is empty — check your .env file")

    client_email = _print_service_account_info()

    # Authenticate via gspread's built-in service_account helper
    gc = gspread.service_account(filename=_SERVICE_ACCOUNT_PATH)
    print("[Sheets] gspread.service_account() succeeded — client authorized")

    # Diagnostic: list everything the service account can see
    _list_all_accessible_sheets(gc)

    # Now try to open the target sheet by ID
    print(f"[Sheets] Attempting gc.open_by_key('{sheet_id}')...")
    try:
        spreadsheet = gc.open_by_key(sheet_id)
        print(f"[Sheets] ✅ Connected to spreadsheet: '{spreadsheet.title}'")
        return spreadsheet.sheet1
    except gspread.exceptions.SpreadsheetNotFound:
        print("[Sheets] ❌ 404 — Spreadsheet not found or not shared.")
        print(f"           → Share the sheet with: {client_email}")
        raise
    except gspread.exceptions.APIError as e:
        print(f"[Sheets] ❌ Google API error: {e}")
        _explain_api_error(e)
        raise


def _explain_api_error(e: gspread.exceptions.APIError) -> None:
    """Parse an APIError response and print actionable hints."""
    try:
        err_json = e.response.json() if hasattr(e, "response") else {}
        status = err_json.get("error", {}).get("status", "")
        msg    = err_json.get("error", {}).get("message", "")
        code   = err_json.get("error", {}).get("code", "")

        print(f"           status:  {status}")
        print(f"           code:    {code}")
        print(f"           message: {msg}")

        if code == 403 and "has not been used" in msg.lower():
            print("           → Google Sheets API or Drive API is NOT enabled.")
            print("           → Enable Sheets:  https://console.cloud.google.com/apis/library/sheets.googleapis.com")
            print("           → Enable Drive:   https://console.cloud.google.com/apis/library/drive.googleapis.com")
        elif code == 404:
            print("           → Double-check the sheet ID and that it is shared with the service account.")
        elif code == 403:
            print("           → Permission denied. Share the sheet with the service account as Editor.")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_report(employee_name: str, phone: str, parsed_data: dict, screenshot_media_id: str) -> bool:
    """Append a new row with the employee's daily report to Google Sheets."""
    try:
        sheet = _get_sheet()

        now = datetime.now()
        row = [
            now.strftime("%Y-%m-%d"),
            employee_name,
            phone,
            parsed_data.get("brands_found",          ""),
            parsed_data.get("brands_platform",       ""),
            parsed_data.get("brands_messaged",       ""),
            parsed_data.get("brands_replied",        ""),
            parsed_data.get("influencers_found",     ""),
            parsed_data.get("influencers_platform",  ""),
            parsed_data.get("influencers_messaged",  ""),
            parsed_data.get("influencers_replied",   ""),
            screenshot_media_id,
            now.strftime("%Y-%m-%d %H:%M:%S"),
        ]

        sheet.append_row(row, value_input_option="USER_ENTERED")
        print(f"[Sheets] ✅ Report saved for {employee_name} ({phone})")
        return True

    except Exception as e:
        print(f"[Sheets] ❌ save_report failed for {phone}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def ensure_header_row() -> None:
    """Write the header row to the sheet if the first row is empty.

    Runs the full diagnostic chain; prints a complete traceback if anything fails.
    Safe to call every startup.
    """
    try:
        sheet = _get_sheet()
        first_row = sheet.row_values(1)
        if not first_row:
            sheet.append_row(_COLUMNS)
            print("[Sheets] ✅ Header row created")
        else:
            print("[Sheets] ✅ Header row already exists, skipping")
    except Exception as e:
        print("=" * 60)
        print(f"[Sheets] ❌ ensure_header_row FAILED: {type(e).__name__}: {e}")
        print("=" * 60)
        traceback.print_exc()
        print("=" * 60)
