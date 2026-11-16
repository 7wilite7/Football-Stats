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

# Internationals: every national-team competition of the season, combined into one "Internationals" tab.
# Competitions with no games yet (later in the season) are simply skipped until they start.
INTL_PARTS = [
    dict(name="Nations League A", fm=9806, slug="nations-league-a", espn="uefa.nations"),
    dict(name="Nations League B", fm=9807, slug="nations-league-b", espn="uefa.nations"),
    dict(name="Nations League C", fm=9808, slug="nations-league-c", espn="uefa.nations"),
    dict(name="Nations League D", fm=9809, slug="nations-league-d", espn="uefa.nations"),
    dict(name="CONCACAF Nations League", fm=9821, slug="concacaf-nations-league", espn="concacaf.nations.league"),
    dict(name="AFCON qualifiers", fm=10608, slug="africa-cup-of-nations-qualification", espn="caf.nations_qual"),
    dict(name="EURO qualifiers", fm=10607, slug="euro-qualification", espn="uefa.euroq"),
    dict(name="Africa Cup of Nations", fm=289, slug="africa-cup-of-nations", espn="caf.nations"),
    dict(name="Asian Cup", fm=290, slug="asian-cup", espn="afc.asian.cup"),
    dict(name="Gold Cup", fm=298, slug="concacaf-gold-cup", espn="concacaf.gold"),
    dict(name="Friendlies", fm=114, slug="friendlies", espn="fifa.friendly"),
]
INTL_SINCE = "2026-08-01"   # 2026-27 season starts after the World Cup
LEAGUES.append(dict(key="INTL", name="Internationals", parts=INTL_PARTS, mode="all", yc_ban=2, espn=None))

MIN_AVG_MINUTES = 45
