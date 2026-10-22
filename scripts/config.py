# League set-up. mode:
#   "all"    -> every team in the league
#   "top5"   -> the top five on the day of first run, then locked forever (data/locked_teams.json)
#   list     -> only these clubs (names as FotMob writes them, matched loosely)
#   "table"  -> every team in the competition's league phase (UCL / UEL, 36 teams)
LEAGUES = [
    # key, tab name, fotmob id, fotmob slug, espn slug, mode, booking-ban threshold
    dict(key="EPL", name="Premier League", fm=47, slug="premier-league", espn="eng.1", mode="all", yc_ban=5),
    dict(key="LALIGA", name="La Liga", fm=87, slug="laliga", espn="esp.1", mode="all", yc_ban=5),
    dict(key="SERIEA", name="Serie A", fm=55, slug="serie-a", espn="ita.1", mode="all", yc_ban=5),
    dict(key="BUNDESLIGA", name="Bundesliga", fm=54, slug="bundesliga", espn="ger.1", mode="all", yc_ban=5),
    dict(key="LIGUE1", name="Ligue 1", fm=53, slug="ligue-1", espn="fra.1", mode="all", yc_ban=5),
    dict(key="CHAMPIONSHIP", name="Championship", fm=48, slug="championship", espn="eng.2", mode="all", yc_ban=5),
    dict(key="MLS", name="MLS", fm=130, slug="mls", espn="usa.1", mode="all", yc_ban=5),
    dict(key="UCL", name="Champions League", fm=42, slug="champions-league", espn="uefa.champions", mode="table", yc_ban=3),
    dict(key="UEL", name="Europa League", fm=73, slug="europa-league", espn="uefa.europa", mode="table", yc_ban=3),
    dict(key="EREDIVISIE", name="Eredivisie (top 5)", fm=57, slug="eredivisie", espn="ned.1", mode="top5", yc_ban=5),
    dict(key="SAUDI", name="Saudi Pro League (top 5)", fm=536, slug="saudi-pro-league", espn="ksa.1", mode="top5", yc_ban=5),
    dict(key="PORTUGAL", name="Portugal (Porto, Sporting, Benfica)", fm=61, slug="liga-portugal", espn="por.1",
         mode=["Porto", "Sporting CP", "Benfica"], yc_ban=5),
    dict(key="SCOTLAND", name="Scotland (Rangers, Celtic, Hearts)", fm=64, slug="premiership", espn="sco.1",
         mode=["Rangers", "Celtic", "Heart of Midlothian"], yc_ban=5),
    dict(key="TURKEY", name="Turkey (Gala, Fener, Besiktas, Trabzon)", fm=71, slug="super-lig", espn="tur.1",
         mode=["Galatasaray", "Fenerbahce", "Besiktas", "Trabzonspor"], yc_ban=4),
]

MIN_AVG_MINUTES = 45
