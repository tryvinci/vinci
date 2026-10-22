# Google Sheets batch driver

`vinci sheets sync` reads a Google Sheet and runs the same batch path as `POST /integrations/gsheet/sync`.

1. Install the optional extra (the daemon boots without it):

```bash
pip install 'vinci-daemon[gsheet]'
```

2. Create a service account, download its JSON key, and point `GOOGLE_APPLICATION_CREDENTIALS` at that file.

3. Share the spreadsheet with the service-account email (Viewer is not enough — the sync writes status back).

4. Put this header row on the tab you want to sync:

```text
source_url	presets	status	output_links	error
```

`presets` is a comma-separated list of preset ids (`amazon_828x300,inuxu_728x90`). Leave `status` blank for rows that should run. Rows already `processing` or `done` are skipped. The sync writes `processing` before enqueue, then `done` plus asset file URLs, or `error` plus the message.

5. Save the sheet id and tab name:

```bash
curl -X PATCH http://127.0.0.1:4310/settings \
  -H 'content-type: application/json' \
  -d '{"gsheet_id":"SPREADSHEET_ID","gsheet_tab":"Sheet1"}'
./scripts/vinci sheets sync
```
