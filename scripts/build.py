"""Turn cached matches into CSVs for the Google Sheet.

Per league: <KEY>_teams.csv (team markets, home/away splits, last-5, next opponent)
            <KEY>_players.csv (player hit rates incl. last-5, next match)
Plus TODAY.csv (best 80%+ markets for games in the next 24 hours) and INDEX.csv.
"""
import csv, json, os, datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo
from config import LEAGUES, MIN_AVG_MINUTES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, OUT = os.path.join(ROOT, "data"), os.path.join(ROOT, "out")
UK = ZoneInfo("Europe/London")
MIN_APPS = 3          # players need this many league appearances to be listed
PICK_MIN = 80         # Today tab: season and last-5 hit rate both at least this
PICKS_PER_MATCH = 30


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
        info[tid] = {"vals": vals, "l5": l5, "n": len(R), "ctx": ctx}
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
               [c for c, _ in PLAYER_STATS] + [c for c, _ in GK_STATS] + [f"L5 {k}" for k in PLAYER_L5_KEYS] +
               [f"Starts: {k}" for k in STARTS_KEYS] +
               ["Last 5 SOT", "Last 5 shots", "Last 5 fouls", "Last 5 tackles"])
SMALL = 6   # fewer games than this = small sample
# market -> which opponent number gives useful context in the Today tab
OPP_FOR = {"Goal": ("goals", "goals conceded"), "Score": ("goals", "goals conceded"), "Shots": ("shots", "shots conceded"),
           "SOT": ("sot", "SOT conceded"), "Fouls": ("fouls_won", "fouls won"), "Fouled": ("fouls", "fouls committed"),
           "Booked": ("fouls_won", "fouls won"), "Saves": ("sot_for", "shots on target")}


def player_rows(matches, scope, lg, all_last_team, avail, team_names, team_info):
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
        rows.append([last_p["name"], team_names.get(team, last_p.get("teamName")), status, nxt, "GK" if is_gk else "",
                     n, sum(p["start"] for p in Pl), round(mins / n)] +
                    [season[c] for c, _ in PLAYER_STATS] + [gk[c] for c, _ in GK_STATS] + [l5[k] for k in PLAYER_L5_KEYS] +
                    [st[k] for k in STARTS_KEYS] +
                    [" ".join(str(int(p[k])) for p in last5) for k in ("sot", "sh", "fc", "tk")])
        # Today-tab candidates: season and last-5 both strong, player available
        if ctx and not any(w in status for w in ("Injured", "uspended", "Doubtful", "Unavailable")):
            for k in PLAYER_L5_KEYS:
                sv = gk.get(k, season.get(k)); lv = l5[k]
                if isinstance(sv, int) and isinstance(lv, int) and sv >= PICK_MIN and lv >= PICK_MIN:
                    picks.append({"fixture": ctx["fixture"], "who": last_p["name"], "team": team_names.get(team, ""),
                                  "market": k.replace(" %", ""), "key": k, "season": sv, "l5": lv, "games": n,
                                  "starts": st.get(k, ""), "nstarts": len(St), "pid": pid,
                                  "opp": ctx, "status": status})
    rows.sort(key=lambda r: (r[1] or "", -r[7]))
    return rows, picks


def team_picks(info, names):
    picks = []
    for tid, d in info.items():
        ctx = d["ctx"]
        if not ctx or d["n"] < MIN_APPS: continue
        for k in TEAM_L5_KEYS:
            sv, lv = d["vals"].get(k), d["l5"].get(k)
            if isinstance(sv, int) and isinstance(lv, int) and sv >= PICK_MIN and lv >= PICK_MIN:
                picks.append({"fixture": ctx["fixture"], "who": names[tid] + " (team)", "team": names[tid],
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


TODAY_COLS = ["Kick-off (UK)", "Competition", "Match", "Pick", "Team", "Market", "Season %", "Last 5 %", "When starting %",
              "Games", "Opponent context", "Note"]


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


def track_picks(sel, match_by_id, stamp):
    """Log Today picks before kick-off (first sighting is kept) and grade them once the match is in."""
    path = os.path.join(DATA, "picks", "log.json")
    log = jload(path, {}) or {}
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
                  "who": p["who"], "market": p["market"], "key": p["key"], "season": p["season"], "l5": p["l5"],
                  "games": p["games"], "pid": p.get("pid"), "tid": p.get("tid"), "result": ""}
    for e in log.values():
        if not e["result"] and e["fixture"] in match_by_id:
            try: e["result"] = grade(e, match_by_id[e["fixture"]])
            except Exception as ex: print("grade failed", e["who"], e["market"], ex)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: json.dump(log, f, indent=0, sort_keys=True)
    graded = [e for e in log.values() if e["result"] in ("Hit", "Miss")]
    by = defaultdict(list)
    for e in graded: by[e["market"]].append(e)
    summ = [["All picks", len(graded), sum(e["result"] == "Hit" for e in graded),
             pct(sum(e["result"] == "Hit" for e in graded), len(graded)),
             round(sum(e["season"] for e in graded) / len(graded)) if graded else ""]]
    for mk, es in sorted(by.items(), key=lambda x: -len(x[1])):
        h = sum(e["result"] == "Hit" for e in es)
        summ.append([mk, len(es), h, pct(h, len(es)), round(sum(e["season"] for e in es) / len(es))])
    rows = sorted(log.values(), key=lambda e: e["utc"], reverse=True)[:1500]
    with open(os.path.join(OUT, "TRACKER.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"How the Today picks actually did (logged before kick-off, graded after the match). Updated {stamp}. "
                    "'Sheet said %' = average season hit rate shown when the pick was made"])
        w.writerow(["Market", "Picks graded", "Hits", "Actual hit rate %", "Sheet said %"])
        w.writerows(summ)
        w.writerow([]); w.writerow(["Every logged pick, newest first ('Did not play' and pending picks don't count)"])
        w.writerow(["Player", "Market", "Match", "Kick-off (UK)", "Competition", "Season %", "Last 5 %", "Result"])
        w.writerows([[e["who"], e["market"], e["match"], uk_time(e["utc"]), e["league"], e["season"], e["l5"],
                      e["result"] or "Pending"] for e in rows] or [["No picks logged yet"]])


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
    moves = transfers_index()
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
        avail = (jload(os.path.join(DATA, "availability", f"{lg['key']}.json"), {}) or {}).get("players", {})
        recs, rnames = team_records(matches)
        names.update({k: v for k, v in rnames.items() if k not in names})
        trows, info = team_rows(recs, names, scope, fixtures)
        prows, picks = player_rows(matches, scope, lg, moves, avail, names, info)
        for pk in picks + team_picks(info, names):
            pk["league"] = lg["name"]; all_picks.append(pk)
        last_date = max(m["date"] for m in matches)
        with open(os.path.join(OUT, f"{lg['key']}_teams.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([f"{lg['name']} 2026-27: team stats from {len(matches)} league games (latest {last_date}). Updated {stamp}. % = share of games. L5 = last 5 games"])
            w.writerow(TEAM_COLS); w.writerows(blank_zeros(trows))
        with open(os.path.join(OUT, f"{lg['key']}_players.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([f"Player hit rates: {MIN_AVG_MINUTES}+ mins a game and at least {MIN_APPS} appearances (2 while a cup has played 3 or fewer). % = share of their league games. L5 = last 5 games"])
            w.writerow(PLAYER_COLS); w.writerows(blank_zeros(prows))
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
    out_rows = []
    for key in sorted(by_match):
        ps = by_match[key]
        # one row per pick, best first; avoid listing the same match twice from both teams' sides
        seen, uniq = set(), []
        for p in sorted(ps, key=lambda p: (-p["season"], -p["l5"], p["who"])):
            k = (p["who"], p["market"])
            if k in seen: continue
            seen.add(k); uniq.append(p)
        for p in uniq[:PICKS_PER_MATCH]:
            fx = p["fixture"]
            note = "; ".join(x for x in (p["status"], f"Small sample ({p['games']} games)" if p["games"] < SMALL else "") if x)
            out_rows.append([uk_time(fx["utc"]), p["league"], f"{fx['home']['name']} v {fx['away']['name']}", p["who"], p["team"],
                             p["market"], p["season"], p["l5"], p["starts"], p["games"], opp_note(p), note])
    with open(os.path.join(OUT, "TODAY.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"Games kicking off in the next 24 hours (from {stamp}): markets hitting {PICK_MIN}%+ this season AND in the last 5 games. "
                    f"Injured, doubtful and suspended players left out. Up to {PICKS_PER_MATCH} per match."])
        w.writerow(TODAY_COLS)
        w.writerows(out_rows if out_rows else [["No games with 80%+ markets in the next 24 hours"]])
    with open(os.path.join(OUT, "ALL_players.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(PLAYER_COLS + ["League", "Search name"])
        w.writerows(sorted(all_players, key=lambda r: r[0]))
    track_picks(sel, match_by_id, stamp)
    with open(os.path.join(OUT, "INDEX.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"Updated {stamp}"])
        w.writerow(["League", "Matches loaded", "Latest match", "Teams", "Players", "Injured/doubtful", "Suspended", "Transferred"])
        w.writerows(summary)
    print("\n".join(str(s) for s in summary)); print("today picks", len(out_rows))


if __name__ == "__main__":
    main()
