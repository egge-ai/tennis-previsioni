"""
Modello predittivo tennis v3 — dati TML (Tennismylife), ATP e WTA.
Aggiunge condizioni fisiche (infortuni/ritiri recenti, età), mentali (tie-break, set decisivi,
palle break, gioco in casa) e di gioco (indoor/outdoor, altitudine).

Cosa usa per ogni partita (tutto calcolato con i soli dati PRIMA del match):
  - Elo generale ed Elo per superficie (K decrescente, peso per livello torneo)
  - forma recente: quanto un giocatore sta battendo le attese nelle ultime partite
  - servizio + risposta: % punti vinti al servizio e in risposta (media mobile)
  - rientri: giorni dall'ultima partita
  - stanchezza: minuti giocati negli ultimi 3 giorni, partite negli ultimi 10
Una regressione logistica combina tutto (senza intercetta, quindi A-B e B-A sommano a 1).

  python tennis_model2.py --tml ./tml --tour atp --test-from 2026
  python tennis_model2.py --tml ./tml --tour wta --test-from 2026
"""
import argparse, glob, json, math, os, re
from collections import defaultdict, deque
import numpy as np
import pandas as pd

SURFACES = ["Hard", "Clay", "Grass"]
LEVEL_W = {"G": 1.1, "F": 1.05, "M": 1.0, "1000": 1.0, "O": 1.0, "500": 0.97, "250": 0.95, "A": 0.95,
           "D": 0.9, "C": 0.85, "Q": 0.8, "S": 0.75}
HOME = {  # torneo -> paese (codice IOC)
 "Australian Open":"AUS","Brisbane":"AUS","Adelaide":"AUS","Hobart":"AUS","Sydney":"AUS","Perth":"AUS",
 "Roland Garros":"FRA","Paris Masters":"FRA","Marseille":"FRA","Montpellier":"FRA","Lyon":"FRA","Metz":"FRA","Rouen":"FRA","Strasbourg":"FRA","Nice":"FRA","Paris Olympics":"FRA",
 "Wimbledon":"GBR","Queen's Club":"GBR","Eastbourne":"GBR","Nottingham":"GBR","Birmingham":"GBR","London":"GBR",
 "US Open":"USA","Indian Wells Masters":"USA","Indian Wells":"USA","Miami Masters":"USA","Miami":"USA","Cincinnati Masters":"USA","Cincinnati":"USA",
 "Washington":"USA","Winston-Salem":"USA","Charleston":"USA","Austin":"USA","Dallas":"USA","Delray Beach":"USA","Houston":"USA","Cleveland":"USA",
 "Memphis":"USA","Newport":"USA","Atlanta":"USA","San Diego":"USA","Atlanta":"USA","New York":"USA","San Jose":"USA",
 "Madrid Masters":"ESP","Madrid":"ESP","Barcelona":"ESP","Mallorca":"ESP","Marbella":"ESP","Valencia":"ESP",
 "Rome Masters":"ITA","Rome":"ITA","Palermo":"ITA","ATP Finals":"ITA","ATP Tour Finals":"ITA","Next Gen Finals":"ITA","Next Gen ATP Finals":"ITA","Parma":"ITA","Cagliari":"ITA",
 "Canada Masters":"CAN","Toronto":"CAN","Montreal":"CAN",
 "Monte Carlo Masters":"MON","Monte Carlo":"MON",
 "Beijing":"CHN","Shanghai":"CHN","Shanghai Masters":"CHN","Wuhan":"CHN","Guangzhou":"CHN","Chengdu":"CHN","Hangzhou":"CHN","Ningbo":"CHN","Jiujiang":"CHN","Zhuhai":"CHN","Shenzhen":"CHN","Zhengzhou":"CHN",
 "Tokyo":"JPN","Osaka":"JPN","Hong Kong":"HKG","Seoul":"KOR","Singapore":"SGP","Hua Hin":"THA","Hua Hin 2":"THA","Chennai":"IND","Pune":"IND",
 "Dubai":"UAE","Abu Dhabi":"UAE","Doha":"QAT","Riyadh Finals":"KSA","WTA Finals":"KSA","Almaty":"KAZ","Astana":"KAZ",
 "Stuttgart":"GER","Hamburg":"GER","Halle":"GER","Munich":"GER","Bad Homburg":"GER","Berlin":"GER",
 "'s-Hertogenbosch":"NED","Rosmalen":"NED","Rotterdam":"NED","Basel":"SUI","Gstaad":"SUI","Geneva":"SUI",
 "Vienna":"AUT","Kitzbuhel":"AUT","Linz":"AUT","Bastad":"SWE","Stockholm":"SWE","Umag":"CRO","Zagreb":"CRO",
 "Cluj-Napoca":"ROU","Iasi":"ROU","Bucharest":"ROU","Prague":"CZE","Prague Open":"CZE","Ostrava":"CZE",
 "Budapest":"HUN","Belgrade":"SRB","Athens":"GRE","Antwerp":"BEL","Brussels":"BEL","Estoril":"POR","Sofia":"BUL",
 "Rabat":"MAR","Marrakech":"MAR","Monastir":"TUN",
 "Acapulco":"MEX","Los Cabos":"MEX","Merida":"MEX","Monterrey":"MEX","Guadalajara":"MEX",
 "Buenos Aires":"ARG","Cordoba":"ARG","Santiago":"CHI","Rio de Janeiro":"BRA","Rio De Janeiro":"BRA","Sao Paulo":"BRA","Bogota":"COL","Quito":"ECU",
 "Auckland":"NZL"}
ALTITUDE = {"Bogota": 2.6, "Quito": 2.8, "Madrid Masters": 0.65, "Madrid": 0.65, "Gstaad": 1.05, "Kitzbuhel": 0.76,
            "Guadalajara": 1.55, "Monterrey": 0.54, "Johannesburg": 1.75, "Merida": 0.0, "Cordoba": 0.4, "Sofia": 0.55}
INDOOR = ["Paris Masters", "Rotterdam", "Basel", "Vienna", "ATP Finals", "ATP Tour Finals", "Next Gen", "Stockholm", "Antwerp",
          "Metz", "Linz", "Ostrava", "Marseille", "Montpellier", "Dallas", "Memphis", "Sofia", "Brussels", "Cluj", "Rouen",
          "Stuttgart", "St. Petersburg", "Moscow", "Belgrade", "WTA Finals", "Riyadh"]

TCOORD = {  # torneo -> (lat, lon) della città
 "Australian Open": (-37.82, 144.98), "Brisbane": (-27.47, 153.03), "Adelaide": (-34.93, 138.60), "Hobart": (-42.88, 147.33),
 "Sydney": (-33.87, 151.21), "Perth": (-31.95, 115.86), "Auckland": (-36.85, 174.76),
 "Roland Garros": (48.85, 2.25), "Lyon": (45.76, 4.84), "Strasbourg": (48.57, 7.75), "Nice": (43.70, 7.27), "Paris Olympics": (48.85, 2.25),
 "Wimbledon": (51.43, -0.21), "Queen's Club": (51.49, -0.21), "Eastbourne": (50.77, 0.28), "Nottingham": (52.95, -1.15), "Birmingham": (52.48, -1.90),
 "US Open": (40.75, -73.85), "Indian Wells Masters": (33.72, -116.31), "Indian Wells": (33.72, -116.31), "Miami Masters": (25.96, -80.24),
 "Miami": (25.96, -80.24), "Cincinnati Masters": (39.35, -84.27), "Cincinnati": (39.35, -84.27), "Washington": (38.96, -77.04),
 "Winston-Salem": (36.10, -80.24), "Charleston": (32.86, -79.91), "Austin": (30.27, -97.74), "Delray Beach": (26.46, -80.07),
 "Houston": (29.76, -95.37), "Cleveland": (41.50, -81.69), "Newport": (41.49, -71.31), "Atlanta": (33.75, -84.39), "San Diego": (32.72, -117.16),
 "Madrid Masters": (40.37, -3.69), "Madrid": (40.37, -3.69), "Barcelona": (41.39, 2.12), "Mallorca": (39.57, 2.65),
 "Rome Masters": (41.93, 12.46), "Rome": (41.93, 12.46), "Palermo": (38.12, 13.36), "Parma": (44.80, 10.33), "Cagliari": (39.22, 9.11),
 "Canada Masters": (45.53, -73.62), "Toronto": (43.77, -79.51), "Montreal": (45.53, -73.62), "Monte Carlo Masters": (43.75, 7.44), "Monte Carlo": (43.75, 7.44),
 "Beijing": (39.99, 116.39), "Shanghai": (31.04, 121.36), "Shanghai Masters": (31.04, 121.36), "Wuhan": (30.59, 114.31), "Guangzhou": (23.13, 113.26),
 "Chengdu": (30.57, 104.07), "Hangzhou": (30.27, 120.16), "Ningbo": (29.87, 121.54), "Jiujiang": (29.71, 116.00), "Zhuhai": (22.27, 113.58),
 "Shenzhen": (22.54, 114.06), "Zhengzhou": (34.75, 113.63), "Tokyo": (35.63, 139.79), "Osaka": (34.69, 135.50), "Hong Kong": (22.28, 114.17),
 "Seoul": (37.52, 127.12), "Singapore": (1.30, 103.87), "Hua Hin": (12.57, 99.96), "Hua Hin 2": (12.57, 99.96), "Chennai": (13.08, 80.27), "Pune": (18.52, 73.86),
 "Dubai": (25.24, 55.33), "Abu Dhabi": (24.45, 54.38), "Doha": (25.32, 51.53), "Almaty": (43.24, 76.89),
 "Stuttgart": (48.78, 9.18), "Hamburg": (53.58, 9.97), "Halle": (52.06, 8.36), "Munich": (48.14, 11.58), "Bad Homburg": (50.23, 8.62), "Berlin": (52.49, 13.27),
 "'s-Hertogenbosch": (51.70, 5.30), "Rosmalen": (51.70, 5.30), "Gstaad": (46.47, 7.28), "Geneva": (46.20, 6.14), "Kitzbuhel": (47.45, 12.39),
 "Bastad": (56.43, 12.85), "Umag": (45.43, 13.52), "Iasi": (47.16, 27.59), "Bucharest": (44.43, 26.10), "Prague": (50.08, 14.42), "Prague Open": (50.08, 14.42),
 "Budapest": (47.50, 19.04), "Belgrade": (44.79, 20.45), "Athens": (37.98, 23.73), "Estoril": (38.70, -9.40),
 "Rabat": (34.02, -6.83), "Marrakech": (31.63, -8.01), "Monastir": (35.78, 10.83),
 "Acapulco": (16.86, -99.88), "Los Cabos": (22.89, -109.91), "Merida": (20.97, -89.62), "Monterrey": (25.69, -100.32), "Guadalajara": (20.66, -103.35),
 "Buenos Aires": (-34.58, -58.40), "Cordoba": (-31.42, -64.18), "Santiago": (-33.45, -70.67), "Rio de Janeiro": (-22.98, -43.22),
 "Rio De Janeiro": (-22.98, -43.22), "Sao Paulo": (-23.55, -46.63), "Bogota": (4.71, -74.07), "Quito": (-0.18, -78.47),
}

ROUND_ORD = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3, "R128": 10, "R64": 11, "R32": 12, "R16": 13, "RR": 14,
             "QF": 15, "SF": 16, "BR": 17, "F": 18}


# ------------------------------------------------------------------ modello punto per punto
from functools import lru_cache

@lru_cache(maxsize=None)
def _game(p):
    q = 1 - p
    return p**4 * (1 + 4*q + 10*q*q) + 20 * p**3 * q**3 * p*p / (1 - 2*p*q)

@lru_cache(maxsize=None)
def _tb(pa, pb):
    # tie-break: A serve il primo punto, poi si alterna ogni 2 punti
    from functools import lru_cache as lc
    @lc(maxsize=None)
    def f(a, b):
        if a >= 7 and a - b >= 2: return 1.0
        if b >= 7 and b - a >= 2: return 0.0
        if a == b and a >= 6:      # parità ai vantaggi: forma chiusa sui 2 punti
            x = pa * (1 - pb); y = (1 - pa) * pb
            return x / (x + y) if x + y > 0 else 0.5
        n = a + b
        server_a = (n % 4 == 0) or (n % 4 == 3)
        p = pa if server_a else 1 - pb
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return f(0, 0)

@lru_cache(maxsize=None)
def _set(pa, pb):
    ga, gb = _game(pa), 1 - _game(pb)          # A vince il game: al servizio / in risposta
    from functools import lru_cache as lc
    @lc(maxsize=None)
    def f(a, b):
        if a >= 6 and a - b >= 2: return 1.0
        if b >= 6 and b - a >= 2: return 0.0
        if a == 7: return 1.0
        if b == 7: return 0.0
        if a == 6 and b == 6: return _tb(pa, pb)
        p = ga if (a + b) % 2 == 0 else gb
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return f(0, 0)

def markov_match(pa, pb, best_of=3):
    """probabilità che A vinca, dati i punti vinti al servizio di A (pa) e di B (pb)."""
    pa = min(max(round(pa, 3), 0.40), 0.90); pb = min(max(round(pb, 3), 0.40), 0.90)
    s = (_set(pa, pb) + (1 - _set(pb, pa))) / 2          # media: A serve per primo / B serve per primo
    need = 3 if best_of == 5 else 2
    from math import comb
    return sum(comb(need - 1 + k, k) * s**need * (1 - s)**k for k in range(need))


# ------------------------------------------------------------------ dati
def load(tml, tour, first_year=2010, weather=None):
    files = []
    years = range(first_year, 2100)
    if tour == "atp":
        for y in years:
            for f, lvl in [(f"{y}.csv", None), (f"{y}_challenger.csv", None), (f"atp_quali/{y}_atp_quali.csv", "Q")]:
                if os.path.exists(os.path.join(tml, f)): files.append((f, lvl))
        files += [("ongoing_tourneys.csv", None), ("challenger_ongoing_tourneys.csv", None)]
    else:
        for y in years:
            if os.path.exists(os.path.join(tml, f"{y}_wta.csv")): files.append((f"{y}_wta.csv", None))
        files += [("wta_ongoing_tourneys.csv", None)]
    if tour == "wta":                                # archivio Sackmann: ITF + qualificazioni WTA (aiuta molto sulle giocatrici meno note)
        here = os.path.dirname(os.path.abspath(__file__))
        for p in [os.environ.get("EXTRA_FILE", ""), os.path.join(here, "wta_itf.csv.gz"), os.path.join(here, "..", "wta_itf.csv.gz"), "wta_itf.csv.gz"]:
            if p and os.path.exists(p): files.append((os.path.abspath(p), "S")); break
    parts = []
    for f, lvl in files:
        p = os.path.join(tml, f)
        if not os.path.exists(p): continue
        d = pd.read_csv(p, low_memory=False)
        if d.empty: continue
        if lvl == "S": d = d[pd.to_numeric(d["tourney_date"], errors="coerce") // 10000 >= first_year]
        if lvl: d["tourney_level"] = lvl; d["best_of"] = 3
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df = df.dropna(subset=["winner_name", "loser_name", "tourney_date"])
    df = df[~df["tourney_name"].astype(str).str.contains("Laver Cup|Exhibition|Hopman", case=False)]
    df = df.drop_duplicates(["tourney_id", "winner_name", "loser_name", "round"])
    df["score"] = df["score"].fillna("").astype(str)
    df["incomplete"] = df["score"].str.contains("RET|W/O|DEF|Walkover|ABD|unfinished", case=False)
    df["walkover"] = df["score"].str.contains("W/O|Walkover", case=False)
    # forfait: non dicono chi è più forte, ma segnalano un problema fisico → li tengo solo per lo stato "infortuni"
    df["surface"] = df["surface"].fillna("Hard").replace({"Carpet": "Hard"})
    df["best_of"] = pd.to_numeric(df["best_of"], errors="coerce").fillna(3).astype(int)
    if tour == "wta": df["best_of"] = 3
    df["tourney_level"] = df["tourney_level"].astype(str)
    io = df["indoor"].astype(str).str.upper().map({"I": 1.0, "O": 0.0}) if "indoor" in df else pd.Series(np.nan, index=df.index)
    by_name = io.groupby(df["tourney_name"]).transform("mean")
    rule = df["tourney_name"].astype(str).apply(lambda n: 1.0 if any(k.lower() in n.lower() for k in INDOOR) else 0.0)
    df["indoor_f"] = io.fillna(by_name.round()).fillna(rule)
    df["country"] = df["tourney_name"].map(HOME)
    df["alt"] = df["tourney_name"].map(ALTITUDE).fillna(0.0)
    df["start"] = pd.to_datetime(df["tourney_date"].astype(int).astype(str), format="%Y%m%d")
    df["rord"] = df["round"].map(ROUND_ORD).fillna(12)
    # data stimata della partita: dove tutte le partite hanno la data di inizio torneo, la sposto in base al turno
    g = df.groupby("tourney_id")
    same = g["start"].transform("nunique") == 1
    rmin, rmax = g["rord"].transform("min"), g["rord"].transform("max")
    span = np.where(df["best_of"].eq(5) | (g["rord"].transform("count") > 80), 13, 6)
    frac = ((df["rord"] - rmin.clip(lower=10)) / (rmax - rmin.clip(lower=10)).replace(0, 1)).clip(lower=0)
    off = np.where(df["rord"] < 10, df["rord"] - 3, frac * span)
    df["date"] = df["start"] + pd.to_timedelta(np.where(same, off, 0).round(), unit="D")
    df["tmax"], df["wind"] = np.nan, np.nan
    if weather and os.path.exists(weather):
        wx = pd.read_csv(weather).drop_duplicates(["tourney_name", "date"])
        wx["date"] = pd.to_datetime(wx["date"])
        df = df.drop(columns=["tmax", "wind"]).merge(wx[["tourney_name", "date", "tmax", "wind"]], on=["tourney_name", "date"], how="left")
        print(f"meteo trovato per {df['tmax'].notna().mean():.0%} delle partite")
    return df.sort_values(["date", "tourney_id", "rord", "match_num"]).reset_index(drop=True)


# ------------------------------------------------------------------ stato dei giocatori
LAYOFF_ELO = os.environ.get("LAYOFF_ELO", "1") == "1"

class State:
    def __init__(self, k_c=250.0, k_off=5.0, k_shape=0.4):
        self.k_c, self.k_off, self.k_shape = k_c, k_off, k_shape
        self.r = defaultdict(lambda: 1500.0); self.rs = defaultdict(lambda: 1500.0)
        self.n = defaultdict(int); self.ns = defaultdict(int)
        self.last = {}
        self.form = defaultdict(float)                         # media mobile di (risultato - attesa)
        self.spw = defaultdict(lambda: 0.62); self.rpw = defaultdict(lambda: 0.38); self.nst = defaultdict(int)
        self.recent = defaultdict(deque)                       # (data, minuti)
        self.ioc, self.age = {}, {}
        self.pts = {}
        self.ht = {}
        self.boost = {}
        self.S = defaultdict(float); self.R = defaultdict(float); self.nsr = defaultdict(int)
        self.mu = {"Hard": 0.45, "Clay": 0.38, "Grass": 0.55}           # logit della % media di punti vinti al servizio
        self.seas_surf = defaultdict(set)                      # (giocatore, anno) -> superfici giocate
        self.injk = defaultdict(list)                          # (data, peso): W/O pesa più di un ritiro in partita
        self.last_surf = defaultdict(lambda: deque(maxlen=3))
        self.title_date, self.title_tid = {}, {}
        self.last_lon = {}
        self.rp = defaultdict(lambda: 1500.0)                  # Elo sui punti vinti (dominio reale)
        self.sp2_sum = defaultdict(float); self.sp2_n = defaultdict(int); self.sp2_hist = defaultdict(dict)
        self.load = defaultdict(list)                          # (data, minuti) per carico esponenziale
        self.rg = defaultdict(lambda: 1500.0)                  # Elo sui game (quanto netta è la vittoria)
        self.h2h = defaultdict(int)                            # (vincitore, perdente) -> vittorie
        # stanchezza: torneo in corso, partita precedente, torneo della settimana prima
        self.cur_tid, self.cur_min, self.last_min, self.cur_start = {}, defaultdict(float), defaultdict(float), {}
        self.prev_min, self.prev_end = defaultdict(float), {}
        self.inj = defaultdict(deque)                          # date di ritiri/forfait
        self.rio = defaultdict(lambda: 1500.0); self.nio = defaultdict(int)   # Elo indoor / outdoor
        self.clutch = defaultdict(float); self.ncl = defaultdict(int)          # tie-break e set decisivi vs attese
        self.bps = defaultdict(lambda: 0.6); self.nbp = defaultdict(int)      # % palle break salvate
        self.spw_only = defaultdict(lambda: 0.62)
        # velocità dei campi: quanti ace in più (o in meno) del solito fanno i giocatori in quel torneo
        self.ace = defaultdict(lambda: 0.07); self.nace = defaultdict(int)
        self.sp_sum = defaultdict(float); self.sp_n = defaultdict(int)
        self.sp_hist = defaultdict(dict)                       # torneo -> {anno: indice}

    def k(self, n): return self.k_c / (n + self.k_off) ** self.k_shape
    @staticmethod
    def expect(a, b): return 1.0 / (1.0 + 10 ** ((b - a) / 400.0))

    def player_feats(self, p, date):
        days = (date - self.last[p]).days if p in self.last else 400
        q = self.recent[p]
        while q and (date - q[0][0]).days > 10: q.popleft()
        mins3 = sum(m for d, m in q if (date - d).days <= 3)
        sr = self.spw[p] + self.rpw[p] - 1.0
        w = self.nst[p] / (self.nst[p] + 15)                   # poche partite → servizio/risposta poco affidabili
        iq = self.inj[p]
        while iq and (date - iq[0]).days > 90: iq.popleft()
        return dict(layoff=math.log1p(min(days, 400)), mins3=mins3 / 60, n10=len(q), sr=sr * w * 100, form=self.form[p],
                    inj=len(iq), clutch=self.clutch[p] * self.ncl[p] / (self.ncl[p] + 20),
                    bps=(self.bps[p] - 0.6) * self.nbp[p] / (self.nbp[p] + 20) * 100,
                    srv=(self.spw_only[p] - 0.62) * w * 100)

    def fatigue(self, p, tid, start, date):
        if self.cur_tid.get(p) == tid:                  # già in gara in questo torneo
            tmin, pm = self.cur_min[p], self.last_min[p]
            wk = self.prev_min[p] if p in self.prev_end and (start - self.prev_end[p]).days <= 9 else 0.0
        else:                                           # primo match del torneo: il torneo precedente è "la settimana prima"
            tmin, pm = 0.0, 0.0
            wk = self.cur_min[p] if p in self.last and (start - self.last[p]).days <= 9 else 0.0
        return tmin / 60, pm / 60, wk / 60

    def fatigue_update(self, p, tid, start, date, minutes):
        if self.cur_tid.get(p) != tid:
            self.prev_min[p] = self.cur_min[p]
            if p in self.last: self.prev_end[p] = self.last[p]
            self.cur_tid[p], self.cur_min[p], self.cur_start[p] = tid, 0.0, start
        self.cur_min[p] += minutes; self.last_min[p] = minutes

    def speed(self, tname, year):
        """Indice di velocità (punti % di ace sopra la media dei giocatori). Usa le partite già giocate
        in questa edizione; se sono poche, le mescola con l'edizione precedente."""
        cur_n, cur = self.sp_n[(tname, year)], (self.sp_sum[(tname, year)] / self.sp_n[(tname, year)] if self.sp_n[(tname, year)] else 0.0)
        prev = [v for y, v in self.sp_hist[tname].items() if y < year]
        prior = prev[-1] if prev else 0.0
        w = cur_n / (cur_n + 15)
        return (w * cur + (1 - w) * prior) * 100

    def features(self, a, b, surface, date, ctx):
        fa, fb = self.player_feats(a, date), self.player_feats(b, date)
        io = "I" if ctx["indoor"] >= 0.5 else "O"
        f = {"d_overall": self.r[a] - self.r[b], "d_surface": self.rs[(a, surface)] - self.rs[(b, surface)],
             "log_n_a": math.log1p(self.n[a]), "log_n_b": math.log1p(self.n[b])}
        for k in fa: f["d_" + k] = fa[k] - fb[k]
        f["layoff_max"] = max(fa["layoff"], fb["layoff"])
        f["d_io"] = self.rio[(a, io)] - self.rio[(b, io)]
        age = lambda x: abs(x - 26.0) if x == x else 0.0
        f["d_age"] = age(ctx["age_a"]) - age(ctx["age_b"])
        f["d_home"] = float(ctx["ioc_a"] == ctx["country"]) - float(ctx["ioc_b"] == ctx["country"])
        f["alt"] = ctx["alt"]
        f["speed"] = self.speed(ctx["tname"], date.year)
        f["d_mov"] = self.rg[a] - self.rg[b]
        # maratona: partita precedente nello stesso torneo oltre 150 minuti (ATP) / 130 (WTA)
        thr = 150 if ctx["best_of"] == 5 or ctx.get("tour") == "atp" else 130
        mar = lambda p: float(self.cur_tid.get(p) == ctx["tid"] and self.last_min[p] >= thr)
        f["d_marathon"] = mar(a) - mar(b)
        # prima partita della stagione su terra/erba, contro chi ci ha già giocato
        if surface in ("Clay", "Grass"):
            fa_, fb_ = surface not in self.seas_surf[(a, date.year)], surface not in self.seas_surf[(b, date.year)]
            f["d_first_surf"] = float(fa_) - float(fb_)
        else:
            f["d_first_surf"] = 0.0
        # superficie pesata per esperienza: w = n/(n+c)
        nsa, nsb = self.ns[(a, surface)], self.ns[(b, surface)]
        f["d_surf_sh"] = (nsa / (nsa + 20)) * (self.rs[(a, surface)] - self.r[a]) - (nsb / (nsb + 20)) * (self.rs[(b, surface)] - self.r[b])
        # infortuni con gravità e decadimento (mezza vita ~3 settimane)
        injd = lambda p: sum(w * math.exp(-(date - d).days / 30) for d, w in self.injk[p] if 0 <= (date - d).days <= 120)
        f["d_injd"] = injd(a) - injd(b)
        # shock di superficie: nessuna delle ultime 3 partite su questa superficie, e ultima partita da meno di 10 giorni
        def shock(p):
            ls = self.last_surf[p]
            return float(len(ls) > 0 and surface not in ls and p in self.last and (date - self.last[p]).days <= 10)
        f["d_shock"] = shock(a) - shock(b)
        # "hangover": titolo vinto nel torneo precedente, primo match del nuovo torneo
        def hang(p):
            return float(p in self.title_date and self.title_tid.get(p) != ctx["tid"] and self.cur_tid.get(p) != ctx["tid"]
                         and (ctx["start"] - self.title_date[p]).days <= 9)
        f["d_hang"] = hang(a) - hang(b)
        # mancini / altezza
        f["d_left"] = float(ctx["hand_a"] == "L") - float(ctx["hand_b"] == "L")
        f["cg"] = float(surface in ("Clay", "Grass"))
        hta, htb = ctx["ht_a"], ctx["ht_b"]
        f["d_ht"] = (hta - htb) / 10 if hta == hta and htb == htb and hta > 150 and htb > 150 else 0.0
        # fusi orari attraversati (solo tornei con coordinate note, primo match del torneo)
        lon = TCOORD.get(ctx["tname"], (None, None))[1]
        def jet(p):
            if lon is None or p not in self.last_lon or self.cur_tid.get(p) == ctx["tid"]: return 0.0
            if p not in self.last or (ctx["start"] - self.last[p]).days > 12: return 0.0
            dl = abs(lon - self.last_lon[p]); dl = min(dl, 360 - dl)
            return dl / 15
        f["d_jet"] = jet(a) - jet(b)
        def jet6(p):
            if jet(p) < 6 or (ctx["start"] - self.last[p]).days > 4: return 0.0
            return 1.0
        f["d_jet6"] = jet6(a) - jet6(b)
        # settimana prima di uno Slam: i big in un 250/500 rendono meno
        top = lambda pts: float(pts == pts and pts >= 2000)
        f["preslam"] = float(ctx.get("preslam", False))
        f["d_preslam"] = f["preslam"] * (top(ctx["pts_a"]) - top(ctx["pts_b"]))
        # velocità 2: punti al servizio vinti sopra le attese nel torneo
        cur_n = self.sp2_n[(ctx["tname"], date.year)]
        cur = self.sp2_sum[(ctx["tname"], date.year)] / cur_n if cur_n else 0.0
        prev = [v for y, v in self.sp2_hist[ctx["tname"]].items() if y < date.year]
        wsp = cur_n / (cur_n + 15)
        f["speed2"] = (wsp * cur + (1 - wsp) * (prev[-1] if prev else 0.0)) * 100
        # Elo sui punti
        f["d_ptselo"] = self.rp[a] - self.rp[b]
        qa, qb = self.sr_probs(a, b, surface)
        pm2 = min(max(markov_match(qa, qb, ctx["best_of"]), 0.005), 0.995)
        f["d_pt2"] = math.log(pm2 / (1 - pm2))
        f["d_style"] = self.S[a] * (-self.R[b]) - self.S[b] * (-self.R[a])
        f["unc2"] = ((30 / (self.n[a] + 5)) ** 2 + (min((date - self.last[a]).days, 365) / 365 if a in self.last else 1.0)
                     + (30 / (self.n[b] + 5)) ** 2 + (min((date - self.last[b]).days, 365) / 365 if b in self.last else 1.0))
        # incertezza (stile Glicko): poche partite o lungo stop → Elo meno affidabile
        rd = lambda p: min(1.0, math.sqrt((30 / (self.n[p] + 5)) ** 2 + ((date - self.last[p]).days / 365 if p in self.last else 1.0)))
        f["unc"] = (rd(a) + rd(b)) / 2
        # carico esponenziale (minuti, mezza vita ~5 giorni)
        ld = lambda p: sum(m * math.exp(-(date - d).days / 7) for d, m in self.load[p] if 0 <= (date - d).days <= 21) / 60
        f["d_load"] = ld(a) - ld(b)
        wa, wb = self.h2h[(a, b)], self.h2h[(b, a)]
        f["d_h2h"] = (wa - wb) / (wa + wb + 2)
        f["d_rank"] = math.log1p(ctx["pts_a"]) - math.log1p(ctx["pts_b"]) if ctx["pts_a"] == ctx["pts_a"] and ctx["pts_b"] == ctx["pts_b"] else 0.0
        f["d_q"] = float(ctx["ent_a"] in ("Q", "LL")) - float(ctx["ent_b"] in ("Q", "LL"))
        wsa, wsb = self.nst[a] / (self.nst[a] + 15), self.nst[b] / (self.nst[b] + 15)
        sa, ra = 0.62 + (self.spw[a] - 0.62) * wsa, 0.38 + (self.rpw[a] - 0.38) * wsa
        sb, rb = 0.62 + (self.spw[b] - 0.62) * wsb, 0.38 + (self.rpw[b] - 0.38) * wsb
        pm = markov_match(sa - (rb - 0.38), sb - (ra - 0.38), ctx["best_of"])
        pm = min(max(pm, 0.005), 0.995)
        f["d_pt"] = math.log(pm / (1 - pm))
        ta, tb = self.fatigue(a, ctx["tid"], ctx["start"], date), self.fatigue(b, ctx["tid"], ctx["start"], date)
        f["d_tmin"], f["d_pmin"], f["d_wk"] = ta[0] - tb[0], ta[1] - tb[1], ta[2] - tb[2]
        sh = lambda p: (self.ace[p] - 0.07) * self.nace[p] / (self.nace[p] + 15) * 100
        f["d_ace"] = sh(a) - sh(b)
        out = ctx["indoor"] < 0.5
        f["heat"] = (ctx["tmax"] - 25) / 10 if out and ctx["tmax"] == ctx["tmax"] else 0.0
        f["windy"] = (ctx["wind"] - 15) / 10 if out and ctx["wind"] == ctx["wind"] else 0.0
        return f

    def mov_update(self, w, l, score, level):
        g = re.findall(r"(\d+)-(\d+)", str(score))
        gw = sum(int(x) for x, _ in g); gl = sum(int(y) for _, y in g)
        if gw + gl < 6: return
        sh = gw / (gw + gl)
        e = self.expect(self.rg[w], self.rg[l]) 
        e = 0.5 + (e - 0.5) * 0.5                     # la quota di game attesa è più "schiacciata" della prob. di vittoria
        k = 40 * LEVEL_W.get(level, 1.0)
        self.rg[w] += k * (sh - e); self.rg[l] -= k * (sh - e)

    def injury(self, p, date):
        self.inj[p].append(date)

    def sr_probs(self, a, b, surface):
        mu = self.mu.get(surface, 0.45)
        sg = lambda z: 1 / (1 + math.exp(-z))
        return sg(mu + self.S[a] - self.R[b]), sg(mu + self.S[b] - self.R[a])

    def sr_update(self, server, returner, won, tot, surface):
        if tot < 20: return
        pa, _ = self.sr_probs(server, returner, surface)
        res = won / tot - pa
        g = res / max(pa * (1 - pa), 0.05)                              # passo nel logit
        ks = 0.5 / math.sqrt(1 + self.nsr[server] / 10); kr = 0.5 / math.sqrt(1 + self.nsr[returner] / 10)
        self.S[server] += ks * 0.25 * g; self.R[returner] -= kr * 0.25 * g
        self.mu[surface] = self.mu.get(surface, 0.45) + 0.002 * g     # media del circuito che si adatta lentamente

    def comeback(self, p, date):
        """dopo più di 60 giorni di stop: l'Elo regredisce un po' verso la media e per 5 partite si aggiorna più in fretta."""
        if not LAYOFF_ELO or p not in self.last: return
        d = (date - self.last[p]).days
        if d > 60:
            f = min(0.15, 0.05 * (d - 60) / 60)
            self.r[p] -= (self.r[p] - 1500) * f
            for s_ in SURFACES: self.rs[(p, s_)] -= (self.rs[(p, s_)] - 1500) * f
            self.boost[p] = 5

    def update(self, w, l, surface, level, date, minutes, stats, complete, io, score, bp):
        lw = LEVEL_W.get(level, 1.0) * (0.5 if not complete else 1.0)   # i ritiri contano meno
        e = self.expect(self.r[w], self.r[l])
        bw = 1.5 if self.boost.get(w, 0) > 0 else 1.0; bl = 1.5 if self.boost.get(l, 0) > 0 else 1.0
        self.r[w] += self.k(self.n[w]) * lw * bw * (1 - e); self.r[l] -= self.k(self.n[l]) * lw * bl * (1 - e)
        for p in (w, l):
            if self.boost.get(p, 0) > 0: self.boost[p] -= 1
        if surface in SURFACES:
            sw, sl = (w, surface), (l, surface)
            es = self.expect(self.rs[sw], self.rs[sl])
            self.rs[sw] += self.k(self.ns[sw]) * lw * (1 - es); self.rs[sl] -= self.k(self.ns[sl]) * lw * (1 - es)
            self.ns[sw] += 1; self.ns[sl] += 1
        iw, il = (w, io), (l, io)
        ei = self.expect(self.rio[iw], self.rio[il])
        self.rio[iw] += self.k(self.nio[iw]) * lw * (1 - ei); self.rio[il] -= self.k(self.nio[il]) * lw * (1 - ei)
        self.nio[iw] += 1; self.nio[il] += 1
        # momenti di pressione: tie-break e set decisivo, confrontati con la probabilità attesa
        if complete:
            sets = re.findall(r"(\d+)-(\d+)", str(score))
            for i, (g1, g2) in enumerate(sets):
                g1, g2 = int(g1), int(g2)
                tb = {g1, g2} == {6, 7} or {g1, g2} == {7, 6}
                decider = i == len(sets) - 1 and len(sets) in (3, 5)
                if tb or decider:
                    won = g1 > g2
                    for p, res in ((w, won), (l, not won)):
                        exp_p = e if p == w else 1 - e
                        self.clutch[p] = 0.9 * self.clutch[p] + 0.1 * ((1.0 if res else 0.0) - exp_p)
                        self.ncl[p] += 1
        if bp is not None:
            for p, (sv, fc) in zip((w, l), bp):
                if fc >= 3:
                    self.bps[p] = 0.9 * self.bps[p] + 0.1 * sv / fc; self.nbp[p] += 1
        self.form[w] = 0.85 * self.form[w] + 0.15 * (1 - e)
        self.form[l] = 0.85 * self.form[l] + 0.15 * (0 - (1 - e))
        if stats is not None:
            ws, ls = stats                                    # punti vinti al servizio / giocati al servizio
            for p, s_won, s_tot, r_won, r_tot in [(w, ws[0], ws[1], ls[1] - ls[0], ls[1]), (l, ls[0], ls[1], ws[1] - ws[0], ws[1])]:
                if s_tot > 20 and r_tot > 20:
                    a = 0.1
                    self.spw[p] = (1 - a) * self.spw[p] + a * s_won / s_tot
                    self.spw_only[p] = self.spw[p]
                    self.rpw[p] = (1 - a) * self.rpw[p] + a * r_won / r_tot
                    self.nst[p] += 1
        for p in (w, l):
            self.n[p] += 1; self.last[p] = date
            self.recent[p].append((date, minutes if minutes == minutes and minutes > 0 else 100))


TOUR = "atp"

def build(df):
    st = State(); rows = []
    rng = np.random.default_rng(0)
    cols = ["w_svpt", "w_1stWon", "w_2ndWon", "l_svpt", "l_1stWon", "l_2ndWon"]
    S = df[cols].apply(pd.to_numeric, errors="coerce").to_numpy() if set(cols) <= set(df) else None
    mins = pd.to_numeric(df.get("minutes"), errors="coerce").to_numpy() if "minutes" in df else np.full(len(df), np.nan)
    book = df["book_w"].to_numpy() if "book_w" in df else np.full(len(df), np.nan)
    num = lambda c: pd.to_numeric(df[c], errors="coerce").to_numpy() if c in df else np.full(len(df), np.nan)
    wage, lage = num("winner_age"), num("loser_age")
    bpw = np.column_stack([num("w_bpSaved"), num("w_bpFaced")]); bpl = np.column_stack([num("l_bpSaved"), num("l_bpFaced")])
    wpts, lpts = num("winner_rank_points"), num("loser_rank_points")
    whand = df["winner_hand"].fillna("").astype(str).to_numpy() if "winner_hand" in df else np.full(len(df), "")
    lhand = df["loser_hand"].fillna("").astype(str).to_numpy() if "loser_hand" in df else np.full(len(df), "")
    wht, lht = num("winner_ht"), num("loser_ht")
    went = df["winner_entry"].astype(str).to_numpy() if "winner_entry" in df else np.full(len(df), "")
    lent = df["loser_entry"].astype(str).to_numpy() if "loser_entry" in df else np.full(len(df), "")
    aces = np.column_stack([num("w_ace"), num("w_svpt"), num("l_ace"), num("l_svpt")])
    wioc, lioc = df["winner_ioc"].fillna("").astype(str).to_numpy(), df["loser_ioc"].fillna("").astype(str).to_numpy()
    # tornei 250/500 nella settimana prima di uno Slam
    slam_starts = sorted(df.loc[df["tourney_level"] == "G", "start"].unique())
    def is_pre(row_start, lvl):
        if lvl not in ("A", "250", "500"): return False
        return any(0 < (pd.Timestamp(s0) - row_start).days <= 8 for s0 in slam_starts)
    tstart = df.drop_duplicates("tourney_id").set_index("tourney_id")
    pre_t = {tid: is_pre(r.start, r.tourney_level) for tid, r in tstart.iterrows()}
    pre_slam = df["tourney_id"].map(pre_t).fillna(False).to_numpy()
    for i, t in enumerate(df.itertuples(index=False)):
        w, l = t.winner_name, t.loser_name
        if t.walkover:
            st.injury(l, t.date); st.injk[l].append((t.date, 1.0)); continue
        flip = rng.random() < 0.5
        a, b = (l, w) if flip else (w, l)
        ctx = dict(hand_a=lhand[i] if flip else whand[i], hand_b=whand[i] if flip else lhand[i],
                   ht_a=lht[i] if flip else wht[i], ht_b=wht[i] if flip else lht[i],
                   pts_a=lpts[i] if flip else wpts[i], pts_b=wpts[i] if flip else lpts[i],
                   ent_a=lent[i] if flip else went[i], ent_b=went[i] if flip else lent[i], best_of=t.best_of,
                   tid=t.tourney_id, start=t.start, indoor=t.indoor_f, alt=t.alt, country=t.country, tmax=t.tmax, wind=t.wind, tname=t.tourney_name,
                   age_a=lage[i] if flip else wage[i], age_b=wage[i] if flip else lage[i],
                   ioc_a=lioc[i] if flip else wioc[i], ioc_b=wioc[i] if flip else lioc[i])
        ctx["preslam"] = bool(pre_slam[i]); ctx["tour"] = TOUR
        st.comeback(w, t.date); st.comeback(l, t.date)
        f = st.features(a, b, t.surface, t.date, ctx)
        f.update(y=0 if flip else 1, best_of=t.best_of, date=t.date, level=t.tourney_level,
                 complete=not t.incomplete, book_a=(1 - book[i]) if flip else book[i], a=a, b=b)
        rows.append(f)
        stats = None
        if S is not None and not np.isnan(S[i]).any():
            stats = ((S[i, 1] + S[i, 2], S[i, 0]), (S[i, 4] + S[i, 5], S[i, 3]))
        if t.incomplete:                                  # il ritiro si registra solo DOPO la previsione di questa partita
            st.injury(l, t.date)
            if re.search("RET", str(t.score)): st.injk[l].append((t.date, 0.7))
        mm = mins[i] if mins[i] == mins[i] and mins[i] > 0 else 40.0 * max(2, len(re.findall(r"\d+-\d+", str(t.score))))
        for p in (w, l): st.fatigue_update(p, t.tourney_id, t.start, t.date, mm)
        for p in (w, l):
            st.seas_surf[(p, t.date.year)].add(t.surface)
            st.last_surf[p].append(t.surface)
            st.load[p].append((t.date, mm)); st.load[p] = [x for x in st.load[p] if (t.date - x[0]).days <= 21]
            if t.tourney_name in TCOORD: st.last_lon[p] = TCOORD[t.tourney_name][1]
        if str(t.round) == "F" and not t.incomplete:
            st.title_date[w], st.title_tid[w] = t.date, t.tourney_id
        if S is not None and not np.isnan(S[i]).any():
            sw, sl = S[i, 1] + S[i, 2], S[i, 4] + S[i, 5]                 # punti vinti al servizio
            tot = S[i, 0] + S[i, 3]
            if tot > 40:
                pw = (sw + (S[i, 3] - sl)) / tot                            # quota di punti vinti dal vincitore
                e = st.expect(st.rp[w], st.rp[l]); e = 0.5 + (e - 0.5) * 0.25
                k = 40 * LEVEL_W.get(t.tourney_level, 1.0)
                st.rp[w] += k * (pw - e); st.rp[l] -= k * (pw - e)
                res2 = []
                for p, won, sv in ((w, sw, S[i, 0]), (l, sl, S[i, 3])):
                    if sv >= 30 and st.nst[p] >= 5: res2.append(won / sv - st.spw[p])
                if res2:
                    kk = (t.tourney_name, t.date.year)
                    st.sp2_sum[kk] += sum(res2) / len(res2); st.sp2_n[kk] += 1
                    if st.sp2_n[kk] >= 10: st.sp2_hist[t.tourney_name][t.date.year] = st.sp2_sum[kk] / st.sp2_n[kk]
        if wht[i] == wht[i] and wht[i] > 150: st.ht[w] = int(wht[i])
        if lht[i] == lht[i] and lht[i] > 150: st.ht[l] = int(lht[i])
        if S is not None and not np.isnan(S[i]).any() and t.surface in SURFACES:
            st.sr_update(w, l, S[i, 1] + S[i, 2], S[i, 0], t.surface)
            st.sr_update(l, w, S[i, 4] + S[i, 5], S[i, 3], t.surface)
            st.nsr[w] += 1; st.nsr[l] += 1
        if wpts[i] == wpts[i]: st.pts[w] = float(wpts[i])
        if lpts[i] == lpts[i]: st.pts[l] = float(lpts[i])
        if not t.incomplete:
            st.mov_update(w, l, t.score, t.tourney_level)
            st.h2h[(w, l)] += 1
        st.ioc[w], st.ioc[l] = wioc[i], lioc[i]
        if wage[i] == wage[i]: st.age[w] = round(float(wage[i]) + 0, 1)
        if lage[i] == lage[i]: st.age[l] = round(float(lage[i]), 1)
        if not (np.isnan(aces[i]).any()):
            res = []
            for p, ac, sv in ((w, aces[i, 0], aces[i, 1]), (l, aces[i, 2], aces[i, 3])):
                if sv >= 30:
                    if st.nace[p] >= 5: res.append(ac / sv - st.ace[p])
                    st.ace[p] = 0.9 * st.ace[p] + 0.1 * ac / sv; st.nace[p] += 1
            if res:
                k = (t.tourney_name, t.date.year)
                st.sp_sum[k] += sum(res) / len(res); st.sp_n[k] += 1
                if st.sp_n[k] >= 10: st.sp_hist[t.tourney_name][t.date.year] = st.sp_sum[k] / st.sp_n[k]
        bp = None if np.isnan(bpw[i]).any() or np.isnan(bpl[i]).any() else (tuple(bpw[i]), tuple(bpl[i]))
        st.update(w, l, t.surface, t.tourney_level, t.date, mins[i], stats, not t.incomplete,
                  "I" if t.indoor_f >= 0.5 else "O", t.score, bp)
    return st, pd.DataFrame(rows)


# ------------------------------------------------------------------ modello
# variabili finali: ognuna migliora la log loss sia nel 2025 sia nel 2026 (test fuori campione)
FINAL = {"atp": ["d_sr", "d_layoff", "d_rank", "d_ace_speed", "d_hang", "d_first_surf", "d_shock", "d_ptselo",
                 "d_mov", "d_pmin", "d_home", "d_pt2"],
         "wta": ["d_sr", "d_layoff", "d_rank", "d_ace_speed", "d_mov", "d_wk", "d_first_surf", "d_ptselo",
                 "d_marathon", "d_home", "d_pt2"]}
# scelta con walk-forward 2019-2026 (addestramento solo sul passato) e bootstrap accoppiato sulla log loss
BASE = ["d_overall", "d_surface", "d_overall_bo5", "d_surface_bo5", "d_overall_exp"]
EXTRA = ["d_sr", "d_layoff",                                  # già nel modello v2
         "d_inj", "d_age",                                      # fisico
         "d_clutch", "d_bps", "d_home",                         # mentale
         "d_io", "d_srv_alt",                                   # condizioni di gioco
         "d_ace_speed", "d_srv_speed", "d_overall_speed",        # velocità del campo
         "d_tmin", "d_pmin", "d_wk",                             # stanchezza
         "d_mov", "d_h2h", "d_rank", "d_q", "d_pt"]               # margine, precedenti, classifica, punto per punto

def design(X, feats):
    bo5 = (X["best_of"] == 5).astype(float)
    exp_n = np.minimum(X["log_n_a"], X["log_n_b"]) / math.log1p(200)
    lay = (X["layoff_max"] / math.log1p(400))
    M = {"d_overall": X["d_overall"] / 100, "d_surface": X["d_surface"] / 100,
         "d_overall_bo5": X["d_overall"] / 100 * bo5, "d_surface_bo5": X["d_surface"] / 100 * bo5,
         "d_overall_exp": X["d_overall"] / 100 * exp_n,
         "d_form": X["d_form"] * 10, "d_sr": X["d_sr"] / 5, "d_layoff": X["d_layoff"], "d_mins3": X["d_mins3"],
         "d_n10": X["d_n10"] / 3, "d_overall_layoff": X["d_overall"] / 100 * lay,
         "d_inj": X["d_inj"], "d_age": X["d_age"] / 5, "d_clutch": X["d_clutch"] * 10, "d_bps": X["d_bps"] / 5,
         "d_home": X["d_home"], "d_io": X["d_io"] / 100, "d_srv_alt": X["d_srv"] / 5 * X["alt"],
         "d_srv_heat": X["d_srv"] / 5 * X["heat"], "d_srv_wind": X["d_srv"] / 5 * X["windy"], "d_age_heat": X["d_age"] / 5 * X["heat"],
         "d_ace_speed": X["d_ace"] / 3 * X["speed"] / 2, "d_srv_speed": X["d_srv"] / 5 * X["speed"] / 2,
         "d_overall_speed": X["d_overall"] / 100 * X["speed"] / 2,
         "d_tmin": X["d_tmin"], "d_pmin": X["d_pmin"], "d_wk": X["d_wk"],
         "d_injd": X["d_injd"], "d_shock": X["d_shock"], "d_hang": X["d_hang"], "d_left": X["d_left"],
         "d_left_cg": X["d_left"] * X["cg"], "d_ht": X["d_ht"], "d_ht_speed": X["d_ht"] * X["speed"] / 2,
         "d_jet": X["d_jet"] / 3, "d_srv_speed2": X["d_srv"] / 5 * X["speed2"], "d_ptselo": X["d_ptselo"] / 100,
         "d_overall_unc": X["d_overall"] / 100 * X["unc"], "d_load": X["d_load"],
         "d_marathon": X["d_marathon"], "d_first_surf": X["d_first_surf"], "d_surf_sh": X["d_surf_sh"] / 100,
         "d_jet6": X["d_jet6"], "d_preslam": X["d_preslam"], "d_pt2": X["d_pt2"], "d_style": X["d_style"],
         "d_mov": X["d_mov"] / 100, "d_h2h": X["d_h2h"], "d_rank": X["d_rank"], "d_q": X["d_q"], "d_pt": X["d_pt"],
         "d_overall_wind": X["d_overall"] / 100 * X["windy"], "d_overall_heat": X["d_overall"] / 100 * X["heat"]}
    return np.column_stack([np.asarray(M[f], dtype=float) for f in feats])

def fit_logistic(M, y, l2=1e-2, iters=60):
    w = np.zeros(M.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-M @ w))
        g = M.T @ (p - y) + l2 * w
        H = (M * (p * (1 - p))[:, None]).T @ M + l2 * np.eye(len(w))
        s = np.linalg.solve(H, g); w -= s
        if np.abs(s).max() < 1e-9: break
    return w

def metrics(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {"acc": float(((p > 0.5) == y).mean()), "brier": float(((p - y) ** 2).mean()),
            "logloss": float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), "n": int(len(y))}

def predict(X, feats, w): return 1 / (1 + np.exp(-design(X, feats) @ w))


def attach_book(df, path):
    """Aggiunge le quote di chiusura (prob. vittoria del vincitore) da un file con nomi completi."""
    import unicodedata
    norm = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())
    b = pd.read_csv(path, low_memory=False).dropna(subset=["winner_close_prob"])
    key = {(norm(r.winner_name), norm(r.loser_name), str(r.tourney_name)[:6].lower()): r.winner_close_prob for r in b.itertuples()}
    keyb = {}
    for (w, l, _), p in key.items(): keyb.setdefault((w, l), []).append(p)
    out = []
    for r in df.itertuples():
        k = (norm(r.winner_name), norm(r.loser_name))
        v = keyb.get(k)
        out.append(v[0] if v and len(v) == 1 else np.nan)
    df["book_w"] = out
    return df


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tml", default="./tml"); ap.add_argument("--tour", default="atp", choices=["atp", "wta"])
    ap.add_argument("--test-from", type=int, default=2026); ap.add_argument("--book", default=None)
    ap.add_argument("--out", default=".")
    ap.add_argument("--also", nargs="*", default=None,
                    help="feature da includere comunque (verificate su più anni)")
    ap.add_argument("--weather", default=None, help="weather.csv creato da fetch_weather.py")
    args = ap.parse_args()

    global TOUR; TOUR = args.tour
    df = load(args.tml, args.tour, weather=args.weather)
    extra = EXTRA + (["d_srv_heat", "d_srv_wind", "d_age_heat", "d_overall_wind", "d_overall_heat"] if args.weather else [])
    if args.book: df = attach_book(df, args.book)
    st, X = build(df)
    yr = X["date"].dt.year
    known = np.minimum(X["log_n_a"], X["log_n_b"]) >= math.log1p(10)
    main_tour = ~X["level"].isin(["C", "Q", "S"])
    val_from = args.test_from - 1
    tr = (yr >= 2013) & (yr < val_from) & known
    va = (yr == val_from) & known
    tr_full = (yr >= 2013) & (yr < args.test_from) & known
    te = (yr >= args.test_from) & known & (X["level"] != "S")   # ITF non conta nei risultati mostrati
    y = X["y"].to_numpy()

    base = BASE if args.tour == "atp" else [f for f in BASE if "bo5" not in f]
    chosen = base + FINAL[args.tour]
    # 2) test onesto sull'anno dopo
    w_old = fit_logistic(design(X[tr_full], base), y[tr_full])
    w_new = fit_logistic(design(X[tr_full], chosen), y[tr_full])
    p_old, p_new = predict(X[te], base, w_old), predict(X[te], chosen, w_new)
    yt = y[te]
    res = {"Modello precedente": metrics(p_old, yt), "Modello nuovo": metrics(p_new, yt)}
    mt = main_tour[te].to_numpy()
    res["Nuovo, solo circuito maggiore"] = metrics(p_new[mt], yt[mt])
    bk = X.loc[te, "book_a"].to_numpy(dtype=float); ok = ~np.isnan(bk)
    if ok.sum() > 200:
        res["Bookmaker (stesse partite)"] = metrics(bk[ok], yt[ok])
        res["Nuovo (stesse partite)"] = metrics(p_new[ok], yt[ok])
    print(f"\nTest dal {args.test_from}:")
    for k, m in res.items():
        print(f"  {k:<32} acc {m['acc']:.3f}  brier {m['brier']:.4f}  logloss {m['logloss']:.4f}  n={m['n']}")

    # calibrazione sul test (per il sito)
    conf = np.maximum(p_new, 1 - p_new); hit = (p_new > 0.5) == yt
    cal = []
    for lo, hi in [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]:
        m = (conf >= lo) & (conf < hi)
        cal.append({"lo": lo, "hi": min(hi, 1), "n": int(m.sum()), "hit": round(float(hit[m].mean()), 3) if m.sum() else None,
                    "pred": round(float(conf[m].mean()), 3) if m.sum() else None})

    # 3) modello finale su tutti i dati
    allm = (yr >= 2013) & known
    w_fin = fit_logistic(design(X[allm], chosen), y[allm])
    last = df["date"].max()
    players = {}
    for p, n in st.n.items():
        if n < 5: continue
        players[p] = {"elo": round(st.r[p], 1), "n": n,
                      "surface": {s: round(st.rs[(p, s)], 1) for s in SURFACES},
                      "last": st.last[p].strftime("%Y-%m-%d"), "active": bool((last - st.last[p]).days <= 365),
                      "form": round(st.form[p], 4), "ioc": st.ioc.get(p, ""), "age": st.age.get(p), "inj": [d.strftime("%Y-%m-%d") for d in st.inj[p] if (last - d).days <= 90],
                      "io": [round(st.rio[(p, "I")], 1), round(st.rio[(p, "O")], 1)],
                      "clutch": round(st.clutch[p] * st.ncl[p] / (st.ncl[p] + 20), 4),
                      "bps": round((st.bps[p] - 0.6) * st.nbp[p] / (st.nbp[p] + 20) * 100, 3),
                      "pts": st.pts.get(p, 0), "mov": round(st.rg[p], 1),
                      "ik": [[d.strftime("%Y-%m-%d"), wt] for d, wt in st.injk[p] if (last - d).days <= 120],
                      "td": st.title_date[p].strftime("%Y-%m-%d") if p in st.title_date else None,
                      "ht": st.ht.get(p), "rp": round(st.rp[p], 1), "S": round(st.S[p], 4), "R": round(st.R[p], 4),
                      "ss": sorted(st.seas_surf.get((p, last.year), set())), "ls": list(st.last_surf[p]),
                      "spw": round(0.62 + (st.spw[p] - 0.62) * st.nst[p] / (st.nst[p] + 15), 4),
                      "rpw": round(0.38 + (st.rpw[p] - 0.38) * st.nst[p] / (st.nst[p] + 15), 4),
                      "acer": round(0.07 + (st.ace[p] - 0.07) * st.nace[p] / (st.nace[p] + 15), 4),
                      "lm": round(st.last_min[p]), "tm": round(st.cur_min[p]), "pm": round(st.prev_min[p]),
                      "pe": st.prev_end[p].strftime("%Y-%m-%d") if p in st.prev_end else None,
                      "ace": round((st.ace[p] - 0.07) * st.nace[p] / (st.nace[p] + 15) * 100, 3),
                      "srv": round((st.spw_only[p] - 0.62) * st.nst[p] / (st.nst[p] + 15) * 100, 3), "sr": round((st.spw[p] + st.rpw[p] - 1) * st.nst[p] / (st.nst[p] + 15) * 100, 3)}
    out = {"tour": args.tour, "updated": last.strftime("%Y-%m-%d"), "features": chosen,
           "weights": [float(v) for v in w_fin], "calibration": cal,
           "test": {k: {kk: round(vv, 4) for kk, vv in m.items()} for k, m in res.items()},
           "test_from": args.test_from, "players": players}
    act = {p for p, v in players.items() if v["active"]}
    out["h2h"] = {f"{a}|{b}": [n, st.h2h.get((b, a), 0)] for (a, b), n in st.h2h.items() if a in act and b in act and a < b}
    out["h2h"].update({f"{b}|{a}": [st.h2h.get((b, a), 0), n] for (a, b), n in st.h2h.items() if a in act and b in act and a > b and f"{b}|{a}" not in out["h2h"]})
    mm = pd.to_numeric(df.get("minutes"), errors="coerce"); sp = pd.to_numeric(df.get("w_svpt"), errors="coerce") + pd.to_numeric(df.get("l_svpt"), errors="coerce")
    ok = (mm > 20) & (sp > 40) & ~df["incomplete"]
    out["sec_per_point"] = round(float((mm[ok] * 60 / sp[ok]).median()), 1)
    out["home"] = {k: v for k, v in HOME.items()}
    out["mu"] = {k: round(v, 4) for k, v in st.mu.items()}
    out["court_speed"] = {t: {str(y): round(v * 100, 2) for y, v in sorted(h.items())} for t, h in st.sp_hist.items()
                          if len(h) >= 3 and st.sp_n[(t, max(h))] >= 15}
    # scheda di ogni torneo (ultima edizione): superficie, formato, coperto, categoria
    info = {}
    md = df[~df["tourney_level"].isin(["Q", "S"])]
    for t, g in md.groupby("tourney_name"):
        if t not in out["court_speed"]: continue
        g = g[g["start"].dt.year == g["start"].dt.year.max()]
        info[t] = {"s": g["surface"].mode().iloc[0], "bo": int(g["best_of"].max()), "i": int(round(float(g["indoor_f"].mean()))),
                   "lv": str(g["tourney_level"].mode().iloc[0]), "y": int(g["start"].dt.year.max())}
    out["court_info"] = info
    path = os.path.join(args.out, f"ratings_{args.tour}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\nFeature finali: {chosen}\nPesi: {np.round(w_fin, 4).tolist()}\nSalvato {path}: {len(players)} giocatori, dati fino al {out['updated']}")
    act = sorted([kv for kv in players.items() if kv[1]["active"]], key=lambda kv: -kv[1]["elo"])[:10]
    for i, (p, d) in enumerate(act, 1): print(f"  {i:>2}. {p:<26} {d['elo']:.0f}")


if __name__ == "__main__":
    main()
