"""
Scarica i CSV di TennisMyLife (TML) nella cartella cache/ (che NON va pubblicata: i termini TML
non permettono di ridistribuire i file grezzi).

  python pipeline/download.py --mode full     # tutti gli anni dal 2010 (una volta al giorno)
  python pipeline/download.py --mode live     # solo anno in corso + tornei in corso (ogni 15 minuti)
"""
import argparse, datetime as dt, os, sys, time, urllib.request, urllib.error

BASE = "https://stats.tennismylife.org/data/"
UA = {"User-Agent": "tennis-previsioni/1.0 (uso personale non commerciale)"}


def files_for(year):
    return [f"{year}.csv", f"{year}_challenger.csv", f"{year}_wta.csv", f"atp_quali/{year}_atp_quali.csv"]


def get(name, dest, tries=2):
    url = BASE + name
    path = os.path.join(dest, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                data = r.read()
            if len(data) < 50:
                raise ValueError("file vuoto")
            tmp = path + ".tmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, path)                       # sostituisce solo se il download è completo
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False                            # file che non esiste (es. anno senza quali)
            err = e
        except Exception as e:
            err = e
        time.sleep(3 * (k + 1))
    print(f"  ! non scaricato {name}: {err}", file=sys.stderr)
    return False


def code_changed(state_dir="state"):
    """se il programma del modello è cambiato, forza il ricalcolo anche senza risultati nuovi."""
    import hashlib
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1(b"".join(open(os.path.join(here, f), "rb").read() for f in ("model.py", "train.py") if os.path.exists(os.path.join(here, f)))).hexdigest()
    os.makedirs(state_dir, exist_ok=True)
    p = os.path.join(state_dir, "code_hash.txt")
    old = open(p).read().strip() if os.path.exists(p) else ""
    if h != old:
        if os.path.exists(os.path.join(state_dir, "data_hash.txt")): os.remove(os.path.join(state_dir, "data_hash.txt"))
        open(p, "w").write(h)
        print("Programma del modello aggiornato: ricalcolo forzato.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "live"], default="live")
    ap.add_argument("--dest", default="cache")
    ap.add_argument("--first", type=int, default=2010)
    a = ap.parse_args()
    code_changed()
    year = dt.date.today().year
    names = ["ongoing_tourneys.csv", "challenger_ongoing_tourneys.csv", "wta_ongoing_tourneys.csv"]
    years = range(a.first, year + 1) if a.mode == "full" else [year]
    for y in years:
        names += files_for(y)
    ok, fails = 0, 0
    for n in names:
        if get(n, a.dest): ok += 1; fails = 0
        else:
            fails += 1
            if ok == 0 and fails >= 3:
                sys.exit("Il sito TML non risponde: riprovo al prossimo giro, il sito resta com'era.")
    print(f"Scaricati {ok}/{len(names)} file in {a.dest}/")
    if not os.path.exists(os.path.join(a.dest, f"{year}.csv")):
        sys.exit("Manca il file dell'anno in corso: interrompo per non pubblicare dati vecchi.")


if __name__ == "__main__":
    main()
