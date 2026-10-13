"""Google Sheet sync for Axis export batches.

Reads a tab with columns source_url, presets, status, output_links, error.
Rows already processing or done are skipped. A row is claimed by writing
status=processing before it is enqueued, so a second sync is idempotent.
"""

from __future__ import annotations

from typing import Any, Protocol

_SKIP_STATUSES = frozenset({"processing", "done"})
_COLUMNS = ("source_url", "presets", "status", "output_links", "error")


class SheetClient(Protocol):
    def read_table(self, sheet_id: str, tab: str) -> list[dict[str, Any]]: ...

    def write_row(
        self, sheet_id: str, tab: str, row_number: int, fields: dict[str, str]
    ) -> None: ...


def parse_preset_cell(cell: str) -> list[str]:
    return [part.strip() for part in str(cell).split(",") if part.strip()]


def sync_sheet(
    engine: Any,
    client: SheetClient,
    *,
    sheet_id: str,
    tab: str,
    public_base: str,
) -> dict[str, Any]:
    if not sheet_id or not tab:
        raise ValueError("gsheet_id and gsheet_tab are required")
    rows = client.read_table(sheet_id, tab)
    skipped = 0
    claimed: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        if status in _SKIP_STATUSES:
            skipped += 1
            continue
        source_url = str(row.get("source_url") or "").strip()
        presets = parse_preset_cell(str(row.get("presets") or ""))
        if not source_url or not presets:
            skipped += 1
            continue
        row_number = int(row["row_number"])
        client.write_row(
            sheet_id,
            tab,
            row_number,
            {"status": "processing", "error": ""},
        )
        claimed.append({"row_number": row_number, "source_url": source_url, "preset_ids": presets})
    if not claimed:
        return {"batch_id": None, "claimed": 0, "skipped": skipped, "rows": []}
    try:
        batch = engine.start_adapt_batch(
            [
                {"source_url": row["source_url"], "preset_ids": row["preset_ids"]}
                for row in claimed
            ]
        )
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        written = []
        for row in claimed:
            client.write_row(
                sheet_id,
                tab,
                int(row["row_number"]),
                {"status": "error", "error": message, "output_links": ""},
            )
            written.append(
                {"row_number": row["row_number"], "status": "error", "error": message}
            )
        return {"batch_id": None, "claimed": len(claimed), "skipped": skipped, "rows": written}
    batch_id = str(batch["batch_id"])
    status = engine.adapt_batch_status(batch_id)
    items = list(status.get("items") or [])
    written_rows: list[dict[str, Any]] = []
    base = public_base.rstrip("/")
    for row, item in zip(claimed, items, strict=False):
        if item.get("status") == "done":
            links = " ".join(
                f"{base}/assets/{asset_id}/file" for asset_id in item.get("output_asset_ids") or []
            )
            fields = {"status": "done", "output_links": links, "error": ""}
        else:
            fields = {
                "status": "error",
                "output_links": "",
                "error": str(item.get("error") or "adapt failed"),
            }
        client.write_row(sheet_id, tab, int(row["row_number"]), fields)
        written_rows.append(
            {
                "row_number": row["row_number"],
                "status": fields["status"],
                "error": fields["error"],
                "output_links": fields["output_links"],
            }
        )
    return {
        "batch_id": batch_id,
        "claimed": len(claimed),
        "skipped": skipped,
        "rows": written_rows,
    }


def sheet_columns() -> tuple[str, ...]:
    return _COLUMNS
