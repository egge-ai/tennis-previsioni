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
           "D": 0.9, "C": 0.85, "Q": 0.8}
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

ROUND_ORD = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3, "R128": 10, "R64": 11, "R32": 12, "R16": 13, "RR": 14,
             "QF": 15, "SF": 16, "BR": 17, "F": 18}


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
    parts = []
    for f, lvl in files:
        p = os.path.join(tml, f)
        if not os.path.exists(p): continue
        d = pd.read_csv(p, low_memory=False)
        if d.empty: continue
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
        ta, tb = self.fatigue(a, ctx["tid"], ctx["start"], date), self.fatigue(b, ctx["tid"], ctx["start"], date)
        f["d_tmin"], f["d_pmin"], f["d_wk"] = ta[0] - tb[0], ta[1] - tb[1], ta[2] - tb[2]
        sh = lambda p: (self.ace[p] - 0.07) * self.nace[p] / (self.nace[p] + 15) * 100
        f["d_ace"] = sh(a) - sh(b)
        out = ctx["indoor"] < 0.5
        f["heat"] = (ctx["tmax"] - 25) / 10 if out and ctx["tmax"] == ctx["tmax"] else 0.0
        f["windy"] = (ctx["wind"] - 15) / 10 if out and ctx["wind"] == ctx["wind"] else 0.0
        return f

    def injury(self, p, date):
        self.inj[p].append(date)

    def update(self, w, l, surface, level, date, minutes, stats, complete, io, score, bp):
        lw = LEVEL_W.get(level, 1.0) * (0.5 if not complete else 1.0)   # i ritiri contano meno
        e = self.expect(self.r[w], self.r[l])
        self.r[w] += self.k(self.n[w]) * lw * (1 - e); self.r[l] -= self.k(self.n[l]) * lw * (1 - e)
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
    aces = np.column_stack([num("w_ace"), num("w_svpt"), num("l_ace"), num("l_svpt")])
    wioc, lioc = df["winner_ioc"].astype(str).to_numpy(), df["loser_ioc"].astype(str).to_numpy()
    for i, t in enumerate(df.itertuples(index=False)):
        w, l = t.winner_name, t.loser_name
        if t.walkover:
            st.injury(l, t.date); continue
        if t.incomplete: st.injury(l, t.date)
        flip = rng.random() < 0.5
        a, b = (l, w) if flip else (w, l)
        ctx = dict(tid=t.tourney_id, start=t.start, indoor=t.indoor_f, alt=t.alt, country=t.country, tmax=t.tmax, wind=t.wind, tname=t.tourney_name,
                   age_a=lage[i] if flip else wage[i], age_b=wage[i] if flip else lage[i],
                   ioc_a=lioc[i] if flip else wioc[i], ioc_b=wioc[i] if flip else lioc[i])
        f = st.features(a, b, t.surface, t.date, ctx)
        f.update(y=0 if flip else 1, best_of=t.best_of, date=t.date, level=t.tourney_level,
                 complete=not t.incomplete, book_a=(1 - book[i]) if flip else book[i], a=a, b=b)
        rows.append(f)
        stats = None
        if S is not None and not np.isnan(S[i]).any():
            stats = ((S[i, 1] + S[i, 2], S[i, 0]), (S[i, 4] + S[i, 5], S[i, 3]))
        mm = mins[i] if mins[i] == mins[i] and mins[i] > 0 else 40.0 * max(2, len(re.findall(r"\d+-\d+", str(t.score))))
        for p in (w, l): st.fatigue_update(p, t.tourney_id, t.start, t.date, mm)
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
BASE = ["d_overall", "d_surface", "d_overall_bo5", "d_surface_bo5", "d_overall_exp"]
EXTRA = ["d_sr", "d_layoff",                                  # già nel modello v2
         "d_inj", "d_age",                                      # fisico
         "d_clutch", "d_bps", "d_home",                         # mentale
         "d_io", "d_srv_alt",                                   # condizioni di gioco
         "d_ace_speed", "d_srv_speed", "d_overall_speed",        # velocità del campo
         "d_tmin", "d_pmin", "d_wk"]                             # stanchezza

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

    df = load(args.tml, args.tour, weather=args.weather)
    extra = EXTRA + (["d_srv_heat", "d_srv_wind", "d_age_heat", "d_overall_wind", "d_overall_heat"] if args.weather else [])
    if args.book: df = attach_book(df, args.book)
    st, X = build(df)
    yr = X["date"].dt.year
    known = np.minimum(X["log_n_a"], X["log_n_b"]) >= math.log1p(10)
    main_tour = ~X["level"].isin(["C", "Q"])
    val_from = args.test_from - 1
    tr = (yr >= 2013) & (yr < val_from) & known
    va = (yr == val_from) & known
    tr_full = (yr >= 2013) & (yr < args.test_from) & known
    te = (yr >= args.test_from) & known
    y = X["y"].to_numpy()

    # 1) scelta delle feature sull'anno di validazione (mai sul test)
    base = BASE if args.tour == "atp" else [f for f in BASE if "bo5" not in f]
    chosen = list(base)
    base_ll = metrics(predict(X[va], chosen, fit_logistic(design(X[tr], chosen), y[tr])), y[va])["logloss"]
    print(f"[{args.tour}] validazione {val_from}: base log loss {base_ll:.4f}")
    for f in extra:
        cand = chosen + [f]
        ll = metrics(predict(X[va], cand, fit_logistic(design(X[tr], cand), y[tr])), y[va])["logloss"]
        keep = ll < base_ll - 0.0005
        print(f"   + {f:<18} {ll:.4f} {'tenuta' if keep else 'scartata'}")
        if keep: chosen, base_ll = cand, ll

    also = args.also if args.also is not None else (["d_ace_speed", "d_pmin"] if args.tour == "atp" else ["d_ace_speed", "d_wk"])
    for f in also:
        if f not in chosen: chosen.append(f)
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
                      "lm": round(st.last_min[p]), "tm": round(st.cur_min[p]), "pm": round(st.prev_min[p]),
                      "pe": st.prev_end[p].strftime("%Y-%m-%d") if p in st.prev_end else None,
                      "ace": round((st.ace[p] - 0.07) * st.nace[p] / (st.nace[p] + 15) * 100, 3),
                      "srv": round((st.spw_only[p] - 0.62) * st.nst[p] / (st.nst[p] + 15) * 100, 3), "sr": round((st.spw[p] + st.rpw[p] - 1) * st.nst[p] / (st.nst[p] + 15) * 100, 3)}
    out = {"tour": args.tour, "updated": last.strftime("%Y-%m-%d"), "features": chosen,
           "weights": [float(v) for v in w_fin], "calibration": cal,
           "test": {k: {kk: round(vv, 4) for kk, vv in m.items()} for k, m in res.items()},
           "test_from": args.test_from, "players": players}
    out["court_speed"] = {t: {str(y): round(v * 100, 2) for y, v in sorted(h.items())} for t, h in st.sp_hist.items()
                          if len(h) >= 3 and st.sp_n[(t, max(h))] >= 15}
    path = os.path.join(args.out, f"ratings_{args.tour}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\nFeature finali: {chosen}\nPesi: {np.round(w_fin, 4).tolist()}\nSalvato {path}: {len(players)} giocatori, dati fino al {out['updated']}")
    act = sorted([kv for kv in players.items() if kv[1]["active"]], key=lambda kv: -kv[1]["elo"])[:10]
    for i, (p, d) in enumerate(act, 1): print(f"  {i:>2}. {p:<26} {d['elo']:.0f}")


if __name__ == "__main__":
    main()
