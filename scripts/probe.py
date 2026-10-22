import json, os, re, requests
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
os.makedirs("probe",exist_ok=True)
def get(u):
    try:
        r=requests.get(u,headers=UA,timeout=30); return r.status_code,r.text
    except Exception as e: return -1,str(e)
rep={}
for lg in ["eng.1","ksa.1","sau.1"]:
    for rng in ["20261001-20261021","20261017","20261018"]:
        c,t=get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={rng}")
        try:
            ev=json.loads(t).get("events",[])
            rep[f"{lg} {rng}"]=[(e["id"],e["name"],e["status"]["type"]["name"]) for e in ev]
        except Exception as e: rep[f"{lg} {rng}"]=[c,t[:150]]
c,t=get("https://site.api.espn.com/apis/v2/sports/soccer/ksa.1/standings"); rep["ksa_standings"]=[c,t[:200]]
# fotmob fixtures
c,t=get("https://www.fotmob.com/leagues/47/fixtures/premier-league"); open("probe/fotmob_fixtures.html","w").write(t); rep["fm_fix"]=c
h=t; m=re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',h,re.S)
try:
    s=m.group(1); ids=re.findall(r'"pageUrl":"(/matches/[^"]+)"',s); rep["fm_match_urls"]=ids[:5]
    if ids:
        c2,t2=get("https://www.fotmob.com"+ids[0]); open("probe/fotmob_match.html","w").write(t2); rep["fm_match"]=c2
except Exception as e: rep["fm_err"]=str(e)
open("probe/report2.json","w").write(json.dumps(rep,indent=1))
