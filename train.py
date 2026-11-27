"""
Ricalcola i modelli ATP e WTA dai CSV in cache/ e scrive i file per il sito in docs/data/.
Pubblica solo punteggi e probabilità derivati, mai i dati grezzi.

  python pipeline/train.py --cache cache --out docs/data
"""
import argparse, datetime as dt, io, json, os, sys, contextlib
sys.path.insert(0, os.path.dirname(__file__))
import model


def run(tour, cache, tmp):
    argv = ["model.py", "--tml", cache, "--tour", tour, "--test-from", str(dt.date.today().year), "--out", tmp]
    old, sys.argv = sys.argv, argv
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            model.main()
    finally:
        sys.argv = old
    log = buf.getvalue()
    print(log.split("Feature finali")[0][-900:])
    return json.load(open(os.path.join(tmp, f"ratings_{tour}.json"), encoding="utf-8"))


def clean(o):
    """sostituisce NaN/infinito con null: altrimenti il browser rifiuta l'intero file."""
    import math
    if isinstance(o, float): return o if math.isfinite(o) else None
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(v) for v in o]
    return o


def compact(R):
    P = {}
    for k, v in R["players"].items():
        if R["tour"] == "wta" and v["elo"] < (1400 if v["active"] else 1550): continue   # niente ITF minori: file più leggero
        o = {"e": round(v["elo"]), "n": v["n"], "s": [round(v["surface"][s]) for s in ["Hard", "Clay", "Grass"]],
             "a": int(v["active"]), "l": v["last"], "r": v["sr"], "c": v["ace"],
             "lm": v["lm"], "tm": v["tm"], "pm": v["pm"], "pe": v["pe"],
             "p": round(v["pts"]), "g": v["mov"], "ik": v["ik"], "td": v["td"], "ht": v["ht"], "rp": v["rp"], "S": v["S"], "R": v["R"], "ss": v["ss"], "ls": v["ls"],
             "ioc": v["ioc"], "sv": v["spw"], "rt": v["rpw"], "ar": v["acer"]}
        if v["inj"]: o["i"] = v["inj"]
        P[k] = o
    out = {k: R[k] for k in ["tour", "updated", "features", "weights", "calibration", "test"]}
    out["players"] = P
    out["home"] = R["home"]; out["mu"] = R["mu"]
    out["h2h"] = {k: v for k, v in R["h2h"].items() if sum(v) >= 2}; out["sec_per_point"] = R["sec_per_point"]
    out["speed"] = {k: v for k, v in R["court_speed"].items() if int(max(v)) >= dt.date.today().year - 2}
    out["court"] = {k: v for k, v in R.get("court_info", {}).items() if k in out["speed"]}
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cache", default="cache"); ap.add_argument("--out", default="docs/data")
    a = ap.parse_args()
    tmp = os.path.join(a.cache, "_model"); os.makedirs(tmp, exist_ok=True); os.makedirs(a.out, exist_ok=True)
    meta = {"trained": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")}
    for tour in ["atp", "wta"]:
        R = compact(run(tour, a.cache, tmp))
        # sicurezza: non sovrascrivere con un modello rotto
        if len(R["players"]) < 300 or R["calibration"][0]["n"] in (0, None):
            sys.exit(f"Modello {tour} sospetto ({len(R['players'])} giocatori): non pubblico.")
        json.dump(clean(R), open(os.path.join(a.out, f"ratings_{tour}.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        meta[tour] = {"updated": R["updated"], "players": len(R["players"])}
    json.dump(meta, open(os.path.join(a.out, "meta.json"), "w"), indent=1)
    print("OK", meta)


if __name__ == "__main__":
    main()
