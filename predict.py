"""
Previsione del modello a partire dai file pubblicati (ratings_atp.json / ratings_wta.json):
è la stessa formula usata dal sito, scritta in Python per congelare le previsioni nell'archivio.
"""
import datetime as dt, json, math, os, re, sys, unicodedata
_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.join(_here, "pipeline")): sys.path.insert(0, _p)
from model import markov_match

SI = {"Hard": 0, "Clay": 1, "Grass": 2}


def norm(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())


class Predictor:
    def __init__(self, out_dir):
        self.R = {}
        for t in ("atp", "wta"):
            p = os.path.join(out_dir, f"ratings_{t}.json")
            if os.path.exists(p):
                self.R[t] = json.load(open(p, encoding="utf-8"))
        self.idx = {t: {norm(k): k for k in R["players"]} for t, R in self.R.items()}

    def find(self, tour, name):
        if tour not in self.R: return None
        k = norm(name)
        if k in self.idx[tour]: return self.idx[tour][k]
        parts = str(name).split()
        if len(parts) >= 2:
            last, f = norm("".join(parts[1:])), parts[0][:1]
            c = [x for x in self.R[tour]["players"] if norm(x).endswith(last) and x[:1] == f]
            if len(c) == 1: return c[0]
        return None

    def prob(self, tour, a, b, surface="Hard", best_of=3, tourney=None, today=None):
        R = self.R[tour]; P = R["players"]
        A, B = P.get(a), P.get(b)
        if A is None or B is None: return None
        today = today or dt.date.today()
        days = lambda d: (today - dt.date.fromisoformat(d)).days if d else None
        lay = lambda X: math.log1p(min(days(X["l"]) if X.get("l") else 400, 400))
        def injd(X): return sum(w * math.exp(-days(d) / 30) for d, w in X.get("ik", []) if days(d) is not None and days(d) <= 120)
        def fat(X):
            d = days(X.get("l"))
            if d is None: return (0, 0)
            if d <= 3: return ((X.get("lm") or 0) / 60, (X.get("pm") or 0) / 60 if X.get("pe") and days(X["pe"]) <= 12 else 0)
            if d <= 9: return (0, (X.get("tm") or 0) / 60)
            return (0, 0)
        same_year = today.year == int(str(R["updated"])[:4])
        first = lambda X: 0 if (same_year and surface in (X.get("ss") or [])) else 1
        shock = lambda X: 1 if X.get("ls") and surface not in X["ls"] and days(X["l"]) is not None and days(X["l"]) <= 10 else 0
        mar = lambda X: 1 if days(X["l"]) is not None and days(X["l"]) <= 3 and (X.get("lm") or 0) >= (150 if tour == "atp" else 130) else 0
        hang = lambda X: 1 if X.get("td") and days(X["td"]) <= 9 and X.get("l") == X["td"] else 0
        country = (R.get("home") or {}).get(tourney) if tourney else None
        speed = 0.0
        if tourney and tourney in R.get("speed", {}):
            h = R["speed"][tourney]; speed = h[max(h)]
        i = SI.get(surface, 0); bo5 = 1 if best_of == 5 else 0
        dO = (A["e"] - B["e"]) / 100; dS = (A["s"][i] - B["s"][i]) / 100
        ex = min(math.log1p(A["n"]), math.log1p(B["n"])) / math.log1p(200)
        mu = (R.get("mu") or {}).get(surface, 0.45)
        sg = lambda z: 1 / (1 + math.exp(-z))
        qa, qb = sg(mu + A.get("S", 0) - B.get("R", 0)), sg(mu + B.get("S", 0) - A.get("R", 0))
        pm2 = min(max(markov_match(qa, qb, best_of), 0.005), 0.995)
        x = {"d_overall": dO, "d_surface": dS, "d_overall_bo5": dO * bo5, "d_surface_bo5": dS * bo5, "d_overall_exp": dO * ex,
             "d_sr": (A["r"] - B["r"]) / 5, "d_layoff": lay(A) - lay(B), "d_rank": math.log1p(A.get("p") or 0) - math.log1p(B.get("p") or 0),
             "d_ace_speed": ((A.get("c") or 0) - (B.get("c") or 0)) / 3 * speed / 2, "d_hang": hang(A) - hang(B),
             "d_first_surf": first(A) - first(B) if surface in ("Clay", "Grass") else 0, "d_shock": shock(A) - shock(B),
             "d_ptselo": ((A.get("rp") or 1500) - (B.get("rp") or 1500)) / 100, "d_mov": ((A.get("g") or 1500) - (B.get("g") or 1500)) / 100,
             "d_pmin": fat(A)[0] - fat(B)[0], "d_wk": fat(A)[1] - fat(B)[1],
             "d_home": (float(A.get("ioc") == country) - float(B.get("ioc") == country)) if country else 0,
             "d_marathon": mar(A) - mar(B), "d_injd": injd(A) - injd(B), "d_pt2": math.log(pm2 / (1 - pm2))}
        z = sum(w * x.get(f, 0.0) for f, w in zip(R["features"], R["weights"]))
        return 1 / (1 + math.exp(-z))
