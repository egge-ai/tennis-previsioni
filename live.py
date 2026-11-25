"""
Aggiornamento "dal vivo" (ogni 15 minuti):
  1. quote dei bookmaker (The Odds API) per le partite di tennis in programma, ripulite dal margine;
  2. allarmi: quote che crollano all'improvviso, partite tolte dalle quote prima dell'inizio,
     ritiri e forfait appena registrati da TML.
Rispetta il budget di crediti: la frequenza si adatta da sola ai crediti rimasti.

  ODDS_API_KEY=... python pipeline/live.py --cache cache --out docs/data --state state
  (senza chiave: niente quote, ma gli allarmi su ritiri e forfait funzionano lo stesso)
"""
import argparse, datetime as dt, glob, json, os, re, statistics, sys, unicodedata, urllib.request, urllib.parse
import pandas as pd

API = "https://api.the-odds-api.com/v4"
NOW = dt.datetime.now(dt.timezone.utc)
SLAMS = ["australian open", "french open", "roland garros", "wimbledon", "us open"]


def norm(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())


def iso(t): return t.isoformat(timespec="minutes").replace("+00:00", "Z")
def parse(t): return dt.datetime.fromisoformat(str(t).replace("Z", "+00:00"))


def http_json(path, params):
    mock = os.environ.get("ODDS_MOCK")
    if mock:                                            # prove senza internet
        data = json.load(open(mock))
        if path == "/sports/": return data["sports"], {"x-requests-remaining": "480"}
        return data["odds"].get(path.split("/")[2], []), {"x-requests-remaining": "479", "x-requests-last": "1"}
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{API}{path}?{q}", timeout=30) as r:
        return json.load(r), {k.lower(): v for k, v in r.headers.items()}


def surface_map(cache):
    """nome torneo (normalizzato) -> (nome TML, superficie), dai file dell'anno in corso e precedente."""
    m = {}
    for f in sorted(glob.glob(os.path.join(cache, "20*.csv")))[-6:]:
        try:
            d = pd.read_csv(f, usecols=["tourney_name", "surface"], low_memory=False).dropna()
        except Exception:
            continue
        for n, s in d.drop_duplicates("tourney_name").itertuples(index=False):
            k = norm(re.sub(r"\b(masters|open|championships?)\b", "", str(n), flags=re.I))
            if len(k) >= 4: m[k] = (n, s)
    return m


def guess_tourney(title, smap):
    t = norm(title)
    best = max((k for k in smap if k in t), key=len, default=None)
    if best: return smap[best]
    if "frenchopen" in t or "rolandgarros" in t: return ("Roland Garros", "Clay")
    if "wimbledon" in t: return ("Wimbledon", "Grass")
    return (None, "Hard")


def market_prob(ev, a, b):
    """probabilità di vittoria di a: mediana tra i bookmaker, dopo aver tolto il margine."""
    ps = []
    for bk in ev.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h": continue
            pr = {o["name"]: o["price"] for o in mk.get("outcomes", []) if o.get("price")}
            if a in pr and b in pr and pr[a] > 1 and pr[b] > 1:
                ia, ib = 1 / pr[a], 1 / pr[b]
                ps.append(ia / (ia + ib))
    return (statistics.median(ps), len(ps)) if ps else (None, 0)


def recent_injuries(cache, days=7):
    out = []
    for f in ["ongoing_tourneys.csv", "challenger_ongoing_tourneys.csv", "wta_ongoing_tourneys.csv",
              f"{NOW.year}.csv", f"{NOW.year}_wta.csv"]:
        p = os.path.join(cache, f)
        if not os.path.exists(p): continue
        d = pd.read_csv(p, low_memory=False)
        if "score" not in d: continue
        d = d[d["score"].astype(str).str.contains("RET|W/O|Walkover|DEF", case=False, na=False)]
        d["date"] = pd.to_datetime(d["tourney_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce")
        d = d[d["date"] >= pd.Timestamp(NOW.date()) - pd.Timedelta(days=days)]
        for r in d.itertuples():
            kind = "forfait" if re.search("W/O|Walkover", str(r.score), re.I) else "ritiro"
            out.append({"type": kind, "player": r.loser_name, "tour": "wta" if "wta" in f else "atp",
                        "text": f"{r.loser_name}: {kind} contro {r.winner_name} ({r.tourney_name}, {r.date:%d/%m})",
                        "date": r.date.strftime("%Y-%m-%d")})
    uniq = {(o["player"], o["date"]): o for o in out}
    return sorted(uniq.values(), key=lambda o: o["date"], reverse=True)


# ------------------------------------------------------------------ notizie
NEWS_WORDS = ('injury OR injured OR withdraws OR withdrawal OR "pulls out" OR retires OR illness OR '
              'infortunio OR infortunato OR forfait OR ritiro OR "dà forfait" OR '
              'lesión OR lesionado OR baja OR retirada OR blessure OR blessé OR abandon')
STRONG = re.compile(r"withdr|pulls? out|forfait|ritir|retir(es|ed|ement from)|out of|abandon|baja|se retira|déclare forfait|won.t play", re.I)
INJ = re.compile(r"injur|infortun|lesi[oó]n|bless|illness|sick|malat|enferm|pain|dolor|dolore|strain|tear|cramp|problem|in dubbio|doubt|fitness|duda|incertain", re.I)
NEG = re.compile(r"return|torna|rientr|recover|guarit|back from|comeback|vuelve|retour|healthy|fit again", re.I)


def players_to_watch(out_dir, cache, matches, limit=40):
    """giocatori nelle partite con quote + i più forti ancora in gara nei tornei in corso."""
    names = {m["a"] for m in matches} | {m["b"] for m in matches}
    elo = {}
    for t in ("atp", "wta"):
        p = os.path.join(out_dir, f"ratings_{t}.json")
        if os.path.exists(p):
            elo.update({k: v["e"] for k, v in json.load(open(p, encoding="utf-8"))["players"].items()})
    alive = set()
    for f in ["ongoing_tourneys.csv", "challenger_ongoing_tourneys.csv", "wta_ongoing_tourneys.csv"]:
        p = os.path.join(cache, f)
        if not os.path.exists(p): continue
        d = pd.read_csv(p, low_memory=False)
        if d.empty or "winner_name" not in d: continue
        for _, g in d.groupby("tourney_id"):
            alive |= set(g["winner_name"]) - set(g["loser_name"])
    alive = sorted(alive, key=lambda n: -elo.get(n, 0))[:limit]
    return sorted(names | set(alive))


def fetch_news(names, state, every_min=30):
    """Google News RSS: cerca notizie su infortuni/ritiri dei giocatori, al massimo ogni 30 minuti."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    last = parse(state["news_poll"]) if state.get("news_poll") else None
    if os.environ.get("NEWS_MOCK"):
        feeds = json.load(open(os.environ["NEWS_MOCK"]))
    elif last and (NOW - last).total_seconds() / 60 < every_min - 1:
        return state.get("news", [])
    else:
        feeds = []
        for i in range(0, len(names), 6):
            batch = names[i:i + 6]
            q = "(" + " OR ".join(f'"{n}"' for n in batch) + ") (" + NEWS_WORDS + ") when:2d"
            for hl, gl, ceid in (("en-US", "US", "US:en"), ("it", "IT", "IT:it")):
                url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": hl, "gl": gl, "ceid": ceid})
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (tennis-previsioni)"})
                    with urllib.request.urlopen(req, timeout=20) as r:
                        feeds.append(r.read().decode("utf-8", "ignore"))
                except Exception as e:
                    print("  notizie non lette:", e, file=sys.stderr)
    items = {}
    for xml in feeds:
        try:
            root = ET.fromstring(xml)
        except Exception:
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip(); link = it.findtext("link") or ""
            try: when = parsedate_to_datetime(it.findtext("pubDate"))
            except Exception: continue
            if (NOW - when).total_seconds() > 48 * 3600 or NEG.search(title): continue
            strong, inj = bool(STRONG.search(title)), bool(INJ.search(title))
            if not (strong or inj): continue
            who = [n for n in names if norm(n.split()[-1]) in norm(title) and (len(n.split()[-1]) > 3 or norm(n) in norm(title))]
            if not who: continue
            src = it.findtext("source") or ""
            for n in who[:2]:
                items[(n, link)] = {"kind": "news", "type": "assenza" if strong else "fisico", "player": n, "url": link,
                                    "date": when.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                                    "text": f"{n}: «{title}»" + (f" ({src})" if src else "")}
    news = sorted(items.values(), key=lambda o: o["date"], reverse=True)[:25]
    state["news_poll"], state["news"] = iso(NOW), news
    return news


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="cache"); ap.add_argument("--out", default="docs/data"); ap.add_argument("--state", default="state")
    ap.add_argument("--config", default="config.json")
    a = ap.parse_args()
    cfg = json.load(open(a.config)) if os.path.exists(a.config) else {}
    oc, al = cfg.get("odds", {}), cfg.get("alerts", {})
    os.makedirs(a.out, exist_ok=True); os.makedirs(a.state, exist_ok=True)
    sp = os.path.join(a.state, "odds_state.json")
    state = json.load(open(sp)) if os.path.exists(sp) else {"hist": {}, "events": {}}
    key = os.environ.get("ODDS_API_KEY") or (os.environ.get("ODDS_MOCK") and "mock")

    alerts = [dict(o, kind="tml") for o in recent_injuries(a.cache)]
    status, matches = "nessuna chiave: quote non attive", list(state.get("events", {}).values())

    if key:
        last = parse(state["last_poll"]) if state.get("last_poll") else None
        remaining = state.get("remaining")
        sports, _ = http_json("/sports/", {"apiKey": key})            # gratis
        keys = [s for s in sports if s["key"].startswith(tuple(oc.get("prefixes", ["tennis_atp", "tennis_wta"]))) and s.get("active")]
        cost = max(1, len(keys)) * len(oc.get("regions", "eu").split(","))
        # quanto spesso posso interrogare per non finire i crediti prima della fine del mese
        month_end = (NOW.replace(day=28) + dt.timedelta(days=4)).replace(day=1, hour=0, minute=0)
        mins_left = (month_end - NOW).total_seconds() / 60
        reserve = oc.get("reserve_credits", 20)
        if remaining is None: interval = oc.get("min_interval_minutes", 15)
        elif remaining - reserve < cost: interval = 10 ** 9
        else: interval = max(oc.get("min_interval_minutes", 15), mins_left / ((remaining - reserve) / cost))
        soon = any(0 <= (parse(e["commence"]) - NOW).total_seconds() / 60 <= 90 for e in matches)
        if soon and remaining and remaining - reserve > cost * 20:
            interval = oc.get("min_interval_minutes", 15)            # partita imminente: controllo più spesso
        due = last is None or (NOW - last).total_seconds() / 60 >= interval - 1
        status = f"quote attive · prossimo controllo tra ~{int(min(interval, 9999))} min" if interval < 10 ** 8 else "crediti quasi finiti: quote in pausa"
        if due and interval < 10 ** 8:
            fresh = {}
            for s in keys:
                evs, hd = http_json(f"/sports/{s['key']}/odds/", {"apiKey": key, "regions": oc.get("regions", "eu"),
                                                                   "markets": "h2h", "oddsFormat": "decimal"})
                if hd.get("x-requests-remaining"): remaining = float(hd["x-requests-remaining"])
                for ev in evs:
                    A, B = ev.get("home_team"), ev.get("away_team")
                    p, nb = market_prob(ev, A, B)
                    if p is None: continue
                    fresh[ev["id"]] = {"id": ev["id"], "sport": s["key"], "title": s.get("title", s["key"]),
                                       "tour": "wta" if "wta" in s["key"] else "atp", "commence": ev["commence_time"],
                                       "a": A, "b": B, "p_market": round(p, 4), "books": nb}
            # partite sparite dalle quote prima dell'inizio → possibile ritiro
            for eid, e in state.get("events", {}).items():
                if eid not in fresh:
                    mins = (parse(e["commence"]) - NOW).total_seconds() / 60
                    if 0 < mins <= al.get("vanish_hours", 3) * 60:
                        alerts.insert(0, {"kind": "odds", "type": "sparita", "tour": e["tour"], "player": None, "date": NOW.date().isoformat(),
                                          "text": f"{e['a']} – {e['b']} ({e['title']}) è stata tolta dalle quote {int(mins)} minuti prima dell'inizio: possibile ritiro o rinvio."})
            for eid, e in fresh.items():
                h = state["hist"].setdefault(eid, [])
                h.append([iso(NOW), e["p_market"]])
            state["events"], state["last_poll"], state["remaining"] = fresh, iso(NOW), remaining
            matches = list(fresh.values())
        # pulizia storico (48 ore)
        state["hist"] = {k: [x for x in v if (NOW - parse(x[0])).total_seconds() < 48 * 3600] for k, v in state["hist"].items()}
        state["hist"] = {k: v for k, v in state["hist"].items() if v}

    # quote che crollano: probabilità scesa di molto nelle ultime ore
    drop = al.get("drop_points", 10) / 100; win = al.get("window_hours", 6) * 3600
    smap = surface_map(a.cache)
    for e in matches:
        h = [x for x in state.get("hist", {}).get(e["id"], []) if (NOW - parse(x[0])).total_seconds() <= win]
        e["trend"] = [x[1] for x in h][-12:]
        if len(h) >= 2:
            hi, lo, cur = max(x[1] for x in h), min(x[1] for x in h), h[-1][1]
            for who, delta in ((e["a"], hi - cur), (e["b"], cur - lo)):
                if delta >= drop:
                    alerts.insert(0, {"kind": "odds", "type": "crollo", "tour": e["tour"], "player": who, "date": NOW.date().isoformat(),
                                      "text": f"Le quote di {who} sono peggiorate di {round(delta * 100)} punti nelle ultime ore ({e['title']}): possibile problema fisico o notizia dell'ultimo minuto."})
        tn, surf = guess_tourney(e["title"], smap)
        e["tourney"], e["surface"] = tn, surf
        e["best_of"] = 5 if e["tour"] == "atp" and any(x in e["title"].lower() for x in SLAMS) else 3

    matches = sorted([m for m in matches if parse(m["commence"]) > NOW - dt.timedelta(hours=4)], key=lambda m: m["commence"])
    try:
        news = fetch_news(players_to_watch(a.out, a.cache, matches), state, cfg.get("news", {}).get("every_minutes", 30))
    except Exception as e:
        print("  notizie: errore", e, file=sys.stderr); news = state.get("news", [])
    alerts = [x for x in alerts if x["kind"] == "odds"] + news + [x for x in alerts if x["kind"] == "tml"]
    out = {"generated": iso(NOW), "status": status, "credits_remaining": state.get("remaining"), "matches": matches, "alerts": alerts[:40]}
    json.dump(out, open(os.path.join(a.out, "live.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(state, open(sp, "w"), separators=(",", ":"))
    print(f"live.json: {len(matches)} partite, {len(alerts)} allarmi · {status}")


if __name__ == "__main__":
    main()
