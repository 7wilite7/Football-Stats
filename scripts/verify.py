"""Independent fact-check: compare the sheet's data (FotMob) with ESPN.

1. League tables: ESPN standings vs tables rebuilt from our matches (played, W/D/L, goals, points).
2. Every match: score and team stats (corners, cards, shots, shots on target, fouls, saves, offsides).
3. Every player in every match: goals, assists, shots, shots on target, fouls, fouled, cards, saves.

Writes verify/REPORT.md (summary) and verify/differences.csv (every mismatch).
The two sources use different data suppliers, so small differences in judgement stats
(shots, fouls) are normal; goals, cards and scores should agree exactly.
"""
import csv, json, os, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LEAGUES
from fetch import get, sim, DATA, ROOT
import build as B

OUT = os.path.join(ROOT, "verify")
TEAM_MAP = [  # (label, FotMob team-stat title, ESPN boxscore stat name, exact?)
    ("Corners", "Corners", "wonCorners", False), ("Yellow cards", "Yellow cards", "yellowCards", True),
    ("Red cards", "Red cards", "redCards", True), ("Shots", "Total shots", "totalShots", False),
    ("Shots on target", "Shots on target", "shotsOnTarget", False), ("Fouls", "Fouls committed", "foulsCommitted", False),
    ("Keeper saves", "Keeper saves", "saves", False), ("Offsides", "Offsides", "offsides", False)]
PLAYER_MAP = [("Goals", "g", "totalGoals", True), ("Assists", "a", "goalAssists", False), ("Shots", "sh", "totalShots", False),
              ("Shots on target", "sot", "shotsOnTarget", False), ("Fouls", "fc", "foulsCommitted", False),
              ("Fouled", "fw", "foulsSuffered", False), ("Yellow cards", "yc", "yellowCards", True),
              ("Red cards", "rc", "redCards", True), ("Saves", "sv", "saves", False)]


def num(v):
    try: return float(str(v).replace("%", ""))
    except Exception: return None


def summary(slug, eid):
    return get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={eid}", as_json=True, delay=0.15)


def check_match(lg, m):
    diffs, stats = [], defaultdict(int)
    try:
        _check(lg, m, diffs, stats)
    except Exception as ex:
        stats["check errors"] += 1; print("error", m.get("id"), ex)
    return diffs, stats


def _check(lg, m, diffs, stats):
    e = (m.get("espn") or {}).get("espn_id")
    if not e:
        stats["no ESPN match"] += 1; return
    j = summary(lg["espn"], e)
    if not j:
        stats["ESPN fetch failed"] += 1; return
    stats["matches compared"] += 1
    label = f"{m['home']['name']} v {m['away']['name']} ({m['date']})"
    comp = (j.get("header") or {}).get("competitions", [{}])[0]
    side_of = {}
    for c in comp.get("competitors", []):
        side = 0 if c.get("homeAway") == "home" else 1
        side_of[str(c.get("id"))] = side
        mine = m["home"]["score"] if side == 0 else m["away"]["score"]
        theirs = num(c.get("score"))
        stats["Score checks"] += 1
        if theirs is None or mine != theirs:
            diffs.append([lg["name"], label, "team", m["home" if side == 0 else "away"]["name"], "Goals (score)", mine, theirs])
        else: stats["Score agree"] += 1
    # team stats
    for t in (j.get("boxscore") or {}).get("teams", []):
        side = side_of.get(str((t.get("team") or {}).get("id")))
        if side is None: continue
        es = {s.get("name"): num(s.get("displayValue")) for s in t.get("statistics", [])}
        for lab, fm, en, exact in TEAM_MAP:
            mine = B.ts(m, fm, side); theirs = es.get(en)
            if mine is None or theirs is None: continue
            stats[f"team {lab} checks"] += 1
            if mine == theirs: stats[f"team {lab} agree"] += 1
            elif abs(mine - theirs) <= (0 if exact else 1): stats[f"team {lab} within 1"] += 1
            if mine != theirs:
                diffs.append([lg["name"], label, "team", m["home" if side == 0 else "away"]["name"], lab, mine, theirs])
    # players
    rosters = j.get("rosters") or []
    for r in rosters:
        side = 0 if r.get("homeAway") == "home" else 1
        team_id = m["home" if side == 0 else "away"]["id"]
        ours = [p for p in m["players"] if p["team"] == team_id and p.get("min")]
        for ep in r.get("roster", []):
            st = {s.get("name"): num(s.get("value")) for s in ep.get("stats", [])}
            if not (st.get("appearances") or ep.get("starter") or st.get("subIns")): continue
            name = (ep.get("athlete") or {}).get("displayName", "")
            best = max(ours, key=lambda p: sim(p["name"], name), default=None)
            if not best or sim(best["name"], name) < 0.5:
                stats["players not matched by name"] += 1; continue
            stats["players compared"] += 1
            for lab, k, en, exact in PLAYER_MAP:
                theirs = st.get(en)
                if theirs is None: continue
                if k == "sv" and not best["gk"]: continue
                mine = best[k]
                stats[f"player {lab} checks"] += 1
                if mine == theirs: stats[f"player {lab} agree"] += 1
                elif abs(mine - theirs) <= (0 if exact else 1): stats[f"player {lab} within 1"] += 1
                if mine != theirs:
                    diffs.append([lg["name"], label, "player", f"{best['name']} ({best['teamName']})", lab, mine, theirs])


def standings(lg, matches, diffs, stats):
    j = get(f"https://site.api.espn.com/apis/v2/sports/soccer/{lg['espn']}/standings", as_json=True)
    entries = []
    for ch in (j or {}).get("children", []) or [j or {}]:
        entries += ((ch.get("standings") or {}).get("entries")) or []
    if not entries:
        stats["standings unavailable"] += 1; return
    tab = defaultdict(lambda: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "name": ""})
    for m in matches:
        hs, as_ = m["home"]["score"], m["away"]["score"]
        for t, me, op in ((m["home"], hs, as_), (m["away"], as_, hs)):
            r = tab[t["id"]]; r["name"] = t["name"]; r["P"] += 1; r["GF"] += me; r["GA"] += op
            r["W" if me > op else "D" if me == op else "L"] += 1
    for e in entries:
        name = (e.get("team") or {}).get("displayName", "")
        es = {s.get("name"): num(s.get("value")) for s in e.get("stats", [])}
        tid, r = max(tab.items(), key=lambda kv: sim(kv[1]["name"], name), default=(None, None))
        if not r or sim(r["name"], name) < 0.5: continue
        stats["table rows compared"] += 1
        pairs = [("Played", r["P"], es.get("gamesPlayed")), ("Won", r["W"], es.get("wins")), ("Drawn", r["D"], es.get("ties")),
                 ("Lost", r["L"], es.get("losses")), ("Goals for", r["GF"], es.get("pointsFor")),
                 ("Goals against", r["GA"], es.get("pointsAgainst")), ("Points", 3 * r["W"] + r["D"], es.get("points"))]
        bad = [(k, a, b) for k, a, b in pairs if b is not None and a != b]
        if bad:
            for k, a, b in bad: diffs.append([lg["name"], "League table", "table", r["name"], k, a, b])
        else:
            stats["table rows agree"] += 1


def main():
    os.makedirs(OUT, exist_ok=True)
    all_diffs, per_league = [], {}
    for lg in LEAGUES:
        matches = B.load_matches(lg["key"])
        diffs, stats = [], defaultdict(int)
        standings(lg, matches, diffs, stats)
        with ThreadPoolExecutor(6) as ex:
            for d, st in ex.map(lambda m: check_match(lg, m), matches):
                diffs += d
                for k, v in st.items(): stats[k] += v
        per_league[lg["name"]] = stats; all_diffs += diffs
        print(lg["name"], dict(stats), "differences:", len(diffs), flush=True)
    with open(os.path.join(OUT, "differences.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["League", "Match", "Level", "Team / player", "Stat", "Sheet (FotMob)", "ESPN"])
        w.writerows(sorted(all_diffs, key=lambda d: (d[0], d[2], d[4], d[1])))
    json.dump(per_league, open(os.path.join(OUT, "stats.json"), "w"), indent=1)
    # report
    L = ["# Fact-check: sheet data (FotMob) vs ESPN", ""]
    tot = defaultdict(int)
    for s in per_league.values():
        for k, v in s.items(): tot[k] += v
    def line(lab, pre):
        c, a, w1 = tot[f"{pre} {lab} checks"], tot[f"{pre} {lab} agree"], tot[f"{pre} {lab} within 1"]
        return f"| {lab} | {c} | {100 * a / c:.1f}% | {100 * (a + w1) / c:.1f}% |" if c else f"| {lab} | 0 | - | - |"
    L += [f"Matches compared: {tot['matches compared']} (no ESPN match found: {tot['no ESPN match']}, ESPN fetch failed: {tot['ESPN fetch failed']})",
          f"League table rows agreeing exactly: {tot['table rows agree']} of {tot['table rows compared']}",
          f"Scores agreeing: {tot['Score agree']} of {tot['Score checks']}",
          f"Player appearances compared: {tot['players compared']} (not matched by name: {tot['players not matched by name']})", "",
          "## Team stats", "| Stat | Checks | Exact match | Within 1 |", "|---|---|---|---|"]
    L += [line(lab, "team") for lab, *_ in TEAM_MAP]
    L += ["", "## Player stats", "| Stat | Checks | Exact match | Within 1 |", "|---|---|---|---|"]
    L += [line(lab, "player") for lab, *_ in PLAYER_MAP]
    L += ["", "## By league", "| League | Matches | Table rows agree | Scores agree | Differences listed |", "|---|---|---|---|---|"]
    for name, s in per_league.items():
        nd = sum(1 for d in all_diffs if d[0] == name)
        L.append(f"| {name} | {s['matches compared']} | {s['table rows agree']}/{s['table rows compared']} | {s['Score agree']}/{s['Score checks']} | {nd} |")
    open(os.path.join(OUT, "REPORT.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
