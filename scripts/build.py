"""Turn cached matches into CSVs for the Google Sheet.

Per league: <KEY>_teams.csv (team markets, home/away splits, last-5, next opponent)
            <KEY>_players.csv (player hit rates incl. last-5, next match)
Plus TODAY.csv (best 80%+ markets for games in the next 24 hours) and INDEX.csv.
"""
import csv, json, os, re, datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo
from config import LEAGUES, MIN_AVG_MINUTES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, OUT = os.path.join(ROOT, "data"), os.path.join(ROOT, "out")
UK = ZoneInfo("Europe/London")
MIN_APPS = 3          # players need this many league appearances to be listed
PICK_MIN = 80         # Today tab: true rate (see true_rate) at least this
TRUE_K = 4            # true rate = record plus this many league-average games (backtest: best predictor)
TOP_PLAYER_PER_MATCH = 5   # Today tab "top picks" per match (All picks tab has no limit)
TOP_TEAM_PER_MATCH = 3
PROVEN_MIN_PICKS, PROVEN_MIN_RATE = 20, 75   # a market is "proven" once the tracker has graded 20+ picks hitting 75%+


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


def ts(m, title, side):
    v = m["team_stats"].get(title)
    return v[side] if v and v[side] is not None else None


def espn_val(m, key, side):
    e = (m.get("espn") or {}).get("h" if side == 0 else "a") or {}
    v = e.get(key)
    return v if isinstance(v, (int, float)) else None


def uk_time(utc):
    try:
        t = dt.datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(UK)
        return t.strftime("%a %d %b · %H:%M")  # the dot stops Sheets turning it into a number
    except Exception:
        return ""


# ---------------- Teams ----------------

def team_record(m, s):
    """One team's view of one match."""
    o = 1 - s
    gf = (m["home"]["score"] if s == 0 else m["away"]["score"]) or 0
    ga = (m["away"]["score"] if s == 0 else m["home"]["score"]) or 0
    r = {"home": s == 0, "gf": gf, "ga": ga, "res": "W" if gf > ga else "D" if gf == ga else "L"}
    ht = m.get("ht")
    if ht:
        r["hf"], r["hg"] = (ht[0], ht[1]) if s == 0 else (ht[1], ht[0])
    for title, k in (("Corners", "cor"), ("Fouls committed", "foul"), ("Total shots", "sh"), ("Shots on target", "sot"),
                     ("Keeper saves", "sv"), ("Offsides", "off"), ("Throws", "thr"), ("Yellow cards", "yc"), ("Red cards", "rc")):
        r[k], r["o" + k] = ts(m, title, s), ts(m, title, o)
    # Cards from FotMob's team totals: these agree with ESPN in 98% of matches (players' own cards only 95%)
    if r["yc"] is not None:
        r["card"] = r["yc"] + (r["rc"] or 0)
        r["ocard"] = (r["oyc"] or 0) + (r["orc"] or 0)
    else:
        r["card"] = r["ocard"] = None
    r["gk"], r["ogk"] = espn_val(m, "goalKicks", s), espn_val(m, "goalKicks", o)
    return r


def A(recs, f, nd=1):
    vals = [f(r) for r in recs]
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), nd) if vals else ""


def P(recs, f, need=None):
    """% of records where f is true; records missing the needed stat are left out."""
    rs = [r for r in recs if need is None or all(r.get(k) is not None for k in need)]
    return pct(sum(1 for r in rs if f(r)), len(rs))


def tsum(*keys):
    return lambda r: None if any(r.get(k) is None for k in keys) else sum(r[k] for k in keys)


# (column, function of a list of team records)
TEAM_STATS = [
    ("W %", lambda R: P(R, lambda r: r["res"] == "W")), ("D %", lambda R: P(R, lambda r: r["res"] == "D")),
    ("L %", lambda R: P(R, lambda r: r["res"] == "L")), ("Win or draw %", lambda R: P(R, lambda r: r["res"] != "L")),
    ("Win by 1 %", lambda R: P(R, lambda r: r["gf"] - r["ga"] == 1)), ("Win by 2+ %", lambda R: P(R, lambda r: r["gf"] - r["ga"] >= 2)),
    ("Goals for avg", lambda R: A(R, lambda r: r["gf"], 2)), ("Goals against avg", lambda R: A(R, lambda r: r["ga"], 2)),
    ("Scores 1+ %", lambda R: P(R, lambda r: r["gf"] >= 1)), ("Scores 2+ %", lambda R: P(R, lambda r: r["gf"] >= 2)),
    ("Scores 3+ %", lambda R: P(R, lambda r: r["gf"] >= 3)), ("Clean sheet %", lambda R: P(R, lambda r: r["ga"] == 0)),
    ("BTTS %", lambda R: P(R, lambda r: r["gf"] > 0 and r["ga"] > 0)),
    ("Match goals avg", lambda R: A(R, lambda r: r["gf"] + r["ga"], 2))] + [
    (f"Over {k - 0.5} %", (lambda k: lambda R: P(R, lambda r: r["gf"] + r["ga"] >= k))(k)) for k in (1, 2, 3, 4, 5)] + [
    ("Leading at HT %", lambda R: P(R, lambda r: r["hf"] > r["hg"], ["hf"])),
    ("Level at HT %", lambda R: P(R, lambda r: r["hf"] == r["hg"], ["hf"])),
    ("HT/FT Win/Win %", lambda R: P(R, lambda r: r["hf"] > r["hg"] and r["res"] == "W", ["hf"])),
    ("HT/FT Draw/Win %", lambda R: P(R, lambda r: r["hf"] == r["hg"] and r["res"] == "W", ["hf"])),
    ("More goals 1st half %", lambda R: P(R, lambda r: r["hf"] + r["hg"] > (r["gf"] + r["ga"]) - (r["hf"] + r["hg"]), ["hf"])),
    ("More goals 2nd half %", lambda R: P(R, lambda r: r["hf"] + r["hg"] < (r["gf"] + r["ga"]) - (r["hf"] + r["hg"]), ["hf"])),
    ("Halves level %", lambda R: P(R, lambda r: 2 * (r["hf"] + r["hg"]) == r["gf"] + r["ga"], ["hf"])),
    ("Corners avg", lambda R: A(R, lambda r: r["cor"]))] + [
    (f"Corners {k}+ %", (lambda k: lambda R: P(R, lambda r: r["cor"] >= k, ["cor"]))(k)) for k in (3, 4, 5, 6, 7)] + [
    ("Match corners avg", lambda R: A(R, tsum("cor", "ocor")))] + [
    (f"Match corners {k}+ %", (lambda k: lambda R: P(R, lambda r: r["cor"] + r["ocor"] >= k, ["cor", "ocor"]))(k)) for k in (8, 9, 10, 11, 12)] + [
    ("Most corners %", lambda R: P(R, lambda r: r["cor"] > r["ocor"], ["cor", "ocor"])),
    ("Cards avg", lambda R: A(R, lambda r: r["card"]))] + [
    (f"Cards {k}+ %", (lambda k: lambda R: P(R, lambda r: r["card"] >= k, ["card"]))(k)) for k in (1, 2, 3)] + [
    ("Match cards avg", lambda R: A(R, tsum("card", "ocard")))] + [
    (f"Match cards {k}+ %", (lambda k: lambda R: P(R, lambda r: r["card"] + r["ocard"] >= k, ["card"]))(k)) for k in (3, 4, 5, 6)] + [
    ("Both teams booked %", lambda R: P(R, lambda r: r["card"] > 0 and r["ocard"] > 0, ["card"])),
    ("Most cards %", lambda R: P(R, lambda r: r["card"] > r["ocard"], ["card"])),
    ("Fouls avg", lambda R: A(R, lambda r: r["foul"])), ("Fouls won (free kicks) avg", lambda R: A(R, lambda r: r["ofoul"])),
    ("Most fouls %", lambda R: P(R, lambda r: r["foul"] > r["ofoul"], ["foul", "ofoul"])),
    ("Shots avg", lambda R: A(R, lambda r: r["sh"])), ("Shots on target avg", lambda R: A(R, lambda r: r["sot"]))] + [
    (f"SOT {k}+ %", (lambda k: lambda R: P(R, lambda r: r["sot"] >= k, ["sot"]))(k)) for k in (3, 4, 5, 6)] + [
    ("Match SOT avg", lambda R: A(R, tsum("sot", "osot"))),
    ("Shots against avg", lambda R: A(R, lambda r: r["osh"])), ("SOT against avg", lambda R: A(R, lambda r: r["osot"])),
    ("Corners against avg", lambda R: A(R, lambda r: r["ocor"])),
    ("Keeper saves avg", lambda R: A(R, lambda r: r["sv"])), ("Offsides avg", lambda R: A(R, lambda r: r["off"])),
    ("Throw-ins avg", lambda R: A(R, lambda r: r["thr"])), ("Match throw-ins avg", lambda R: A(R, tsum("thr", "othr"))),
    ("Goal kicks avg", lambda R: A(R, lambda r: r["gk"])), ("Match goal kicks avg", lambda R: A(R, tsum("gk", "ogk"))),
]
TS = dict(TEAM_STATS)
SPLIT_KEYS = ["W %", "Scores 1+ %", "Clean sheet %", "BTTS %", "Over 2.5 %", "Corners avg", "Corners 5+ %",
              "Cards avg", "Cards 2+ %", "Shots on target avg"]
TEAM_L5_KEYS = ["W %", "Scores 1+ %", "BTTS %", "Over 1.5 %", "Over 2.5 %", "Corners 4+ %", "Corners 5+ %",
                "Match corners 9+ %", "Match corners 10+ %", "Cards 1+ %", "Cards 2+ %", "Match cards 4+ %", "SOT 4+ %"]
OPP_COLS = ["Next opponent", "Next match (UK)", "Next venue", "Opp goals conceded avg", "Opp shots conceded avg",
            "Opp SOT conceded avg", "Opp corners conceded avg", "Opp fouls committed avg", "Opp cards avg", "Opp last 5"]

TEAM_COLS = (["Team", "P"] + [c for c, _ in TEAM_STATS] + ["Last 5 (newest first)"] +
             [f"Home {k}" for k in SPLIT_KEYS for _ in [0]] + [f"Away {k}" for k in SPLIT_KEYS] +
             [f"L5 {k}" for k in TEAM_L5_KEYS] + OPP_COLS)


def team_records(matches):
    recs, names = defaultdict(list), {}
    for m in matches:
        for s, t in ((0, m["home"]), (1, m["away"])):
            names[t["id"]] = t["name"]
            recs[t["id"]].append(team_record(m, s))
    return recs, names


def next_fixture(tid, fixtures):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for f in sorted(fixtures, key=lambda f: f.get("utc") or ""):
        if f.get("started") or (f.get("utc") or "") < now[:19]:
            continue
        if tid in (f["home"]["id"], f["away"]["id"]):
            return f
    return None


def opp_context(tid, fixtures, recs, names):
    f = next_fixture(tid, fixtures)
    if not f:
        return ["", "", "", "", "", "", "", "", "", ""], None
    home = f["home"]["id"] == tid
    opp = f["away"] if home else f["home"]
    R = recs.get(opp["id"], [])
    form = "".join(reversed([r["res"] for r in R[-5:]]))
    ctx = {"goals": A(R, lambda r: r["ga"], 2), "shots": A(R, lambda r: r["osh"]), "sot": A(R, lambda r: r["osot"]),
           "corners": A(R, lambda r: r["ocor"]), "fouls": A(R, lambda r: r["foul"]), "cards": A(R, lambda r: r["card"]),
           "fouls_won": A(R, lambda r: r["ofoul"]), "sot_for": A(R, lambda r: r["sot"]), "name": names.get(opp["id"], opp["name"]), "utc": f.get("utc"),
           "venue": "H" if home else "A", "fixture": f}
    return [ctx["name"], uk_time(f.get("utc")), "Home" if home else "Away", ctx["goals"], ctx["shots"], ctx["sot"],
            ctx["corners"], ctx["fouls"], ctx["cards"], form], ctx


def team_rows(recs, names, scope, fixtures):
    rows, info = [], {}
    for tid, R in recs.items():
        if scope is not None and tid not in scope: continue
        H = [r for r in R if r["home"]]; Aw = [r for r in R if not r["home"]]
        opp, ctx = opp_context(tid, fixtures, recs, names)
        vals = {c: f(R) for c, f in TEAM_STATS}
        l5 = {k: TS[k](R[-5:]) for k in TEAM_L5_KEYS}
        info[tid] = {"vals": vals, "l5": l5, "n": len(R), "ctx": ctx, "R": R}
        rows.append([names[tid], len(R)] + [vals[c] for c, _ in TEAM_STATS] +
                    ["".join(reversed([r["res"] for r in R[-5:]]))] +
                    [TS[k](H) for k in SPLIT_KEYS] + [TS[k](Aw) for k in SPLIT_KEYS] +
                    [l5[k] for k in TEAM_L5_KEYS] + opp)
    rows.sort(key=lambda r: r[0])
    return rows, info


# ---------------- Players ----------------
PH = lambda f: (lambda Pl: pct(sum(1 for p in Pl if f(p)), len(Pl)))
PA = lambda k, nd=1: (lambda Pl: round(sum(p[k] for p in Pl) / len(Pl), nd) if Pl else "")
PLAYER_STATS = [
    ("Goals", lambda Pl: int(sum(p["g"] for p in Pl))), ("Goal 1+ %", PH(lambda p: p["g"] >= 1)),
    ("Goal 2+ %", PH(lambda p: p["g"] >= 2)), ("Assists", lambda Pl: int(sum(p["a"] for p in Pl))),
    ("Assist 1+ %", PH(lambda p: p["a"] >= 1)), ("Score or assist %", PH(lambda p: p["g"] + p["a"] >= 1)),
    ("Shots avg", PA("sh"))] + [(f"Shots {k}+ %", PH((lambda k: lambda p: p["sh"] >= k)(k))) for k in (1, 2, 3, 4, 5)] + [
    ("SOT avg", PA("sot"))] + [(f"SOT {k}+ %", PH((lambda k: lambda p: p["sot"] >= k)(k))) for k in (1, 2, 3, 4)] + [
    ("Headed SOT 1+ %", PH(lambda p: p["hsot"] >= 1)), ("Headed shots 1+ %", PH(lambda p: p["hsh"] >= 1)),
    ("SOT outside box 1+ %", PH(lambda p: p["osot"] >= 1)), ("Shots outside box 1+ %", PH(lambda p: p["osh"] >= 1)),
    ("Fouls avg", PA("fc"))] + [(f"Fouls {k}+ %", PH((lambda k: lambda p: p["fc"] >= k)(k))) for k in (1, 2, 3, 4)] + [
    ("Fouled avg", PA("fw"))] + [(f"Fouled {k}+ %", PH((lambda k: lambda p: p["fw"] >= k)(k))) for k in (1, 2, 3, 4)] + [
    ("Tackles avg", PA("tk"))] + [(f"Tackles {k}+ %", PH((lambda k: lambda p: p["tk"] >= k)(k))) for k in (1, 2, 3, 4, 5)] + [
    ("Booked %", PH(lambda p: p["yc"] + p["rc"] >= 1)), ("Yellows", lambda Pl: int(sum(p["yc"] for p in Pl))),
    ("Reds", lambda Pl: int(sum(p["rc"] for p in Pl)))]
GK_STATS = [("Saves avg", PA("sv"))] + [(f"Saves {k}+ %", PH((lambda k: lambda p: p["sv"] >= k)(k))) for k in (1, 2, 3)]
PS = dict(PLAYER_STATS + GK_STATS)
PLAYER_L5_KEYS = ["Goal 1+ %", "Score or assist %", "Shots 1+ %", "Shots 2+ %", "SOT 1+ %", "SOT 2+ %",
                  "Fouls 1+ %", "Fouls 2+ %", "Fouled 1+ %", "Fouled 2+ %", "Tackles 1+ %", "Tackles 2+ %",
                  "Booked %", "Saves 2+ %", "Saves 3+ %"]
# hit rates counting only games the player started
STARTS_KEYS = ["Goal 1+ %", "Score or assist %", "Shots 1+ %", "Shots 2+ %", "Shots 3+ %", "SOT 1+ %", "SOT 2+ %",
               "Fouls 1+ %", "Fouls 2+ %", "Fouled 1+ %", "Fouled 2+ %", "Tackles 1+ %", "Tackles 2+ %", "Tackles 3+ %",
               "Booked %"]
PLAYER_COLS = (["Player", "Team", "Status", "Next match", "Pos", "Apps", "Starts", "Avg mins"] +
               [f"True {k}" for k in PLAYER_L5_KEYS] + [c for c, _ in PLAYER_STATS] + [c for c, _ in GK_STATS] + [f"L5 {k}" for k in PLAYER_L5_KEYS] +
               [f"Starts: {k}" for k in STARTS_KEYS] +
               ["Last 5 SOT", "Last 5 shots", "Last 5 fouls", "Last 5 tackles", "Last 5 dates"])
SMALL = 6   # fewer games than this = small sample
# market -> which opponent number gives useful context in the Today tab
OPP_FOR = {"Goal": ("goals", "goals conceded"), "Score": ("goals", "goals conceded"), "Shots": ("shots", "shots conceded"),
           "SOT": ("sot", "SOT conceded"), "Fouls": ("fouls_won", "fouls won"), "Fouled": ("fouls", "fouls committed"),
           "Booked": ("fouls_won", "fouls won"), "Saves": ("sot_for", "shots on target")}


def true_rate(games, hit, base):
    """Hit rate pulled toward the league average: (hits + K x average) / (games + K).
    Small samples (5 from 5) stop showing 100%; long records barely move."""
    if not games or base is None: return ""
    h = sum(1 for g in games if hit(g))
    return round(100 * (h + TRUE_K * base) / (len(games) + TRUE_K))


def player_hit(k):
    return lambda p: PS[k]([p]) == 100


def player_bases(matches):
    """League-wide share of player-games hitting each market (keepers only for saves)."""
    base = {}
    for k in PLAYER_L5_KEYS:
        pool = [p for m in matches for p in m["players"] if p.get("min") and (p["gk"] if k.startswith("Saves") else True)]
        base[k] = sum(1 for p in pool if PS[k]([p]) == 100) / len(pool) if pool else None
    return base


def player_rows(matches, scope, lg, all_last_team, avail, team_names, team_info, squads=None, apps=None):
    squads = squads or {}; apps = apps or {}
    games = defaultdict(list)
    for m in matches:
        for p in m["players"]:
            games[p["id"]].append((m, p))
    team_matches = defaultdict(list)
    for m in matches:
        team_matches[m["home"]["id"]].append(m["utc"]); team_matches[m["away"]["id"]].append(m["utc"])
    most = max((len(v) for v in team_matches.values()), default=0)
    min_apps = min(MIN_APPS, max(1, most - 1))
    rows, picks = [], []
    bases = player_bases(matches)
    for pid, lst in games.items():
        lst.sort(key=lambda x: x[0]["utc"])
        last_m, last_p = lst[-1]
        team = last_p["team"]
        if scope is not None and team not in scope: continue
        n = len(lst); mins = sum(p["min"] for _, p in lst)
        if n < min_apps or mins / n < MIN_AVG_MINUTES: continue
        Pl = [p for _, p in lst]; L5 = Pl[-5:]
        is_gk = sum(p["gk"] for p in Pl) > n / 2
        yc_total = sum(p["yc"] for p in Pl)
        status = ""
        a = avail.get(str(pid))
        played_since = [u for u in team_matches[team] if u > last_m["utc"]]
        if last_p["rc"] and not played_since:
            status = "Suspended (red card)"
        elif not played_since and last_p["yc"] and yc_total and yc_total % lg["yc_ban"] == 0:
            status = f"Likely suspended ({yc_total} yellows)"
        if a:
            if a["type"] == "suspension": status = "Suspended"
            elif not status:
                ret = (a.get("ret") or "").strip()
                if ret.lower() == "doubtful": status = "Doubtful"
                elif ret.lower().startswith("back"): status = "Injured (back in training)"
                elif a["type"] == "injury": status = "Injured" + (f", return: {ret}" if ret else "")
                else: status = "Unavailable" + (f", return: {ret}" if ret else "")
        # back from a spell out: missed 3+ of his team's games, and has played 3 or fewer since
        tm = sorted(team_matches[team]); my = [m["utc"] for m, _ in lst]
        back = 0
        for i in range(len(my) - 1, 0, -1):
            missed = sum(1 for u in tm if my[i - 1] < u < my[i])
            if missed >= 3:
                back = len(my) - i; break
        if 0 < back <= 3 and not status:
            status = f"Back from absence ({back} game{'s' if back > 1 else ''} back)"
        sq = squads.get(str(team))
        later = [a for a in apps.get(pid, []) if a[0] > last_m["utc"] and a[2] != team]
        left = bool(later) or (bool(sq) and pid not in sq)
        if later:
            status = (status + "; " if status else "") + f"Transferred out (now at {later[-1][3]})"
        elif left:
            status = (status + "; " if status else "") + "Transferred out (no longer in squad)"
        moved = all_last_team.get(pid, {}).get("from")
        if moved and moved[0] == team:
            status = (status + "; " if status else "") + f"Transferred (from {moved[1]})"
        ctx = (team_info.get(team) or {}).get("ctx")
        nxt = f"v {ctx['name']} ({ctx['venue']}) {uk_time(ctx['utc'])}" if ctx else ""
        last5 = list(reversed(L5))
        season = {c: f(Pl) for c, f in PLAYER_STATS}
        gk = {c: (f(Pl) if is_gk else "") for c, f in GK_STATS}
        l5 = {k: (PS[k](L5) if (is_gk or not k.startswith("Saves")) else "") for k in PLAYER_L5_KEYS}
        St = [p for p in Pl if p["start"]]
        st = {k: (PS[k](St) if St and not is_gk else "") for k in STARTS_KEYS}
        d5 = [dt.date.fromisoformat(m["date"]) for m, _ in lst[-5:]]
        dates5 = f"{d5[0].strftime('%d %b')} – {d5[-1].strftime('%d %b')}" if d5 else ""
        starter = len(St) >= 0.7 * n and all(p["start"] for p in Pl[-2:])
        tr = {k: (true_rate(Pl, player_hit(k), bases[k]) if (is_gk or not k.startswith("Saves")) else "") for k in PLAYER_L5_KEYS}
        tr_st = {k: (true_rate(St, player_hit(k), bases[k]) if St and not is_gk else "") for k in PLAYER_L5_KEYS}
        rows.append([last_p["name"], team_names.get(team, last_p.get("teamName")), status, nxt, "GK" if is_gk else "",
                     n, sum(p["start"] for p in Pl), round(mins / n)] + [tr[k] for k in PLAYER_L5_KEYS] +
                    [season[c] for c, _ in PLAYER_STATS] + [gk[c] for c, _ in GK_STATS] + [l5[k] for k in PLAYER_L5_KEYS] +
                    [st[k] for k in STARTS_KEYS] +
                    [" · ".join(str(int(p[k])) for p in last5) for k in ("sot", "sh", "fc", "tk")] + [dates5])
        # Today-tab candidates: season and last-5 both strong, player available
        if ctx and not left and not any(w in status for w in ("Injured", "uspended", "Doubtful", "Unavailable")):
            for k in PLAYER_L5_KEYS:
                sv = gk.get(k, season.get(k)); lv = l5[k]
                # regular starters are judged on their true rate when starting (cameos don't drag them down)
                use_start = starter and isinstance(tr_st.get(k), int) and isinstance(st.get(k), int)
                qual = tr_st[k] if use_start else tr[k]
                if isinstance(qual, int) and qual >= PICK_MIN and isinstance(sv, int):
                    picks.append({"true": qual, "fixture": ctx["fixture"], "who": last_p["name"], "team": team_names.get(team, ""),
                                  "market": k.replace(" %", ""), "key": k, "season": sv, "l5": lv, "games": n,
                                  "starts": st.get(k, ""), "nstarts": len(St), "pid": pid, "starter": use_start, "back": back if 0 < back <= 3 else 0,
                                  "opp": ctx, "status": status})
    rows.sort(key=lambda r: (r[1] or "", -r[7]))
    return rows, picks


def team_picks(info, names, recs):
    picks = []
    allr = [r for R in recs.values() for r in R]
    base = {k: (sum(1 for r in allr if TS[k]([r]) == 100) / len(allr) if allr else None) for k in TEAM_L5_KEYS}
    for tid, d in info.items():
        ctx = d["ctx"]
        if not ctx or d["n"] < MIN_APPS: continue
        for k in TEAM_L5_KEYS:
            sv, lv = d["vals"].get(k), d["l5"].get(k)
            tv = true_rate(d["R"], (lambda k: lambda r: TS[k]([r]) == 100)(k), base[k])
            if isinstance(sv, int) and isinstance(tv, int) and tv >= PICK_MIN:
                picks.append({"true": tv, "fixture": ctx["fixture"], "who": names[tid] + " (team)", "team": names[tid],
                              "market": {"W": "Win"}.get(k.replace(" %", ""), k.replace(" %", "")), "key": k, "season": sv, "l5": lv,
                              "games": d["n"], "starts": "", "tid": tid, "opp": ctx, "status": ""})
    return picks


def opp_note(pk):
    m = pk["market"]; ctx = pk["opp"]
    for prefix, (key, label) in OPP_FOR.items():
        if m.startswith(prefix):
            return f"{ctx['name']}: {ctx[key]} {label}/game" if ctx.get(key) != "" else ""
    if any(w in m for w in ("Corners", "corners")):
        return f"{ctx['name']}: {ctx['corners']} corners conceded/game"
    if "cards" in m or "Cards" in m:
        return f"{ctx['name']}: {ctx['fouls_won']} fouls won/game"
    if m.startswith("Tackles"):
        return ""
    return f"{ctx['name']}: {ctx['goals']} goals conceded/game"


TODAY_COLS = ["Pick", "Market", "True %", "Season %", "Last 5 %", "When starting %", "Games", "Kick-off (UK)", "Match",
              "Competition", "Team", "Opponent context", "Note"]


EXACT = {"W %": "Win %", "D %": "Draw %", "L %": "Loss %", "Avg mins": "Avg minutes", "P": "Played"}


def nice(h):
    """Plain-English column / market names for the sheet (internal keys stay short)."""
    pre = ""
    for a, b in (("L5 ", "L5: "), ("Starts: ", "Start: "), ("True ", "True: "), ("Home ", "Home "), ("Away ", "Away ")):
        if h.startswith(a) and h != a.strip():
            pre, h = b, h[len(a):]; break
    h = EXACT.get(h, h)
    h = re.sub(r"^Opp ", "Opponent ", h)
    return pre + h


LEGEND = ["Key:", "100%", "90%+", "80%+", "70%+", "60%+", "50%+", "Under 50%", "Injured / suspended", "Doubtful",
          "Transferred", "Under 6 games"]


# league player tabs group some columns away, so the colour key sits only in columns that stay visible
PLAYER_LEGEND_COLS = list(range(8, 20))   # the True columns, always visible


def title_row(text, legend_at, iso):
    """Row 1 of every tab: title, colour key (cells are coloured in the sheet), and a machine-readable update time.
    legend_at = first column of the key, or a list of columns, or 0 for no key."""
    r = [text] + [""] * 116
    cols = legend_at if isinstance(legend_at, list) else (list(range(legend_at, legend_at + len(LEGEND))) if legend_at else [])
    for c, v in zip(cols, LEGEND): r[c] = v
    return r + [iso]


def fold(name):
    """Lower-case, accent-free version of a name so 'mbappe' finds 'Mbappé'."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", name or "") if not unicodedata.combining(c)).lower()


# ---------------- Pick tracker ----------------

def grade(pk, m):
    """Hit / Miss / Did not play for one logged pick against the finished match."""
    if pk.get("pid") is not None:
        p = next((p for p in m["players"] if str(p["id"]) == str(pk["pid"])), None)
        if not p or not p.get("min"): return "Did not play"
        v = PS[pk["key"]]([p])
    else:
        side = 0 if str(m["home"]["id"]) == str(pk["tid"]) else 1
        v = TS[pk["key"]]([team_record(m, side)])
    return "" if v == "" else ("Hit" if v == 100 else "Miss")


PICKS_DIR = os.path.join(DATA, "picks")


def load_log():
    """All logged picks. Stored as one small file per kick-off day so history stays small in git."""
    log = {}
    legacy = os.path.join(PICKS_DIR, "log.json")
    if os.path.exists(legacy):
        log.update(jload(legacy, {}) or {})
    for fn in sorted(os.listdir(PICKS_DIR)) if os.path.isdir(PICKS_DIR) else []:
        if re.match(r"\d{4}-\d{2}-\d{2}\.json$", fn):
            log.update(jload(os.path.join(PICKS_DIR, fn), {}) or {})
    return log


def save_log(log):
    """Rewrite only the day files whose contents changed; drop the old single file."""
    days = defaultdict(dict)
    for k, e in log.items(): days[e["utc"][:10]][k] = e
    os.makedirs(PICKS_DIR, exist_ok=True)
    for day, entries in days.items():
        path = os.path.join(PICKS_DIR, f"{day}.json")
        if (jload(path, None) or None) != entries:
            with open(path, "w") as f: json.dump(entries, f, indent=0, sort_keys=True)
    legacy = os.path.join(PICKS_DIR, "log.json")
    if os.path.exists(legacy): os.remove(legacy)


def track_picks(sel, match_by_id, stamp):
    """Log Today picks before kick-off (first sighting is kept) and grade them once the match is in."""
    log = load_log()
    now = dt.datetime.now(dt.timezone.utc)
    for p in sel:
        fx = p["fixture"]
        try:
            if dt.datetime.fromisoformat(fx["utc"].replace("Z", "+00:00")) <= now: continue
        except Exception:
            continue
        k = f"{fx['id']}|{p.get('pid', p.get('tid'))}|{p['key']}"
        if k in log: continue
        log[k] = {"fixture": str(fx["id"]), "utc": fx["utc"], "league": p["league"], "match": f"{fx['home']['name']} v {fx['away']['name']}",
                  "who": p["who"], "market": p["market"], "key": p["key"], "season": p["season"], "l5": p["l5"], "true": p.get("true"),
                  "games": p["games"], "pid": p.get("pid"), "tid": p.get("tid"), "result": ""}
    for e in log.values():
        if not e["result"] and e["fixture"] in match_by_id:
            try: e["result"] = grade(e, match_by_id[e["fixture"]])
            except Exception as ex: print("grade failed", e["who"], e["market"], ex)
        elif not e["result"]:
            # postponed / abandoned: still not played 3 days after kick-off
            try:
                if now - dt.datetime.fromisoformat(e["utc"].replace("Z", "+00:00")) > dt.timedelta(days=3):
                    e["result"] = "Void (not played)"
            except Exception:
                pass
    save_log(log)
    graded = [e for e in log.values() if e["result"] in ("Hit", "Miss")]
    by = defaultdict(list)
    for e in graded: by[e["market"]].append(e)
    def avg_true(es):
        t = [e["true"] for e in es if isinstance(e.get("true"), (int, float))]
        return round(sum(t) / len(t)) if t else ""
    summ = [["All picks", len(graded), sum(e["result"] == "Hit" for e in graded),
             pct(sum(e["result"] == "Hit" for e in graded), len(graded)),
             round(sum(e["season"] for e in graded) / len(graded)) if graded else "", avg_true(graded)]]
    for mk, es in sorted(by.items(), key=lambda x: -len(x[1])):
        h = sum(e["result"] == "Hit" for e in es)
        summ.append([nice(mk), len(es), h, pct(h, len(es)), round(sum(e["season"] for e in es) / len(es)), avg_true(es)])
    rows = sorted(log.values(), key=lambda e: e["utc"], reverse=True)[:1500]
    with open(os.path.join(OUT, "TRACKER.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"How the Today picks actually did (logged before kick-off, graded after the match). Updated {stamp}. "
                    "'Season said %' = average season hit rate when the pick was made; 'True rate said %' = the adjusted rate (picks from 2 Nov)"])
        w.writerow(["Market", "Picks graded", "Hits", "Actual hit rate %", "Season said %", "True rate said %"])
        w.writerows(summ)
        w.writerow([]); w.writerow(["Every logged pick, newest first ('Did not play' and pending picks don't count)"])
        w.writerow(["Player", "Market", "Match", "Kick-off (UK)", "Competition", "True %", "Season %", "Last 5 %", "Result"])
        w.writerows([[e["who"], nice(e["market"]), e["match"], uk_time(e["utc"]), e["league"], e.get("true") or "", e["season"], e["l5"],
                      e["result"] or "Pending"] for e in rows] or [["No picks logged yet"]])


def apps_index():
    """player id -> [(kick-off, competition, team id, team name, started)] across all tracked competitions."""
    idx = defaultdict(list)
    for lg in LEAGUES:
        for m in load_matches(lg["key"]):
            for p in m["players"]:
                idx[p["id"]].append((m["utc"], lg["name"], p["team"], p.get("teamName"), bool(p.get("start"))))
    for v in idx.values(): v.sort()
    return idx


def transfers_index():
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
    now = dt.datetime.now(UK)
    stamp = now.strftime("%d %b %Y %H:%M") + " UK time"
    iso = now.strftime("%Y-%m-%d %H:%M")
    short = now.strftime("%a %d %b %H:%M")
    team_rows_all = []
    moves = transfers_index()
    started = apps_index()
    locked = jload(os.path.join(DATA, "locked_teams.json"), {})
    summary, all_picks, all_players, match_by_id = [], [], [], {}
    for lg in LEAGUES:
        matches = load_matches(lg["key"])
        if not matches: continue
        for m in matches: match_by_id[str(m["id"])] = m
        table = jload(os.path.join(DATA, "tables", f"{lg['key']}.json"), []) or []
        fixtures = jload(os.path.join(DATA, "fixtures", f"{lg['key']}.json"), []) or []
        names = {t["id"]: t["name"] for t in table}
        for m in matches:
            names.setdefault(m["home"]["id"], m["home"]["name"]); names.setdefault(m["away"]["id"], m["away"]["name"])
        mode = lg["mode"]
        if mode == "all": scope = None
        elif mode == "top5": scope = {int(k) for k in locked.get(lg["key"], {}).get("teams", {})}
        elif mode == "table": scope = {t["id"] for t in table} or None
        else:
            from fetch import scope_teams
            scope = set(scope_teams(lg, table))
        avail_file = jload(os.path.join(DATA, "availability", f"{lg['key']}.json"), {}) or {}
        avail, squads = avail_file.get("players", {}), avail_file.get("squads", {})
        recs, rnames = team_records(matches)
        names.update({k: v for k, v in rnames.items() if k not in names})
        trows, info = team_rows(recs, names, scope, fixtures)
        prows, picks = player_rows(matches, scope, lg, moves, avail, names, info, squads, started)
        for pk in picks + team_picks(info, names, recs):
            pk["league"] = lg["name"]; all_picks.append(pk)
        last_date = max(m["date"] for m in matches)
        with open(os.path.join(OUT, f"{lg['key']}_teams.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([f"{lg['name']} 2026-27: team stats from {len(matches)} league games (latest {last_date}). Updated {stamp}. % = share of games. L5 = last 5 games"])
            w.writerow(TEAM_COLS); w.writerows(blank_zeros(trows))
        with open(os.path.join(OUT, f"{lg['key']}_players.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(title_row(f"{lg['name']} players · updated {short} · % = share of the games they played", PLAYER_LEGEND_COLS, iso))
            w.writerow([nice(c) for c in PLAYER_COLS]); w.writerows(blank_zeros(prows))
        team_rows_all += [[lg["name"]] + r for r in blank_zeros(trows)]
        all_players += [r + [lg["name"], fold(r[0])] for r in blank_zeros(prows)]
        summary.append([lg["name"], len(matches), dt.date.fromisoformat(last_date).strftime("%d %b (%a)"), len(trows), len(prows),
                        sum(1 for r in prows if r[2].startswith(("Injured", "Doubtful"))),
                        sum(1 for r in prows if "uspended" in r[2]), sum(1 for r in prows if "Transferred" in r[2])])
    # Today tab: games kicking off in the next 24 hours
    start, end = dt.datetime.now(dt.timezone.utc), dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)
    def in_window(pk):
        try:
            t = dt.datetime.fromisoformat(pk["fixture"]["utc"].replace("Z", "+00:00"))
            return start - dt.timedelta(hours=2) <= t <= end
        except Exception:
            return False
    sel = [p for p in all_picks if in_window(p)]
    by_match = defaultdict(list)
    for p in sel:
        by_match[(p["fixture"]["utc"], p["league"], p["fixture"]["id"])].append(p)
    # how each market has really done in the Pick tracker so far
    graded = defaultdict(lambda: [0, 0])
    for e in load_log().values():
        if e.get("result") in ("Hit", "Miss"):
            graded[e["market"]][0] += 1; graded[e["market"]][1] += e["result"] == "Hit"
    real = lambda p: (100 * graded[p["market"]][1] / graded[p["market"]][0]) if graded[p["market"]][0] else None
    proven = lambda p: graded[p["market"]][0] >= PROVEN_MIN_PICKS and real(p) >= PROVEN_MIN_RATE

    def pick_row(p):
        fx = p["fixture"]
        g = graded[p["market"]]
        track = f"Tracker: this market hits {round(real(p))}% ({g[0]} picks)" if g[0] >= PROVEN_MIN_PICKS else ""
        extra = []
        if p.get("pid") is not None:
            extra.append(f"{p['games']} apps ({p['nstarts']} starts)")
            if p.get("starter"): extra.append(f"Regular starter: {p['starts']}% when starting")
            ko = dt.datetime.fromisoformat(fx["utc"].replace("Z", "+00:00"))
            for u, comp, tid, tname, was_start in started.get(p["pid"], []):
                t = dt.datetime.fromisoformat(u.replace("Z", "+00:00"))
                if was_start and comp != p["league"] and tname == p["team"] and dt.timedelta(0) < ko - t <= dt.timedelta(days=4):
                    extra.append(f"Started {comp} game {(ko - t).days or 1} day{'s' if (ko - t).days > 1 else ''} before: rotation risk")
        note = "; ".join(x for x in [p["status"], f"Small sample ({p['games']} games)" if p["games"] < SMALL else ""] + extra + [track] if x)
        return [p["who"], nice(p["market"]), p["true"], p["season"], p["l5"], p["starts"] if p.get("pid") is not None else "–", p["games"],
                uk_time(fx["utc"]), f"{fx['home']['name']} v {fx['away']['name']}", p["league"], p["team"], opp_note(p), note]

    def section(ps, cap, top=False):
        """Kick-off order, best picks first within each match, no repeats, at most `cap` per match."""
        rows = []
        for key in sorted(by_match):
            seen, n = set(), 0
            for p in sorted([p for p in ps if (p["fixture"]["utc"], p["league"], p["fixture"]["id"]) == key],
                            key=lambda p: (-p["true"], -(real(p) or 0) if top else 0, -p["season"], p["who"])):
                k = (p["who"], p["market"])
                if k in seen or n >= cap: continue
                seen.add(k); n += 1; rows.append(pick_row(p))
        return rows

    full = lambda p: p["season"] == 100
    players = [p for p in sel if p.get("pid") is not None]
    teams = [p for p in sel if p.get("pid") is None]
    good = lambda p: not full(p) and proven(p)
    today = [(f"PLAYER PICKS: 100% this season, true rate {PICK_MIN}%+", section([p for p in players if full(p)], 999)),
             (f"PLAYER TOP PICKS: best {TOP_PLAYER_PER_MATCH} per match by true rate (markets the tracker shows hitting {PROVEN_MIN_RATE}%+)",
              section([p for p in players if good(p)], TOP_PLAYER_PER_MATCH, top=True)),
             (f"TEAM PICKS: 100% this season, true rate {PICK_MIN}%+", section([p for p in teams if full(p)], 999)),
             (f"TEAM TOP PICKS: best {TOP_TEAM_PER_MATCH} per match by true rate (markets the tracker shows hitting {PROVEN_MIN_RATE}%+)",
              section([p for p in teams if good(p)], TOP_TEAM_PER_MATCH, top=True))]
    every = [(today[0][0], today[0][1]),
             (f"PLAYER PICKS: true rate {PICK_MIN}%+ (every one)", section([p for p in players if not full(p)], 9999)),
             (today[2][0], today[2][1]),
             (f"TEAM PICKS: true rate {PICK_MIN}%+ (every one)", section([p for p in teams if not full(p)], 9999))]
    tot = [sum(v[0] for v in graded.values()), sum(v[1] for v in graded.values())]
    track_line = f" · Pick tracker: past picks hit {round(100 * tot[1] / tot[0])}% ({tot[0]:,} graded)" if tot[0] else ""

    def write_picks(fn, sections, intro):
        rows = []
        for title, rs in sections:
            rows += [[]] if rows else []
            rows.append(["", f"{title}  ({len(rs)})"])   # column A empty so the colour rules skip title rows
            rows += rs or [["", "None in the next 24 hours"]]
        with open(os.path.join(OUT, fn), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(title_row(intro + track_line, 6, iso)); w.writerow(TODAY_COLS); w.writerows(rows)
        return rows

    out_rows = write_picks("TODAY.csv", today, f"Next 24 hours · updated {short} · True % = hit rate adjusted for small samples, the best guide in testing")
    write_picks("ALL_PICKS.csv", every, f"Next 24 hours · updated {short} · every pick with a true rate of {PICK_MIN}%+")
    # phone view: the Today short list in 3 columns that fit a phone screen
    mob = []
    for title, rs in today:
        mob += [[]] if mob else []
        short_title = ("PLAYER" if title.startswith("PLAYER") else "TEAM") + (" TOP PICKS" if "TOP" in title else " 100% PICKS")
        mob.append(["", f"{short_title}  ({len(rs)})"])
        for r in rs:
            ko = r[7].split(" · ")
            mob.append([f"{r[0].replace(' (team)', '')} · {r[1]}", r[2], f"{ko[-1]} {ko[0][:3]} · {r[8]}"])
        if not rs: mob.append(["", "None in the next 24 hours"])
    with open(os.path.join(OUT, "MOBILE.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(title_row(f"Today · updated {short}{track_line}", 0, iso)); w.writerow(["Pick", "True %", "Game"]); w.writerows(mob)
    with open(os.path.join(OUT, "TEAMS.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(title_row(f"All teams · updated {short} · use the filter on League to pick a competition", 6, iso))
        w.writerow(["League"] + [nice(c) for c in TEAM_COLS]); w.writerows(team_rows_all)
    with open(os.path.join(OUT, "ALL_players.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([nice(c) for c in PLAYER_COLS] + ["League", "Search name"])
        w.writerows(sorted(all_players, key=lambda r: r[0]))
    track_picks(sel, match_by_id, stamp)
    with open(os.path.join(OUT, "INDEX.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"Updated {stamp}", iso])
        w.writerow(["League", "Matches loaded", "Latest match", "Teams", "Players", "Injured/doubtful", "Suspended", "Transferred"])
        w.writerows(summary)
    print("\n".join(str(s) for s in summary)); print("today rows", len(out_rows))


if __name__ == "__main__":
    main()
