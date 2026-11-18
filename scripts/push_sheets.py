"""Write the CSVs in out/ straight into the Google Sheets with a service account.

Replaces the sheets' IMPORTDATA formulas (which read the CSVs from the public repo) with values,
so the finished stats no longer have to be published on GitHub. Needs the GOOGLE_SA_JSON secret
(the same service-account key as the NBA repo); without it this does nothing and the old
IMPORTDATA set-up keeps working. Both sheets must be shared with the service account as Editor.
"""
import csv, json, os, sys, time

sys.stdout.reconfigure(line_buffering=True)   # show progress in the Actions log as it happens

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out")

PERSONAL = "1AccN-NUt37jX_EHNX33FEMazTjEpauobtUzee6bkrLE"   # Football Hit Rates 2026-27 (personal)
MEMBERS = "1c7ATg_cMYKig-SKGLTPwstCPEozUivtRrniORkoh8Pk"    # HitRateHub Football (Members)

TABS = {  # tab name -> csv in out/
    "Phone": "MOBILE.csv", "Today": "TODAY.csv", "Pick tracker": "TRACKER.csv", "All picks": "ALL_PICKS.csv",
    "Teams": "TEAMS.csv", "Premier League": "EPL_players.csv", "La Liga": "LALIGA_players.csv",
    "Serie A": "SERIEA_players.csv", "Bundesliga": "BUNDESLIGA_players.csv", "Ligue 1": "LIGUE1_players.csv",
    "Championship": "CHAMPIONSHIP_players.csv", "MLS": "MLS_players.csv", "Champions League": "UCL_players.csv",
    "Europa League": "UEL_players.csv", "Eredivisie top 5": "EREDIVISIE_players.csv",
    "Saudi top 5": "SAUDI_players.csv", "Portugal big 3": "PORTUGAL_players.csv", "Scotland": "SCOTLAND_players.csv",
    "Turkey": "TURKEY_players.csv", "Internationals": "INTL_players.csv", "_all": "ALL_players.csv",
}
# Members' copy is kept light enough for a phone/iPad: no 5,000-row _all tab (it only fed Player search/Lookup,
# which are not in that copy) and every tab cut to the size of its data each run.
MEMBER_SKIP = {"Pick tracker", "_all"}
SPARE_ROWS = 5
CHUNK = 1500   # rows per write, keeps each request well under the API size limit


def col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


RETRY_CODES = {429, 500, 502, 503, 504}
WAITS = (10, 30, 60, 120)      # seconds between attempts when Google is busy (rate limit / 500 / 503)


def retry(fn, *a, **kw):
    """Call a Sheets API function, retrying when Google answers busy/unavailable instead of giving up."""
    import gspread
    for i, wait in enumerate(WAITS + (None,)):
        try:
            return fn(*a, **kw)
        except gspread.exceptions.APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code not in RETRY_CODES or wait is None:
                raise
            print(f"   Google said {code}; retry {i + 1} in {wait}s")
            time.sleep(wait)


def push_book(gc, sid, skip=(), trim=False):
    import gspread
    book = retry(gc.open_by_key, sid)
    failed = 0
    for tab, name in TABS.items():
        if tab in skip:
            continue
        try:
            rows = list(csv.reader(open(os.path.join(OUT, name), encoding="utf-8")))
            if not rows:
                continue
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            ws = retry(book.worksheet, tab)
            if ws.col_count < width:
                retry(ws.add_cols, width - ws.col_count)
            if ws.row_count < len(rows):
                retry(ws.add_rows, len(rows) - ws.row_count)
            retry(ws.batch_clear, [f"A1:{col(max(width, ws.col_count))}{ws.row_count}"])   # values only; formats stay
            for i in range(0, len(rows), CHUNK):
                retry(ws.update, rows[i:i + CHUNK], f"A{i + 1}", value_input_option="USER_ENTERED")
            if trim:                                   # drop the empty rows/columns under and right of the data
                retry(ws.resize, rows=max(len(rows) + SPARE_ROWS, (ws.frozen_row_count or 0) + 1), cols=width)
            print(f"{sid[:6]} {name} -> {tab}: {len(rows)} rows")
        except gspread.exceptions.WorksheetNotFound:
            print(f"{sid[:6]} {tab}: tab not found, skipped")
        except Exception as e:  # noqa: BLE001 - one tab failing must not stop the rest
            print(f"{sid[:6]} {name} -> {tab}: skipped ({type(e).__name__}: {str(e)[:200]})")
            failed += 1
    try:                                               # Key tab: "Last update per league" table (was IMPORTDATA)
        rows = list(csv.reader(open(os.path.join(OUT, "INDEX.csv"), encoding="utf-8")))
        key_ws = retry(book.worksheet, "Key")
        retry(key_ws.batch_clear, ["A36:L90"])
        retry(key_ws.update, rows, "A36", value_input_option="USER_ENTERED")
        print(f"{sid[:6]} INDEX.csv -> Key!A36: {len(rows)} rows")
    except Exception as e:  # noqa: BLE001
        print(f"{sid[:6]} INDEX.csv -> Key: skipped ({type(e).__name__}: {str(e)[:200]})")
        failed += 1
    return failed


def main():
    key = os.environ.get("GOOGLE_SA_JSON")
    if not key:
        print("GOOGLE_SA_JSON not set; sheets keep using IMPORTDATA")
        return 0
    import gspread
    gc = gspread.service_account_from_dict(json.loads(key))
    # Members first: paying customers' copy must not wait behind the big private _all tab.
    failed = push_book(gc, MEMBERS, MEMBER_SKIP, trim=True) + push_book(gc, PERSONAL)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
