"""
Verifica dal vivo contro il mercato (Closing Line Value).

L'archivio state/odds_log.json contiene, per ogni partita con quote:
  - la prima quota vista (apertura) e l'ultima prima dell'inizio (chiusura), senza margine;
  - la previsione del modello CONGELATA al momento dell'apertura, con la versione del modello.
Quando TML pubblica il risultato, questo script calcola:
  - log loss di modello, apertura e chiusura sulle stesse partite;
  - CLV: se il modello vedeva un giocatore più forte di quanto dicesse l'apertura,
    la quota si è poi mossa verso il modello? (CLV positivo = il mercato ha dato ragione al modello)
Pubblica solo statistiche aggregate (docs/data/clv.json), mai le quote grezze.
"""
import datetime as dt, glob, json, math, os, re, unicodedata
import pandas as pd


def norm(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())


def results(cache):
    rows = []
    for f in glob.glob(os.path.join(cache, "20*.csv")) + glob.glob(os.path.join(cache, "*ongoing*.csv")):
        try:
            d = pd.read_csv(f, usecols=["tourney_date", "winner_name", "loser_name", "score"], low_memory=False)
        except Exception:
            continue
        rows.append(d)
    if not rows: return {}
    d = pd.concat(rows).dropna(subset=["winner_name", "loser_name"])
    d = d[~d["score"].astype(str).str.contains("W/O|Walkover", case=False, na=False)]
    out = {}
    for r in d.itertuples():
        out.setdefault(frozenset((norm(r.winner_name), norm(r.loser_name))), []).append((str(r.tourney_date)[:8], norm(r.winner_name)))
    return out


def ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def summarize(items):
    n = len(items)
    if n == 0: return {"n": 0}
    s = {"n": n,
         "logloss_modello": round(sum(ll(i["model_p"], i["y"]) for i in items) / n, 4),
         "logloss_apertura": round(sum(ll(i["open_p"], i["y"]) for i in items) / n, 4),
         "logloss_chiusura": round(sum(ll(i["close_p"], i["y"]) for i in items) / n, 4)}
    picks = [i for i in items if abs(i["model_p"] - i["open_p"]) >= 0.03]
    if picks:
        clv = [(i["close_p"] - i["open_p"]) * (1 if i["model_p"] > i["open_p"] else -1) for i in picks]
        s.update({"partite_con_disaccordo": len(picks), "clv_medio_punti": round(100 * sum(clv) / len(clv), 2),
                  "clv_positivo_pct": round(100 * sum(c > 0 for c in clv) / len(clv), 1)})
    return s


def run(cache="cache", state="state", out="docs/data"):
    p = os.path.join(state, "odds_log.json")
    if not os.path.exists(p): return
    log = json.load(open(p))
    res = results(cache)
    settled = []
    for e in log.values():
        if not e.get("close_p") or e.get("model_p") is None: continue
        k = frozenset((norm(e["a"]), norm(e["b"])))
        day = e["commence"][:10].replace("-", "")
        hit = [w for d0, w in res.get(k, []) if abs((dt.date(int(day[:4]), int(day[4:6]), int(day[6:8])) -
                                                    dt.date(int(d0[:4]), int(d0[4:6]), int(d0[6:8]))).days) <= 16]
        if not hit: continue
        y = 1 if hit[-1] == norm(e["a"]) else 0
        settled.append(dict(e, y=y))
    fav = lambda i: max(i["close_p"], 1 - i["close_p"])
    groups = {"tutte": settled,
              "ATP": [i for i in settled if i["tour"] == "atp"], "WTA": [i for i in settled if i["tour"] == "wta"],
              "prima partita stagione su terra/erba": [i for i in settled if i.get("first_surf")],
              "favorito netto (≥75%)": [i for i in settled if fav(i) >= 0.75],
              "partite equilibrate (<60%)": [i for i in settled if fav(i) < 0.60],
              "disaccordo modello-mercato ≥10 punti": [i for i in settled if abs(i["model_p"] - i["open_p"]) >= 0.10]}
    report = {"aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
              "in_archivio": len(log), "con_risultato": len(settled),
              "gruppi": {k: summarize(v) for k, v in groups.items()}}
    json.dump(report, open(os.path.join(out, "clv.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=1))
