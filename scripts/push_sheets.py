"""Write the CSVs in out/ straight into the Google Sheets with a service account.

Replaces the sheets' IMPORTDATA formulas (which read the CSVs from the public repo) with values,
so the finished stats no longer have to be published on GitHub. Needs the GOOGLE_SA_JSON secret
(the same service-account key as the NBA repo); without it this does nothing and the old
IMPORTDATA set-up keeps working. Both sheets must be shared with the service account as Editor.
"""
import csv, json, os, sys

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
MEMBER_SKIP = {"Pick tracker"}
CHUNK = 1500   # rows per write, keeps each request well under the API size limit


def col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def push_book(gc, sid, skip=()):
    import gspread
    book = gc.open_by_key(sid)
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
            ws = book.worksheet(tab)
            if ws.col_count < width:
                ws.add_cols(width - ws.col_count)
            if ws.row_count < len(rows):
                ws.add_rows(len(rows) - ws.row_count)
            ws.batch_clear([f"A1:{col(max(width, ws.col_count))}{ws.row_count}"])   # values only; formats stay
            for i in range(0, len(rows), CHUNK):
                ws.update(rows[i:i + CHUNK], f"A{i + 1}", value_input_option="USER_ENTERED")
            print(f"{sid[:6]} {name} -> {tab}: {len(rows)} rows")
        except gspread.exceptions.WorksheetNotFound:
            print(f"{sid[:6]} {tab}: tab not found, skipped")
        except Exception as e:  # noqa: BLE001 - one tab failing must not stop the rest
            print(f"{sid[:6]} {name} -> {tab}: skipped ({type(e).__name__}: {str(e)[:200]})")
            failed += 1
    return failed


def main():
    key = os.environ.get("GOOGLE_SA_JSON")
    if not key:
        print("GOOGLE_SA_JSON not set; sheets keep using IMPORTDATA")
        return 0
    import gspread
    gc = gspread.service_account_from_dict(json.loads(key))
    failed = push_book(gc, PERSONAL) + push_book(gc, MEMBERS, MEMBER_SKIP)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
