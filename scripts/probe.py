"""One-off: find FotMob's international competitions with 2026-27 matches (probe by id)."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get, page_props
def walk_names(o, out):
    if isinstance(o, dict):
        if "international" in o and isinstance(o["international"], list):
            for g in o["international"]:
                for lg in (g.get("leagues") or []): out.append((lg.get("id"), lg.get("name"), lg.get("pageUrl")))
        for v in o.values(): walk_names(v, out)
    elif isinstance(o, list):
        for v in o: walk_names(v, out)
found = []
for url in ("https://www.fotmob.com/", "https://www.fotmob.com/leagues"):
    pp = page_props(get(url)); walk_names(pp, found)
print("FOUND IN PAGES:", len(found))
for f in found: print("  ", f)
ids = sorted({f[0] for f in found if f[0]} | {77, 50, 44, 289, 290, 298, 114, 9806, 9807, 9808, 9809, 9821, 10195, 10196, 10197,
            10198, 10199, 10200, 10607, 10608, 10609, 10610, 10611, 10216, 10229, 10230, 489, 525, 526, 10046, 10171, 10840, 9469, 8971})
for lid in ids:
    pp = page_props(get(f"https://www.fotmob.com/leagues/{lid}/fixtures/x"))
    if not pp: print(f"PROBE {lid} | no page"); continue
    d = pp.get("details") or {}
    am = ((pp.get("fixtures") or {}).get("allMatches")) or []
    since = [m for m in am if (m.get("status") or {}).get("utcTime", "") >= "2026-08-01"]
    fin = [m for m in since if (m.get("status") or {}).get("finished")]
    teams = {m["home"]["name"] for m in since} | {m["away"]["name"] for m in since}
    print(f"PROBE {lid} | {d.get('name')} | season={d.get('selectedSeason') or d.get('latestSeason')} | country={d.get('country')} | since Aug26={len(since)} finished={len(fin)} teams={len(teams)} | {min((m['status']['utcTime'] for m in since), default='-')[:10]}..{max((m['status']['utcTime'] for m in since), default='-')[:10]}")
