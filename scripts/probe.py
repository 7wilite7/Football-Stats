import json, os, requests
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
os.makedirs("probe",exist_ok=True)
def get(u,**k):
    try:
        r=requests.get(u,headers=UA,timeout=30,**k); return r.status_code,r.text
    except Exception as e: return -1,str(e)
rep={}
# ESPN league slugs
for lg in ["eng.1","esp.1","ita.1","ger.1","fra.1","eng.2","usa.1","uefa.champions","uefa.europa","ned.1","sau.1","por.1","sco.1","tur.1"]:
    c,t=get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates=20260801-20261021&limit=1000")
    try:
        j=json.loads(t); ev=j.get("events",[])
        done=[e for e in ev if e["status"]["type"].get("completed")]
        rep[lg]={"code":c,"events":len(ev),"completed":len(done),"first":ev[0]["date"] if ev else None,"sample":done[-1]["id"] if done else None}
    except Exception as e: rep[lg]={"code":c,"err":str(e)[:200]}
open("probe/espn_leagues.json","w").write(json.dumps(rep,indent=1))
# sample summary
c,t=get("https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/summary?event=401879272")
open("probe/summary.json","w").write(t)
c,t=get("https://site.api.espn.com/apis/v2/sports/soccer/sau.1/standings"); open("probe/sau_standings.json","w").write(t)
c,t=get("https://site.api.espn.com/apis/v2/sports/soccer/ned.1/standings"); open("probe/ned_standings.json","w").write(t)
c,t=get("https://www.fotmob.com/teams/8456/squad/manchester-city"); open("probe/fotmob_squad.html","w").write(t); rep["fotmob_squad"]=c
c,t=get("https://www.fotmob.com/leagues/47/overview/premier-league"); open("probe/fotmob_league.html","w").write(t); rep["fotmob_league"]=c
open("probe/espn_leagues.json","w").write(json.dumps(rep,indent=1))
