"""Post-update checks. Run after fetch + build; exits 1 (so the run fails and healthchecks.io gets a fail ping) on real problems.

Errors (fail the run):
  - a league wasn't updated in this run, or its fetch flagged a problem
  - an output CSV the sheet imports is missing, empty, or lost a column the sheet's formulas look up by name
  - a cached match file is broken (no teams/score/players) or a match id appears twice
  - the league files contain the same player twice
Warnings (printed, run still passes):
  - a fixture kicked off more than 2 days ago but is still not finished (postponed/abandoned, or the source is stuck)
Writes data/checks.json with the result so the history of every attempt stays in git.
"""
import csv, glob, json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LEAGUES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, OUT = os.path.join(ROOT, "data"), os.path.join(ROOT, "out")
NOW = dt.datetime.now(dt.timezone.utc)
# Columns the sheet's formulas find by header name (Lookup / Player search tabs)
NEEDED = {"ALL_players.csv": ["Player", "Team", "Status", "Next match", "Apps", "Starts", "Last 5 dates", "League", "Search name"]}
errors, warnings = [], []


def rows(fn):
    try:
        with open(os.path.join(OUT, fn), newline="") as f: return list(csv.reader(f))
    except FileNotFoundError:
        return None


def header(r):
    return next((x for x in r if x and x[0] in ("Player", "Team", "League", "Pick", "Market")), [])


def main(keys):
    keys = keys or [l["key"] for l in LEAGUES]
    status = json.load(open(os.path.join(DATA, "status.json")))
    for k in keys:
        s = status.get(k) or {}
        at = s.get("at")
        age = (NOW - dt.datetime.fromisoformat(at.replace("Z", "+00:00"))).total_seconds() / 3600 if at else 999
        if age > 6: errors.append(f"{k}: last updated {at or 'never'} ({age:.0f}h ago), not in this run")
        if s.get("problem"): errors.append(f"{k}: fetch kept yesterday's table/fixtures (source returned nothing)")

    files = ["INDEX.csv", "TODAY.csv", "MOBILE.csv", "ALL_PICKS.csv", "TRACKER.csv", "TEAMS.csv", "ALL_players.csv"]
    files += [f"{l['key']}_{t}.csv" for l in LEAGUES for t in ("players", "teams")]
    for fn in files:
        r = rows(fn)
        if r is None: errors.append(f"{fn}: missing"); continue
        if len(r) < 3: errors.append(f"{fn}: only {len(r)} rows")
        h = header(r)
        for c in NEEDED.get(fn, []):
            if c not in h: errors.append(f"{fn}: column '{c}' is gone (sheet formulas look it up by name)")

    seen_players = 0
    for l in LEAGUES:
        r = rows(f"{l['key']}_players.csv") or []
        h = header(r)
        if not h: continue
        body = r[r.index(h) + 1:]
        pairs = [(x[0], x[1]) for x in body if len(x) > 1 and x[0]]
        dups = {p for p in pairs if pairs.count(p) > 1}
        if dups: errors.append(f"{l['key']}_players.csv: duplicate rows {sorted(dups)[:5]}")
        seen_players += len(pairs)

        ids = set()
        for p in glob.glob(os.path.join(DATA, "matches", l["key"], "*.json")):
            try:
                m = json.load(open(p))
                assert m["home"]["name"] and m["away"]["name"]
                assert isinstance(m["home"]["score"], int) and isinstance(m["away"]["score"], int)
                assert m["players"]
            except Exception as e:
                errors.append(f"{l['key']}: broken match file {os.path.basename(p)} ({e!r})"); continue
            if m["id"] in ids: errors.append(f"{l['key']}: match {m['id']} stored twice")
            ids.add(m["id"])

        for f in json.load(open(os.path.join(DATA, "fixtures", f"{l['key']}.json"))) if os.path.exists(os.path.join(DATA, "fixtures", f"{l['key']}.json")) else []:
            if not f.get("utc"): continue
            ko = dt.datetime.fromisoformat(f["utc"].replace("Z", "+00:00"))
            if (NOW - ko).days >= 2:
                warnings.append(f"{l['key']}: {f['home']['name']} v {f['away']['name']} ({f['utc'][:10]}) still not finished - postponed/abandoned?")

    result = {"at": NOW.isoformat(timespec="minutes").replace("+00:00", "Z"), "ok": not errors,
              "players_listed": seen_players, "errors": errors, "warnings": warnings}
    hist_p = os.path.join(DATA, "checks.json")
    hist = json.load(open(hist_p)) if os.path.exists(hist_p) else []
    hist = ([result] + hist)[:60]
    with open(hist_p, "w") as f: json.dump(hist, f, indent=1, ensure_ascii=False)
    for w in warnings: print("::warning::" + w)
    for e in errors: print("::error::" + e)
    print("checks", "OK" if not errors else f"FAILED ({len(errors)})", f"- {len(warnings)} warnings, {seen_players} player rows")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
