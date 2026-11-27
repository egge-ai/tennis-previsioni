# Previsioni tennis live

Sito di previsioni ATP e WTA che si aggiorna da solo, ogni 15 minuti, senza un computer acceso.
È un progetto **separato da Deuce**.

## Cosa fa

- **Ogni 15 minuti** (gratis, su GitHub):
  1. scarica i risultati nuovi da TennisMyLife (TML);
  2. se ci sono risultati nuovi, ricalcola i modelli ATP e WTA;
  3. legge le quote dei bookmaker (se hai inserito la chiave, vedi sotto);
  4. pubblica il sito aggiornato.
- **Il modello** usa: Elo generale e per superficie, Elo sui game vinti (quanto è netta una vittoria),
  punti in classifica, precedenti tra i due, servizio e risposta, giorni di stop, ritiri e forfait recenti,
  stanchezza (durata della partita precedente nel torneo; per la WTA anche le ore giocate la settimana
  prima) e velocità del campo, che si aggiorna anche durante il torneo.
- **Notizie**: ogni 30 minuti cerca su Google News (inglese, italiano, spagnolo, francese) infortuni,
  ritiri e forfait dei giocatori ancora in gara. Ogni avviso ha il link all'articolo e il pulsante
  "Applica al modello".
- **Proiezioni** per ogni partita: risultato in set, game totali e sopra/sotto, tie-break, ace attesi,
  durata, punti vinti al servizio. Sono calcolate punto per punto e tarate sulla probabilità di vittoria.
- **Problemi dell'ultimo minuto.** Nessuna fonte gratuita pubblica le notizie sugli infortuni in un
  formato leggibile da un programma. Il sito usa quindi tre segnali:
  - **quote che crollano**: se la probabilità di un giocatore scende di 10 punti o più in poche ore, compare un avviso;
  - **partita tolta dalle quote** prima dell'inizio: possibile ritiro o rinvio;
  - **ritiri e forfait** appena registrati da TML.

  In più, nella scheda "Condizioni" puoi segnalare tu un problema fisico appena lo sai: il modello lo
  tratta come un ritiro recente.
- **Quando ci sono le quote**, la previsione principale è quella del mercato, ripulita dal margine del
  bookmaker. Sulle 2.149 partite ATP del 2026 è stata più precisa del modello, e unirle al modello non
  aggiungeva nulla. Il modello resta accanto come confronto; quando non ci sono quote (qualificazioni,
  Challenger) decide lui.

## Verifica contro il mercato (Closing Line Value)

Per ogni partita con quote il sistema salva, in un archivio privato (non pubblicato):
la prima quota vista (apertura), l'ultima prima dell'inizio (chiusura) e la previsione del modello
congelata all'apertura, con la versione del modello. Quando arriva il risultato, la sezione
"Verifica dal vivo" del sito mostra log loss di modello, apertura e chiusura e il CLV, anche per nicchie
(prima partita stagionale su terra/erba, favoriti netti, partite equilibrate, forti disaccordi).

## Come metterlo online (una volta sola, circa 15 minuti)

1. **Crea un account GitHub** su github.com, se non lo hai.
2. **Crea un repository nuovo**: pulsante "+" in alto a destra → *New repository*.
   - Nome: `tennis-previsioni`
   - Visibilità: **Public**. È necessario per avere GitHub Pages e i minuti di Actions gratuiti.
   - Premi *Create repository*.
3. **Carica i file**: nella pagina del repository premi *uploading an existing file* e trascina
   **tutto il contenuto** della cartella `tennis-previsioni`, comprese le cartelle `.github`, `docs`, `pipeline`.
   Poi premi *Commit changes*.
   - Su Windows la cartella `.github` è "nascosta". Se non la vedi: in Esplora file → *Visualizza* → *Mostra* → *Elementi nascosti*.
4. **Attiva il sito**: *Settings* → *Pages* → alla voce *Source* scegli **GitHub Actions**.
5. **(Facoltativo ma consigliato) Attiva le quote**:
   - Registrati su the-odds-api.com. Il piano gratuito dà 500 crediti al mese, quello da 30 $ ne dà 20.000.
   - Copia la tua chiave (API key).
   - Nel repository: *Settings* → *Secrets and variables* → *Actions* → *New repository secret*.
     Nome: `ODDS_API_KEY`, valore: la tua chiave.
6. **Primo avvio**: scheda *Actions* → *Aggiorna previsioni* → *Run workflow*. Il primo giro scarica
   tutti gli anni e dura circa 5 minuti.
7. Il sito sarà su **https://TUO-NOME-UTENTE.github.io/tennis-previsioni/**

Da lì in poi si aggiorna da solo.

## Da sapere

- **Frequenza.** GitHub fa partire i lavori programmati "al meglio": nelle ore di traffico possono
  slittare di qualche minuto. Per un aggiornamento al secondo servirebbe un server a pagamento.
- **Crediti delle quote.** Il programma regola da solo la frequenza per non finire i crediti prima della
  fine del mese. Quando una partita sta per iniziare controlla più spesso. Con il piano gratuito, nei
  giorni con molti tornei le quote si aggiornano circa una volta ogni 1-2 ore; con il piano da 30 $ ogni 15 minuti.
- **Dati TML.** Il sito pubblica solo probabilità e punteggi calcolati, mai i file grezzi, che restano in
  una cache privata di GitHub. I termini di TennisMyLife permettono l'uso **personale e non commerciale**:
  niente pubblicità sul sito né funzioni a pagamento senza il loro permesso scritto.
- **File `wta_itf.csv.gz`.** Contiene le partite ITF e di qualificazione WTA 2010–giugno 2026 dall'archivio
  di Jeff Sackmann (licenza CC BY-NC-SA 4.0: uso non commerciale, citando la fonte). Va caricato nella cartella
  principale del repository: migliora le valutazioni delle giocatrici meno note. Se manca, il modello funziona lo stesso.
- **Stile di gioco.** I profili vengono dal Match Charting Project di Jeff Sackmann (CC BY-NC-SA 4.0) e sono
  già dentro la pagina: non serve caricare altri file. Sono solo descrittivi e non cambiano le probabilità.
- **Prova contro i bookmaker.** La pagina contiene solo i risultati aggregati della prova 2021–2026 su circa
  37.000 partite, non le quote.
- **Disattivazione automatica.** GitHub sospende i lavori programmati dei repository fermi da 60 giorni. Il
  progetto fa un piccolo salvataggio automatico il primo di ogni mese per evitarlo.
- **La sezione Coppa Davis** riguarda la Final 8 di Bologna 2026 e sparisce da sola dopo il 30 novembre.

## Impostazioni (`config.json`)

| Voce | Cosa fa | Predefinito |
|---|---|---|
| `odds.regions` | bookmaker di quale zona (`eu`, `uk`, `us`, `au`) | `eu` |
| `odds.min_interval_minutes` | controllo quote più frequente possibile | 15 |
| `odds.reserve_credits` | crediti da non toccare mai | 20 |
| `alerts.drop_points` | calo delle quote (in punti %) che fa scattare l'avviso | 10 |
| `alerts.window_hours` | finestra in cui misurare il calo | 6 |
| `alerts.vanish_hours` | avvisa se una partita sparisce dalle quote entro queste ore dall'inizio | 3 |

## Provarlo sul tuo computer (facoltativo)

```
pip install -r requirements.txt
python pipeline/download.py --mode full
python pipeline/train.py
python pipeline/live.py
```
Poi apri la cartella `docs` con un piccolo server: `python -m http.server --directory docs`, e vai su
http://localhost:8000.

## File

- `pipeline/download.py`: scarica i CSV TML in `cache/`
- `pipeline/model.py`: il modello (Elo, servizio/risposta, infortuni, stanchezza, velocità del campo)
- `pipeline/train.py`: addestra ATP e WTA e scrive `docs/data/ratings_*.json`
- `pipeline/live.py`: quote, avvisi, partite in programma → `docs/data/live.json`; archivio quote
- `pipeline/predict.py`: la previsione del modello (stessa formula del sito), per congelarla nell'archivio
- `pipeline/clv.py`: confronto con apertura e chiusura → `docs/data/clv.json`
- `docs/index.html`: il sito
- `.github/workflows/aggiorna.yml`: il lavoro automatico ogni 15 minuti
