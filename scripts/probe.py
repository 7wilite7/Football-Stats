"""One-off: list FotMob's international competitions and how many 2026-27 matches each has."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get, page_props
j = get("https://www.fotmob.com/api/allLeagues", as_json=True) or {}
cands = []
for sec in ("international",):
    for grp in j.get(sec) or []:
        for lg in grp.get("leagues") or []:
            cands.append((lg.get("id"), lg.get("name"), lg.get("pageUrl")))
print("INTERNATIONAL LEAGUES:", len(cands))
for c in cands: print("  ", c)
for lid, name, url in cands:
    slug = (url or "").rstrip("/").split("/")[-1]
    pp = page_props(get(f"https://www.fotmob.com/leagues/{lid}/fixtures/{slug}"))
    am = ((pp or {}).get("fixtures") or {}).get("allMatches") or []
    season = ((pp or {}).get("details") or {}).get("selectedSeason") or ((pp or {}).get("details") or {}).get("latestSeason")
    since = [m for m in am if (m.get("status") or {}).get("utcTime", "") >= "2026-08-01"]
    fin = [m for m in since if (m.get("status") or {}).get("finished")]
    teams = {m["home"]["name"] for m in since} | {m["away"]["name"] for m in since}
    print(f"PROBE {lid} | {name} | slug={slug} | season={season} | matches since Aug26={len(since)} finished={len(fin)} teams={len(teams)} | first={min((m['status']['utcTime'] for m in since), default='-')} last={max((m['status']['utcTime'] for m in since), default='-')}")
