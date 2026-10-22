"""Pull this season's finished matches, availability and transfers from FotMob (+ goal kicks from ESPN).

Everything is cached in data/ so each daily run only fetches what's new.
"""
import json, os, re, sys, time, unicodedata, datetime as dt
import requests
from config import LEAGUES

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "en-GB,en;q=0.9"}
S = requests.Session(); S.headers.update(UA)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.append(s)


def get(url, tries=3, delay=0.6, as_json=False):
    for i in range(tries):
        try:
            r = S.get(url, timeout=40)
            time.sleep(delay)
            if r.status_code == 200:
                return r.json() if as_json else r.text
            log("HTTP", r.status_code, url)
        except Exception as e:
            log("ERR", url, e)
        time.sleep(3 * (i + 1))
    return None


def page_props(html):
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html or "", re.S)
    return json.loads(m.group(1))["props"]["pageProps"] if m else None


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    stop = {"fc", "afc", "cf", "sc", "ac", "cd", "sl", "sk", "jk", "fk", "as", "ss", "us", "ud", "rc", "rcd", "club",
            "de", "the", "and", "hove", "albion", "united", "utd", "city", "town", "calcio", "1", "04", "05", "1899", "1846", "1907"}
    return " ".join(w for w in s.split() if w not in stop) or s.strip()


def jload(p, default=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return default


def jsave(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: json.dump(o, f, ensure_ascii=False, separators=(",", ":"))


# ---------------- FotMob league data ----------------

def find_tables(o):
    """Return the 'all' standings rows (list of team dicts) wherever they sit in the page."""
    out = []
    def walk(x):
        if isinstance(x, dict):
            if "all" in x and isinstance(x["all"], list) and x["all"] and isinstance(x["all"][0], dict) and "pts" in x["all"][0]:
                out.append(x["all"]); return
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(o)
    return out


def league_table(lg):
    pp = page_props(get(f"https://www.fotmob.com/leagues/{lg['fm']}/overview/{lg['slug']}"))
    rows = []
    for t in find_tables(pp.get("table") if pp else None):
        rows.extend(t)
    seen, res = set(), []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"]); res.append({"id": int(r["id"]), "name": r["name"], "pos": r.get("idx"), "pts": r.get("pts"), "played": r.get("played")})
    return res


def league_fixtures(lg):
    pp = page_props(get(f"https://www.fotmob.com/leagues/{lg['fm']}/fixtures/{lg['slug']}"))
    fx = (pp or {}).get("fixtures") or {}
    am = fx.get("allMatches") or []
    return am


def scope_teams(lg, table):
    mode = lg["mode"]
    if mode == "all":
        return None
    if mode == "table":
        return {t["id"]: t["name"] for t in table}
    if mode == "top5":
        p = os.path.join(DATA, "locked_teams.json"); locked = jload(p, {})
        if lg["key"] not in locked:
            top = sorted(table, key=lambda t: t["pos"] or 99)[:5]
            locked[lg["key"]] = {"locked_on": dt.date.today().isoformat(), "teams": {str(t["id"]): t["name"] for t in top}}
            jsave(p, locked); log("LOCKED top5", lg["key"], [t["name"] for t in top])
        return {int(k): v for k, v in locked[lg["key"]]["teams"].items()}
    # explicit list of clubs
    res = {}
    for want in mode:
        w = norm(want)
        hit = [t for t in table if w in norm(t["name"]) or norm(t["name"]) in w]
        if hit: res[hit[0]["id"]] = hit[0]["name"]
        else: log("WARN club not found", lg["key"], want)
    return res


# ---------------- Match extraction ----------------

def num(v):
    if v is None: return None
    if isinstance(v, (int, float)): return v
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else None


def extract_match(pp, lg_key):
    gen, hdr, c = pp["general"], pp["header"], pp["content"]
    teams = hdr["teams"]
    home, away = teams[0], teams[1]
    m = {"id": int(gen["matchId"]), "league": lg_key, "date": hdr["status"]["utcTime"][:10],
         "utc": hdr["status"]["utcTime"], "round": gen.get("leagueRoundName"),
         "home": {"id": int(home["id"]), "name": home["name"], "score": home.get("score")},
         "away": {"id": int(away["id"]), "name": away["name"], "score": away.get("score")}}
    # half-time score
    ev = (((c.get("matchFacts") or {}).get("events") or {}).get("events")) or []
    ht = [e for e in ev if e.get("type") == "Half" and e.get("halfStrShort") == "HT"]
    m["ht"] = [ht[0]["homeScore"], ht[0]["awayScore"]] if ht else None
    # team stats
    ts = {}
    try:
        for g in c["stats"]["Periods"]["All"]["stats"]:
            for s in g.get("stats", []):
                v = s.get("stats")
                if isinstance(v, list) and len(v) == 2 and s.get("title") and s["title"] not in ts:
                    a, b = num(v[0]), num(v[1])
                    if a is not None or b is not None: ts[s["title"]] = [a, b]
    except Exception as e:
        log("WARN no team stats", m["id"], e)
    m["team_stats"] = ts
    # cards per player
    cards = {}
    for e in ev:
        if e.get("type") == "Card":
            pid = (e.get("player") or {}).get("id") or e.get("playerId")
            if pid is None: continue
            k = cards.setdefault(int(pid), {"yc": 0, "rc": 0})
            card = (e.get("card") or "").lower()
            if card == "yellow": k["yc"] += 1
            elif card in ("red",): k["rc"] += 1
            elif "yellowred" in card or "second" in card: k["yc"] += 1; k["rc"] += 1
            else: k["yc"] += 1
    # starters
    starters = set()
    lu = c.get("lineup") or {}
    for side in ("homeTeam", "awayTeam"):
        for p in (lu.get(side) or {}).get("starters") or []:
            starters.add(int(p["id"]))
    # shots
    shots = {}
    for s in ((c.get("shotmap") or {}).get("shots") or []):
        if s.get("isOwnGoal"): continue
        pid = int(s["playerId"]); d = shots.setdefault(pid, {"sh": 0, "sot": 0, "hsot": 0, "osot": 0, "hsh": 0, "osh": 0})
        on = bool(s.get("isOnTarget")) and not s.get("isBlocked")
        head = s.get("shotType") == "Header"; outside = s.get("isFromInsideBox") is False
        d["sh"] += 1; d["sot"] += on; d["hsh"] += head; d["osh"] += outside
        d["hsot"] += on and head; d["osot"] += on and outside
    # players
    players = []
    for p in (c.get("playerStats") or {}).values():
        if not p.get("stats"): continue
        st = {}
        for g in p["stats"]:
            for title, v in (g.get("stats") or {}).items():
                st.setdefault(title, (v.get("stat") or {}).get("value"))
        mins = num(st.get("Minutes played")) or 0
        if mins <= 0: continue
        pid = int(p["id"]); sh = shots.get(pid, {}); cd = cards.get(pid, {})
        players.append({
            "id": pid, "name": p["name"], "team": int(p["teamId"]), "teamName": p.get("teamName"),
            "gk": bool(p.get("isGoalkeeper")), "start": pid in starters, "min": mins,
            "g": num(st.get("Goals")) or 0, "a": num(st.get("Assists")) or 0,
            "sh": sh.get("sh", 0), "sot": sh.get("sot", 0), "hsot": sh.get("hsot", 0), "osot": sh.get("osot", 0),
            "hsh": sh.get("hsh", 0), "osh": sh.get("osh", 0),
            "fc": num(st.get("Fouls committed")) or 0, "fw": num(st.get("Was fouled")) or 0,
            "tk": num(st.get("Tackles")) or 0, "sv": num(st.get("Saves")) or 0,
            "yc": cd.get("yc", 0), "rc": cd.get("rc", 0)})
    m["players"] = players
    return m


# ---------------- ESPN goal kicks ----------------
ESPN_SB = {}


def espn_day(slug, day):
    k = (slug, day)
    if k not in ESPN_SB:
        j = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={day.replace('-', '')}", as_json=True, delay=0.3)
        evs = []
        for e in (j or {}).get("events", []):
            comp = e["competitions"][0]; cs = comp["competitors"]
            h = [x for x in cs if x["homeAway"] == "home"][0]; a = [x for x in cs if x["homeAway"] == "away"][0]
            evs.append({"id": e["id"], "h": h["team"]["displayName"], "a": a["team"]["displayName"], "hid": h["id"], "aid": a["id"]})
        ESPN_SB[k] = evs
    return ESPN_SB[k]


def sim(a, b):
    A, B = set(norm(a).split()), set(norm(b).split())
    if not A or not B: return 0
    j = len(A & B) / len(A | B)
    na, nb = norm(a).replace(" ", ""), norm(b).replace(" ", "")
    if na and nb and (na in nb or nb in na): j = max(j, 0.8)
    return j


def espn_supplement(m, slug):
    d0 = dt.date.fromisoformat(m["date"])
    best = None
    for d in (d0, d0 - dt.timedelta(days=1), d0 + dt.timedelta(days=1)):
        for e in espn_day(slug, d.isoformat()):
            sc = sim(m["home"]["name"], e["h"]) + sim(m["away"]["name"], e["a"])
            if best is None or sc > best[0]: best = (sc, e)
        if best and best[0] >= 1.2: break
    if not best or best[0] < 0.9:
        return {"miss": 1}
    e = best[1]; res = {"espn_id": e["id"]}
    for side, tid in (("h", e["hid"]), ("a", e["aid"])):
        j = get(f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/{slug}/events/{e['id']}/competitions/{e['id']}/competitors/{tid}/statistics", as_json=True, delay=0.2)
        vals = {}
        for cat in ((j or {}).get("splits") or {}).get("categories", []):
            for s in cat.get("stats", []):
                vals.setdefault(s["name"], s.get("value"))
        res[side] = {k: vals.get(k) for k in ("goalKicks", "totalThrows", "wonCorners", "foulsSuffered", "fkFoulLost")}
    return res


# ---------------- Availability ----------------

def team_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip("-")


def squad_injuries(team_id, team_name):
    pp = page_props(get(f"https://www.fotmob.com/teams/{team_id}/squad/{team_slug(team_name)}"))
    out = {}
    if not pp: return out
    t = (pp.get("fallback") or {}).get(f"team-{team_id}") or {}
    groups = ((t.get("squad") or {}).get("squad")) or []
    for g in groups:
        for mbr in g.get("members", []):
            if mbr.get("injured") or mbr.get("injury"):
                inj = mbr.get("injury") or {}
                out[int(mbr["id"])] = {"name": mbr.get("name"), "type": "injury", "ret": inj.get("expectedReturn")}
    return out


def next_match_unavailable(match_url):
    pp = page_props(get("https://www.fotmob.com" + match_url))
    out, raw = {}, []
    if not pp: return out, raw
    lu = (pp.get("content") or {}).get("lineup") or {}
    for side in ("homeTeam", "awayTeam"):
        for u in (lu.get(side) or {}).get("unavailable") or []:
            raw.append(u)
            un = u.get("unavailability") or {}
            t = str(un.get("type", "") if isinstance(un, dict) else "").lower()
            typ = "suspension" if ("susp" in t or "card" in t) else ("injury" if "injur" in t else (t or "unavailable"))
            ret = un.get("expectedReturn") if isinstance(un, dict) else None
            out[int(u["id"])] = {"name": u.get("name"), "type": typ, "ret": ret}
    return out, raw


# ---------------- Main ----------------

def run(keys):
    status = jload(os.path.join(DATA, "status.json"), {})
    for lg in LEAGUES:
        if keys and lg["key"] not in keys: continue
        t0 = time.time(); log("=====", lg["key"])
        table = league_table(lg)
        if not table: log("WARN no table", lg["key"])
        scope = scope_teams(lg, table)
        fixtures = league_fixtures(lg)
        log("fixtures", len(fixtures), "table", len(table), "scope", None if scope is None else list(scope.values()))
        mdir = os.path.join(DATA, "matches", lg["key"])
        new = 0
        for f in fixtures:
            st = f.get("status") or {}
            if not st.get("finished") or st.get("cancelled"): continue
            h, a = int(f["home"]["id"]), int(f["away"]["id"])
            if scope is not None:
                if lg["mode"] == "table":
                    if h not in scope or a not in scope: continue
                elif h not in scope and a not in scope: continue
            p = os.path.join(mdir, f"{f['id']}.json")
            if os.path.exists(p): continue
            pp = page_props(get("https://www.fotmob.com" + f["pageUrl"]))
            if not pp: log("WARN match page failed", f["pageUrl"]); continue
            try:
                m = extract_match(pp, lg["key"])
            except Exception as e:
                log("WARN extract failed", f["pageUrl"], repr(e)); continue
            if not m["players"]:
                log("WARN no player stats yet", f["pageUrl"]); continue
            m["espn"] = espn_supplement(m, lg["espn"])
            jsave(p, m); new += 1
        # retry ESPN for earlier misses (max 3 tries)
        for fn in os.listdir(mdir) if os.path.isdir(mdir) else []:
            p = os.path.join(mdir, fn); m = jload(p)
            if m and m.get("espn", {}).get("miss") and m["espn"]["miss"] < 3:
                r = espn_supplement(m, lg["espn"])
                if r.get("miss"): r["miss"] = m["espn"]["miss"] + 1
                m["espn"] = r; jsave(p, m)
        # availability: next fixture per scope team + squad pages
        avail, raw_un = {}, []
        teams_needed = set(scope) if scope is not None else {t["id"] for t in table}
        done_next = set()
        for f in fixtures:
            st = f.get("status") or {}
            if st.get("finished") or st.get("cancelled") or st.get("started"): continue
            h, a = int(f["home"]["id"]), int(f["away"]["id"])
            if (h in teams_needed and h not in done_next) or (a in teams_needed and a not in done_next):
                u, raw = next_match_unavailable(f["pageUrl"]); avail.update(u); raw_un.extend(raw)
                done_next.update({h, a})
            if teams_needed <= done_next: break
        names = {t["id"]: t["name"] for t in table}
        for tid in teams_needed:
            for pid, v in squad_injuries(tid, names.get(tid, str(tid))).items():
                avail.setdefault(pid, v)
        jsave(os.path.join(DATA, "availability", f"{lg['key']}.json"),
              {"updated": dt.datetime.utcnow().isoformat(timespec="minutes") + "Z", "players": {str(k): v for k, v in avail.items()}})
        jsave(os.path.join(DATA, "debug", f"unavailable_{lg['key']}.json"), raw_un[:50])
        jsave(os.path.join(DATA, "tables", f"{lg['key']}.json"), table)
        status[lg["key"]] = {"new_matches": new, "cached": len(os.listdir(mdir)) if os.path.isdir(mdir) else 0,
                             "run_seconds": round(time.time() - t0), "at": dt.datetime.utcnow().isoformat(timespec="minutes") + "Z"}
        log(lg["key"], status[lg["key"]])
        jsave(os.path.join(DATA, "status.json"), status)
    os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
    with open(os.path.join(DATA, "logs", ("_".join(keys) or "all") + ".txt"), "w") as f: f.write("\n".join(LOG[-3000:]))


if __name__ == "__main__":
    run(sys.argv[1:])
