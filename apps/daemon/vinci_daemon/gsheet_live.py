"""Optional gspread client. Importing this module does not import Google libraries."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class SheetsConfigError(RuntimeError):
    """Sheet sync cannot run because credentials or libraries are missing."""


class GspreadSheetClient:
    def __init__(self, client: Any) -> None:
        self._client = client

    def read_table(self, sheet_id: str, tab: str) -> list[dict[str, Any]]:
        worksheet = self._client.open_by_key(sheet_id).worksheet(tab)
        values = worksheet.get_all_values()
        if not values:
            return []
        header = [str(cell).strip() for cell in values[0]]
        rows: list[dict[str, Any]] = []
        for offset, raw in enumerate(values[1:], start=2):
            record: dict[str, Any] = {"row_number": offset}
            for index, name in enumerate(header):
                if not name:
                    continue
                record[name] = raw[index] if index < len(raw) else ""
            rows.append(record)
        return rows

    def write_row(
        self, sheet_id: str, tab: str, row_number: int, fields: dict[str, str]
    ) -> None:
        worksheet = self._client.open_by_key(sheet_id).worksheet(tab)
        header = [str(cell).strip() for cell in worksheet.row_values(1)]
        for key, value in fields.items():
            if key not in header:
                continue
            worksheet.update_cell(row_number, header.index(key) + 1, value)


def build_live_sheet_client() -> GspreadSheetClient:
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not path:
        raise SheetsConfigError(
            "Google Sheet sync is not configured: set GOOGLE_APPLICATION_CREDENTIALS "
            "to a service-account JSON file, and share the sheet with that account."
        )
    if not Path(path).expanduser().is_file():
        raise SheetsConfigError(
            "GOOGLE_APPLICATION_CREDENTIALS does not point to a file: " + path
        )
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise SheetsConfigError(
            "Google Sheet sync needs the optional gsheet extra "
            "(pip install 'vinci-daemon[gsheet]', google-auth and gspread)."
        ) from exc
    creds = Credentials.from_service_account_file(
        str(Path(path).expanduser()),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return GspreadSheetClient(gspread.authorize(creds))
