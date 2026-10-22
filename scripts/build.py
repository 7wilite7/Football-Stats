"""Turn cached matches into one CSV per league: team markets on top, player hit rates below."""
import csv, json, os, datetime as dt
from collections import defaultdict
from config import LEAGUES, MIN_AVG_MINUTES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, OUT = os.path.join(ROOT, "data"), os.path.join(ROOT, "out")


def blank_zeros(rows):
    """Show 0 / 0% as an empty cell so the sheet is easier to scan."""
    return [["" if isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0 else v for v in r] for r in rows]


def jload(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d


def load_matches(key):
    d = os.path.join(DATA, "matches", key)
    ms = [jload(os.path.join(d, f)) for f in os.listdir(d)] if os.path.isdir(d) else []
    return sorted([m for m in ms if m], key=lambda m: m["utc"])


def pct(hits, n):
    return round(100 * hits / n) if n else ""


def avg(v, n, nd=1):
    return round(v / n, nd) if n else ""


def ts(m, title, side):
    v = m["team_stats"].get(title)
    return v[side] if v and v[side] is not None else None


def espn_val(m, key, side):
    e = (m.get("espn") or {}).get("h" if side == 0 else "a") or {}
    v = e.get(key)
    return v if isinstance(v, (int, float)) else None


# ---------------- Teams ----------------
TEAM_COLS = ["Team", "P", "W %", "D %", "L %", "Win or draw %", "Win by 1 %", "Win by 2+ %",
             "Goals for avg", "Goals against avg", "Scores 1+ %", "Scores 2+ %", "Scores 3+ %", "Clean sheet %", "BTTS %",
             "Match goals avg", "Over 0.5 %", "Over 1.5 %", "Over 2.5 %", "Over 3.5 %", "Over 4.5 %",
             "Leading at HT %", "Level at HT %", "HT/FT Win/Win %", "HT/FT Draw/Win %",
             "More goals 1st half %", "More goals 2nd half %", "Halves level %",
             "Corners avg", "Corners 3+ %", "Corners 4+ %", "Corners 5+ %", "Corners 6+ %", "Corners 7+ %",
             "Match corners avg", "Match corners 8+ %", "Match corners 9+ %", "Match corners 10+ %", "Match corners 11+ %", "Match corners 12+ %",
             "Most corners %",
             "Cards avg", "Cards 1+ %", "Cards 2+ %", "Cards 3+ %", "Match cards avg", "Match cards 3+ %", "Match cards 4+ %",
             "Match cards 5+ %", "Match cards 6+ %", "Both teams booked %", "Most cards %",
             "Fouls avg", "Fouls won (free kicks) avg", "Most fouls %",
             "Shots avg", "Shots on target avg", "SOT 3+ %", "SOT 4+ %", "SOT 5+ %", "SOT 6+ %", "Match SOT avg",
             "Shots against avg", "SOT against avg", "Keeper saves avg", "Offsides avg",
             "Throw-ins avg", "Match throw-ins avg", "Goal kicks avg", "Match goal kicks avg", "Last 5 (newest first)"]


def team_rows(matches, scope):
    by = defaultdict(list)
    names = {}
    for m in matches:
        for side, t in ((0, m["home"]), (1, m["away"])):
            names[t["id"]] = t["name"]
            by[t["id"]].append((m, side))
    rows = []
    for tid, lst in by.items():
        if scope is not None and tid not in scope: continue
        n = len(lst); c = defaultdict(float); cnt = defaultdict(int); form = []
        for m, s in lst:
            o = 1 - s
            gf = m["home"]["score"] if s == 0 else m["away"]["score"]
            ga = m["away"]["score"] if s == 0 else m["home"]["score"]
            gf, ga = gf or 0, ga or 0
            res = "W" if gf > ga else "D" if gf == ga else "L"; form.append(res)
            c["gf"] += gf; c["ga"] += ga; c["tg"] += gf + ga
            cnt[res] += 1
            cnt["w1"] += gf - ga == 1; cnt["w2"] += gf - ga >= 2
            for k in (1, 2, 3): cnt[f"s{k}"] += gf >= k
            cnt["cs"] += ga == 0; cnt["btts"] += gf > 0 and ga > 0
            for k in (1, 2, 3, 4, 5): cnt[f"o{k}"] += gf + ga >= k
            ht = m.get("ht")
            if ht:
                hf, hg = (ht[0], ht[1]) if s == 0 else (ht[1], ht[0])
                cnt["htn"] += 1
                cnt["htl"] += hf > hg; cnt["htd"] += hf == hg
                cnt["ww"] += hf > hg and res == "W"; cnt["dw"] += hf == hg and res == "W"
                g1, g2 = ht[0] + ht[1], (gf + ga) - (ht[0] + ht[1])
                cnt["h1"] += g1 > g2; cnt["h2"] += g2 > g1; cnt["heq"] += g1 == g2
            def stat(title, key):
                a, b = ts(m, title, s), ts(m, title, o)
                if a is None: return None, None
                c[key] += a; cnt[key + "_n"] += 1
                if b is not None: c[key + "_m"] += a + b; cnt[key + "_mn"] += 1
                return a, b
            a, b = stat("Corners", "cor")
            if a is not None:
                for k in (3, 4, 5, 6, 7): cnt[f"cor{k}"] += a >= k
                if b is not None:
                    for k in (8, 9, 10, 11, 12): cnt[f"mc{k}"] += a + b >= k
                    cnt["cormost"] += a > b
            yc, oyc = ts(m, "Yellow cards", s), ts(m, "Yellow cards", o)
            rc, orc = ts(m, "Red cards", s) or 0, ts(m, "Red cards", o) or 0
            if yc is not None:
                tc, otc = yc + rc, (oyc or 0) + orc
                c["card"] += tc; cnt["card_n"] += 1; c["mcard"] += tc + otc
                for k in (1, 2, 3): cnt[f"cd{k}"] += tc >= k
                for k in (3, 4, 5, 6): cnt[f"mcd{k}"] += tc + otc >= k
                cnt["bb"] += tc > 0 and otc > 0; cnt["cdmost"] += tc > otc
            a, b = stat("Fouls committed", "foul")
            if b is not None:
                c["fw"] += b; cnt["fw_n"] += 1; cnt["foulmost"] += a > b
            stat("Total shots", "sh")
            a, b = stat("Shots on target", "sot")
            if a is not None:
                for k in (3, 4, 5, 6): cnt[f"sot{k}"] += a >= k
            for title, key in (("Total shots", "sha"), ("Shots on target", "sota")):
                v = ts(m, title, o)
                if v is not None: c[key] += v; cnt[key + "_n"] += 1
            stat("Keeper saves", "sv"); stat("Offsides", "off")
            stat("Throws", "thr")
            g, og = espn_val(m, "goalKicks", s), espn_val(m, "goalKicks", o)
            if g is not None:
                c["gk"] += g; cnt["gk_n"] += 1
                if og is not None: c["gk_m"] += g + og; cnt["gk_mn"] += 1
        A = lambda k, nd=1: avg(c[k], cnt[k + "_n"], nd)
        P = lambda k, base: pct(cnt[k], cnt[base] if isinstance(base, str) else base)
        rows.append([names[tid], n, pct(cnt["W"], n), pct(cnt["D"], n), pct(cnt["L"], n), pct(cnt["W"] + cnt["D"], n),
                     pct(cnt["w1"], n), pct(cnt["w2"], n), avg(c["gf"], n, 2), avg(c["ga"], n, 2),
                     pct(cnt["s1"], n), pct(cnt["s2"], n), pct(cnt["s3"], n), pct(cnt["cs"], n), pct(cnt["btts"], n),
                     avg(c["tg"], n, 2)] + [pct(cnt[f"o{k}"], n) for k in (1, 2, 3, 4, 5)] +
                    [P("htl", "htn"), P("htd", "htn"), P("ww", "htn"), P("dw", "htn"), P("h1", "htn"), P("h2", "htn"), P("heq", "htn"),
                     A("cor")] + [P(f"cor{k}", "cor_n") for k in (3, 4, 5, 6, 7)] +
                    [avg(c["cor_m"], cnt["cor_mn"])] + [P(f"mc{k}", "cor_mn") for k in (8, 9, 10, 11, 12)] + [P("cormost", "cor_mn"),
                     A("card")] + [P(f"cd{k}", "card_n") for k in (1, 2, 3)] + [avg(c["mcard"], cnt["card_n"])] +
                    [P(f"mcd{k}", "card_n") for k in (3, 4, 5, 6)] + [P("bb", "card_n"), P("cdmost", "card_n"),
                     A("foul"), A("fw"), P("foulmost", "fw_n"), A("sh"), A("sot")] + [P(f"sot{k}", "sot_n") for k in (3, 4, 5, 6)] +
                    [avg(c["sot_m"], cnt["sot_mn"]), A("sha"), A("sota"), A("sv"), A("off"), A("thr"), avg(c["thr_m"], cnt["thr_mn"]),
                     A("gk"), avg(c["gk_m"], cnt["gk_mn"]), "".join(reversed(form[-5:]))])
    rows.sort(key=lambda r: r[0])
    return rows


# ---------------- Players ----------------
PLAYER_COLS = ["Player", "Team", "Status", "Pos", "Apps", "Starts", "Avg mins",
               "Goals", "Goal 1+ %", "Goal 2+ %", "Assists", "Assist 1+ %", "Score or assist %",
               "Shots avg", "Shots 1+ %", "Shots 2+ %", "Shots 3+ %", "Shots 4+ %", "Shots 5+ %",
               "SOT avg", "SOT 1+ %", "SOT 2+ %", "SOT 3+ %", "SOT 4+ %",
               "Headed SOT 1+ %", "Headed shots 1+ %", "SOT outside box 1+ %", "Shots outside box 1+ %",
               "Fouls avg", "Fouls 1+ %", "Fouls 2+ %", "Fouls 3+ %", "Fouls 4+ %",
               "Fouled avg", "Fouled 1+ %", "Fouled 2+ %", "Fouled 3+ %", "Fouled 4+ %",
               "Tackles avg", "Tackles 1+ %", "Tackles 2+ %", "Tackles 3+ %", "Tackles 4+ %", "Tackles 5+ %",
               "Booked %", "Yellows", "Reds",
               "Saves avg", "Saves 1+ %", "Saves 2+ %", "Saves 3+ %", "Saves 4+ %", "Saves 5+ %", "Saves 6+ %",
               "Last 5 SOT", "Last 5 shots", "Last 5 fouls", "Last 5 tackles"]


def player_rows(matches, scope, lg, all_last_team, avail, team_names):
    games = defaultdict(list)
    for m in matches:
        for p in m["players"]:
            games[p["id"]].append((m, p))
    # team's league matches, to work out suspensions
    team_matches = defaultdict(list)
    for m in matches:
        team_matches[m["home"]["id"]].append(m["utc"]); team_matches[m["away"]["id"]].append(m["utc"])
    rows = []
    for pid, lst in games.items():
        lst.sort(key=lambda x: x[0]["utc"])
        last_m, last_p = lst[-1]
        team = last_p["team"]
        if scope is not None and team not in scope: continue
        n = len(lst); mins = sum(p["min"] for _, p in lst)
        if mins / n < MIN_AVG_MINUTES: continue
        P = [p for _, p in lst]
        is_gk = sum(p["gk"] for p in P) > n / 2
        tot = lambda k: sum(p[k] for p in P)
        hit = lambda f: pct(sum(1 for p in P if f(p)), n)
        # status
        status = ""
        a = avail.get(str(pid))
        played_since = [u for u in team_matches[team] if u > last_m["utc"]]
        if last_p["rc"] and not played_since:
            status = "Suspended (red card)"
        elif not played_since and last_p["yc"] and tot("yc") % lg["yc_ban"] == 0 and tot("yc") > 0:
            status = f"Likely suspended ({tot('yc')} yellows)"
        if a:
            if a["type"] == "suspension": status = "Suspended"
            elif not status:
                ret = (a.get("ret") or "").strip()
                if ret.lower() == "doubtful": status = "Doubtful"
                elif ret.lower().startswith("back"): status = "Injured (back in training)"
                elif a["type"] == "injury": status = "Injured" + (f", return: {ret}" if ret else "")
                else: status = "Unavailable" + (f", return: {ret}" if ret else "")
        moved = all_last_team.get(pid, {}).get("from")
        if moved and moved[0] == team:  # transferred into this team this season
            frm = moved[1]
            status = (status + "; " if status else "") + f"Transferred (from {frm})"
        last5 = list(reversed(P[-5:]))
        rows.append([last_p["name"], team_names.get(team, last_p.get("teamName")), status, "GK" if is_gk else "",
                     n, sum(p["start"] for p in P), round(mins / n),
                     int(tot("g")), hit(lambda p: p["g"] >= 1), hit(lambda p: p["g"] >= 2), int(tot("a")), hit(lambda p: p["a"] >= 1),
                     hit(lambda p: p["g"] + p["a"] >= 1),
                     avg(tot("sh"), n)] + [hit(lambda p, k=k: p["sh"] >= k) for k in (1, 2, 3, 4, 5)] +
                    [avg(tot("sot"), n)] + [hit(lambda p, k=k: p["sot"] >= k) for k in (1, 2, 3, 4)] +
                    [hit(lambda p: p["hsot"] >= 1), hit(lambda p: p["hsh"] >= 1), hit(lambda p: p["osot"] >= 1), hit(lambda p: p["osh"] >= 1),
                     avg(tot("fc"), n)] + [hit(lambda p, k=k: p["fc"] >= k) for k in (1, 2, 3, 4)] +
                    [avg(tot("fw"), n)] + [hit(lambda p, k=k: p["fw"] >= k) for k in (1, 2, 3, 4)] +
                    [avg(tot("tk"), n)] + [hit(lambda p, k=k: p["tk"] >= k) for k in (1, 2, 3, 4, 5)] +
                    [hit(lambda p: p["yc"] + p["rc"] >= 1), int(tot("yc")), int(tot("rc"))] +
                    ([avg(tot("sv"), n)] + [hit(lambda p, k=k: p["sv"] >= k) for k in (1, 2, 3, 4, 5, 6)] if is_gk else [""] * 7) +
                    [" ".join(str(int(p["sot"])) for p in last5), " ".join(str(int(p["sh"])) for p in last5),
                     " ".join(str(int(p["fc"])) for p in last5), " ".join(str(int(p["tk"])) for p in last5)])
    rows.sort(key=lambda r: (r[1] or "", -r[6]))
    return rows


def transfers_index():
    """For each player, if his most recent club (any competition) differs from an earlier club this season."""
    hist = defaultdict(list)
    base = os.path.join(DATA, "matches")
    for key in os.listdir(base) if os.path.isdir(base) else []:
        for m in load_matches(key):
            for p in m["players"]:
                hist[p["id"]].append((m["utc"], p["team"], p.get("teamName")))
    res = {}
    for pid, h in hist.items():
        h.sort()
        last_team = h[-1][1]
        prev = [x for x in h if x[1] != last_team]
        if prev:
            res[pid] = {"from": (last_team, prev[-1][2])}
    return res


def main():
    os.makedirs(OUT, exist_ok=True)
    for fn in os.listdir(OUT):
        if fn.endswith(".csv"): os.remove(os.path.join(OUT, fn))
    from zoneinfo import ZoneInfo
    stamp = dt.datetime.now(ZoneInfo("Europe/London")).strftime("%d %b %Y %H:%M") + " UK time"
    moves = transfers_index()
    locked = jload(os.path.join(DATA, "locked_teams.json"), {})
    summary = []
    for lg in LEAGUES:
        matches = load_matches(lg["key"])
        if not matches: continue
        table = jload(os.path.join(DATA, "tables", f"{lg['key']}.json"), []) or []
        names = {t["id"]: t["name"] for t in table}
        for m in matches:
            names.setdefault(m["home"]["id"], m["home"]["name"]); names.setdefault(m["away"]["id"], m["away"]["name"])
        mode = lg["mode"]
        if mode == "all": scope = None
        elif mode == "top5": scope = {int(k) for k in locked.get(lg["key"], {}).get("teams", {})}
        else:
            # "table" and explicit lists: teams fetch.py kept
            if mode == "table": scope = {t["id"] for t in table} or None
            else:
                from fetch import scope_teams
                scope = set(scope_teams(lg, table))
        avail = (jload(os.path.join(DATA, "availability", f"{lg['key']}.json"), {}) or {}).get("players", {})
        trows = team_rows(matches, scope)
        prows = player_rows(matches, scope, lg, moves, avail, names)
        last_date = max(m["date"] for m in matches)
        with open(os.path.join(OUT, f"{lg['key']}_teams.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([f"{lg['name']} 2026-27: team stats from {len(matches)} league games (latest {last_date}). Updated {stamp}. % = share of games"])
            w.writerow(TEAM_COLS); w.writerows(blank_zeros(trows))
        with open(os.path.join(OUT, f"{lg['key']}_players.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([f"Player hit rates: players averaging {MIN_AVG_MINUTES}+ mins. % = share of their league appearances. Last 5 = newest first"])
            w.writerow(PLAYER_COLS); w.writerows(blank_zeros(prows))
        summary.append([lg["name"], len(matches), last_date, len(trows), len(prows),
                        sum(1 for r in prows if r[2].startswith(("Injured", "Doubtful"))),
                        sum(1 for r in prows if "uspended" in r[2]), sum(1 for r in prows if "Transferred" in r[2])])
    with open(os.path.join(OUT, "INDEX.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"Updated {stamp}"])
        w.writerow(["League", "Matches loaded", "Latest match", "Teams", "Players", "Injured/doubtful", "Suspended", "Transferred"])
        w.writerows(summary)
    print("\n".join(str(s) for s in summary))


if __name__ == "__main__":
    main()
