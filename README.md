# HOOPLY – Every game, a report

(App locale per il referto Minibasket 5 contro 5; versione storica v4 sotto.)

App locale per compilare il referto: squadre e giocatori, tempi (configurabili) con tempo supplementare, punti e falli, progressivo, riepilogo e **PDF identico al foglio Excel**.
Serve solo **Python 3** (già presente sul Mac). Nessun pacchetto da installare, nessuna connessione internet.

## Avvio
```bash
cd referto-v2
python3 app.py
```
Si apre il browser su http://localhost:8000 (porta diversa: `python3 app.py 8080`; senza browser: `--no-browser`).
I dati sono nel file `referto.db` (SQLite) accanto all'app: per un backup basta copiarlo. Un `referto.db` creato con una versione precedente viene aggiornato da solo (nuove colonne aggiunte, dati intatti). Fermare con `Ctrl+C`.

## Come si usa
1. **Nuova partita** → procedura guidata. Passo 1 (Squadra A): **numero di tempi** (1–4, default 4), casella **tempo supplementare** (attiva di default), dati gara (categoria, girone, gara n., campo, arbitri, segnapunti, cronometrista), nome squadra e istruttore, poi per ogni giocatore maglia, nome, cognome, anno di nascita (dal 2000 fino a anno corrente − 5: gli atleti devono avere almeno 5 anni, 2021 nel 2026; il server rifiuta anni più recenti). Passo 2: Squadra B. Passo 3: conferma. Da 4 a 12 giocatori, maglie uniche.
2. **Inizia tempo** → scegli i 4 giocatori in campo per squadra (chi ha 5 falli non è selezionabile).
3. **Schermo diviso** A / B: tendina giocatore, +1 / +2 / +3 / Fallo (i punti si inseriscono solo con questi pulsanti: un canestro vale 1, 2 o 3; il server rifiuta altri valori). Ogni canestro resta registrato a parte ("2 2 1"). Registro eventi con annulla.
4. **Termina tempo** → si ricomincia dalla scelta dei giocatori. Finiti **tutti i tempi** l'app chiede: *"Vuoi aggiungere il tempo supplementare?"* Sì → si gioca come un tempo normale (scelta 4 giocatori, punti, termina); No → partita conclusa. Se la partita è già conclusa senza supplementare, resta il pulsante "Aggiungi tempo supplementare".
5. **Situazione riassuntiva** (pulsante in alto, sempre disponibile).
6. A fine partita **Scarica PDF**.

## Il PDF
È il tuo Excel (foglio `REF.5C5`) convertito in PDF cella per cella (A4 orizzontale, 1 pagina; il modello è in `template/referto_template.pdf`, l'originale in `template/referto_originale.xls`) con i dati scritti nelle stesse celle:
- intestazione (categoria, girone, gara, data, ora, campo, squadre, arbitri, segnapunti, cronometrista) e nome istruttore;
- per ogni giocatore: maglia, nome (anno), **entrate** (X per ogni tempo giocato), **falli** (numero del tempo in cui è stato commesso, rosso al 5°), e i **punti nelle 12 celle di ogni tempo, un canestro per cella** (es. 2 | 2 | 1);
- **falli di squadra** per tempo (crocette sulle caselle 1–5);
- **punteggio progressivo**: i punti raggiunti sono barrati e il totale a fine di ogni tempo è **evidenziato** (colore diverso per tempo): con 2, 4, 3 e 5 punti sono evidenziati 2, 6, 9, 14. Se un tempo non porta punti, il numero resta evidenziato con più colori;
- **punti assegnati** (3/2/1) cerchiati nelle celle del periodo; **punteggio finale**.
- **Tempo supplementare**: i punti assegnati vanno sulla riga *Gioco spareggio* (vince 3, perde 1); i canestri dei giocatori sono scritti nell'ultimo blocco tempo in celle azzurre (modalità compatta se non c'è spazio). Il progressivo lo evidenzia con un colore proprio.
- Se i canestri di un giocatore superano le 12 celle di un tempo, proseguono nelle celle del tempo successivo (grigio/corsivo); i totali restano per tempo reale.
Limiti rispetto al foglio: massimo 4 tempi (4 blocchi sul foglio); il foglio non ha una colonna per il totale di ogni giocatore, quindi non è stampato (lo vedi a video e nel riepilogo); sospensioni, tessera e firme restano vuote.

## Regole e costanti (inizio di `app.py`)
`ON_COURT` (4), `MAX_PLAYERS` (12), `MAX_FOULS` (5), `TEMPI` (4 di default), `MAX_TEMPI` (4), `OVERTIME_DEFAULT` (sì), `YEAR_MIN` (2000).
Progressivo = somma dei punti dei tempi fino a quello indicato. Punti assegnati: vittoria 3, pareggio 2, sconfitta 1 per tempo.

## Come è fatto il PDF (tecnico)
`pdfform.py` aggiunge i dati al PDF del modello con un *aggiornamento incrementale* (nuovo flusso di contenuto + font standard), solo libreria standard. La geometria delle celle (`template/layout.json`) è stata estratta una volta dall'Excel con `tools/extract_layout.py`.

## Test
`python3 test_e2e.py` (serve `pdfinfo` di poppler solo per il test: `brew install poppler`) prova migrazione DB, validazioni, tempi configurabili, supplementare sì/no, overflow, evidenziazioni 2-6-9-14 e che il PDF sia 1 pagina orizzontale.

## Novità v4.3

- **Wizard**: gli errori sono evidenziati in rosso sulla riga/campo sbagliato (con messaggio sotto la riga) oltre che nel riquadro in alto. Il bordo rosso sparisce appena si corregge il campo.
- **Fino a 24 giocatori per squadra** (`MAX_PLAYERS` in `app.py`). L'ordine dei giocatori è quello di inserimento nel wizard.
- **PDF a 2 fogli** se una squadra ha più di 12 giocatori: foglio 1 = primi 12 di ogni squadra, foglio 2 = i restanti. Intestazione, falli di squadra, progressivo, punti per tempo e punteggio finale sono ripetuti identici su entrambi i fogli (sono dati di partita); in alto c'è la scritta "Foglio 1 di 2 / 2 di 2". Con ≤12 giocatori resta 1 foglio.
- **Panchina** sotto ogni squadra nella schermata del tempo: il "+" chiede chi esce tra i giocatori in campo; entra al suo posto (stessa posizione in elenco/tendina). Chi ha 5 falli non può entrare. Canestri e falli di chi esce restano e contano in tutti i totali e nel progressivo.
- Le sostituzioni sono nel registro eventi e nel DB (tabella `subs`, creata in automatico, nessuna perdita di dati). Si può annullare l'ultima sostituzione (× o "Annulla ultimo") finché dopo non è stato registrato altro.
- Nel referto chi è entrato dalla panchina in un tempo ha la X nelle "Entrate" di quel tempo, come i titolari.

### Schermata del tempo (v4.4)
- Niente più tendina e pulsanti in alto: ogni giocatore in campo ha sulla riga i suoi pulsanti **+1 / +2 / +3 / Fallo** (grandi, per tablet).
- Chi viene sostituito resta nell'elenco "Giocatori del tempo" in grigio e disabilitato, con canestri e falli ancora visibili; chi entra si aggiunge come riga attiva. Se un giocatore sostituito rientra dalla panchina la sua riga si riattiva (nessun duplicato). Chi ha 5 falli ha i pulsanti disattivati.

### Maiuscolo (v4.5)
Tutti i campi di testo (nomi squadra, istruttore, nome/cognome, categoria, campo, girone, gara, arbitri, segnapunti, cronometrista) sono in MAIUSCOLO: a video mentre si scrive, e il server li salva comunque in maiuscolo. Al primo avvio i dati già nel database vengono convertiti, quindi anche i vecchi referti e il PDF escono in maiuscolo.

### Una partita alla volta (v4.6)
- Finché una partita non è terminata, "Nuova partita" è disattivato (anche nella lista) e il server rifiuta la creazione con errore 409: "C'è già una partita in corso: terminala prima di crearne una nuova". La partita in corso si può riaprire dalla lista.
- In alto compare "Termina partita": chiede conferma ("Il tempo in corso verrà chiuso (senza tempo supplementare) e non potrai più modificarla"). Alla conferma chiude il tempo aperto e segna la partita come terminata: punteggio e PDF contano solo i tempi giocati. Dopo, "Nuova partita" torna disponibile.

### Scelta dei giocatori del tempo (v4.7)
Niente più caselle da spuntare: sopra, per squadra, i giocatori scelti ("In campo") con un **−** per rimetterli in lista; sotto i "Disponibili" con un **+**. Quando ne sono scelti 4 i **+** si disattivano; chi ha 5 falli resta in lista con il **+** disattivato. "Inizia tempo" si attiva con 4 per squadra. Pulsanti grandi per il tablet.

### v4.8: conferme, modifica giocatori, forfait
- **Conferma prima di annullare**: annullare un canestro o un fallo (× o "Annulla ultimo") o una sostituzione chiede conferma e mostra cosa verrà tolto (es. "Annullare canestro da 3 punti di #2 MARIO2 ROSSI?").
- **Modifica giocatori** (pulsante in alto durante la partita): riapre la configurazione squadre (stesse validazioni, maiuscolo, errori sulla riga). Si possono aggiungere giocatori e correggere nome, anno e maglia; si possono rimuovere solo giocatori senza punti, falli o presenze nei tempi (altrimenti blocco con messaggio). Nessun dato registrato va perso; poi si torna alla partita. API: `POST /api/matches/<id>/roster`.
- **Forfait**: se una squadra ha meno di 4 giocatori schierabili (esclusi quelli con 5 falli) – al momento di scegliere la formazione, dopo un fallo o dopo una modifica giocatori – la partita termina subito con un avviso. Il tempo in corso conta come giocato. I tempi regolari non giocati vanno alla squadra vincitrice (3 punti; 1 a chi ha perso il forfait) e il punteggio dei canestri resta quello segnato. Doppio forfait: nessuna vittoria, nessun punto per i tempi non giocati. Il riepilogo, la schermata finale e il PDF (nota rossa in testata) riportano "Partita terminata: squadra X senza giocatori sufficienti, vittoria a squadra Y". Colonna `forfeit` aggiunta con migrazione automatica.

### v4.9: lista partite, statistiche, sola consultazione
- **Formazione**: il numero di maglia è un badge scuro ben visibile; cognome e nome in carattere normale e più piccolo.
- **Partita conclusa**: tolto "Nuova partita" dal corpo della pagina (resta quello in alto).
- **Elenco partite**: data `gg/mm/aaaa hh:mm`; per ogni partita conclusa il pulsante **Scarica referto** (PDF); pulsante **Statistiche** per tutte.
- **Sola consultazione**: la data che conta è quella di creazione della partita. Se è precedente a oggi la partita si può solo vedere (riepilogo, statistiche, PDF): il server risponde 403 "Partita di un giorno precedente…" a qualsiasi modifica (eventi, sostituzioni, annulla, formazione, modifica giocatori, termina, elimina). Una partita vecchia rimasta non terminata non blocca la creazione di una nuova.
- **Statistiche** (elenco partite, intestazione e schermata partita): grafici SVG senza librerie esterne (funziona offline): punti per giocatore impilati per tempo, falli di squadra per tempo, falli per giocatore per tempo, punti totali per squadra.

### v4.10: Statistiche a tutto schermo
La finestra Statistiche occupa tutto lo schermo (barra con "Chiudi", tasto Esc, scorrimento interno). Per ogni squadra: a sinistra l'elenco giocatori (colore, maglia, nome, punti e falli) che fa da legenda; a destra una torta per ogni tempo (supplementare incluso, se giocato) con i punti segnati da ogni giocatore, poi una torta riassuntiva del totale e le torte dei falli per tempo. Un tempo senza punti/falli mostra "Nessun punto"/"Nessun fallo"; se nessuna squadra ha commesso falli la sezione è sostituita da "Non sono stati commessi falli" (se solo una squadra non ne ha, una nota nella sua sezione). In fondo il grafico dei punti totali per squadra. Tutto in SVG, senza librerie esterne.

## v5: referto con il layout del campione (CSI "Pallacanestro Under 9 - Under 10 - Under 11")
Il PDF finale ora riproduce il referto cartaceo del campione (A4 orizzontale), generato da zero in vettoriale (`pdfcsi.py`, solo libreria standard, offline):
- testata con titolo e logo, dati gara (gara n°, categoria, girone, campo, data/ora, squadre A/B, arbitri);
- per squadra 12 righe: Anno, Tess, Nominativo, N°, **Entrate in gioco** (1-6, S: una X per periodo giocato), **Falli** (una X per fallo, 5 caselle), **Punti segnati** per periodo (1°-6° e Supplement.): ogni canestro e' scritto nella sua casella (8 per periodo; oltre le caselle prosegue nel periodo successivo in grigio, l'ultimo periodo si comprime); canestri del supplementare cerchiati;
- allenatore / aiuto / dirigente, sospensioni, **Punti Progressivi 1-120** con cerchiato il totale a fine di ogni periodo;
- tabella **Punti** per periodo (3-2-1 per A e B, cerchiato il punteggio assegnato), **Punteggio finale** (A, B, DTS NO/SI, squadra vincente, pareggio Under 9), refertista/cronometrista/firme arbitri;
- oltre 12 giocatori: secondo foglio con i restanti; forfait in rosso a pie' pagina; dati in blu e maiuscolo.
- Tempi configurabili ora da 1 a 6 (+ supplementare). Il vecchio modello Excel resta disponibile in `pdfform.make_pdf_excel`.
Confronto: `screenshot/confronto_referto.png`, anteprima: `screenshot/pdf_anteprima.png`.

### v5.1: dalla guida CSI (secondo campione)
- Le caselle per i canestri restano sempre visibili (anche per periodi senza punti o non giocati): niente piu' campiture grigie.
- Falli segnati con "p" (come da guida); punti per periodo segnati con X sul valore assegnato; progressivo con numeri raggiunti barrati e totale di periodo cerchiato; segno "\" quando i canestri sforano nel periodo successivo.
- "Punteggio finale" = somma dei punti per periodo (es. 14-10); il "Progressivo" riporta i canestri totali (es. 24-18).

## v6: regole della guida CSI, capitano, avviso 2° periodo
- **6 periodi di default** (configurabili 1-6). Resta il tasto +3.
- **Risultato (guida CSI):** punti per periodo 3/2/1 (parità 2-2); punteggio finale = somma dei punti per periodo. A parità di punti vince chi è avanti nel progressivo (canestri) e ottiene +1 (13-12 con 6 periodi). Se anche il progressivo è pari: tempi supplementari (ripetuti finché una squadra è avanti); la vincente ottiene +1 (13-12) e nel referto si segna DTS "SI". I supplementari non assegnano punti di periodo.
- **Quando si propone il supplementare:** solo a parità di punti di periodo E di progressivo, se "Prevedi supplementare" è attivo; mai in Under 9 (la categoria è riconosciuta dal campo Categoria: "UNDER 9", "U9", "U 9") dove il pareggio è ammesso e chiude la gara; mai dopo un forfait. Se si rifiuta resta pareggio, ma si può aggiungere il supplementare dopo ("Aggiungi tempo supplementare").
- Schermate aggiornate: partita conclusa, riepilogo (colonna Finale), statistiche (risultato finale), PDF (punteggio finale, squadra vincente con motivo, pareggio, DTS).
- **Capitano (K):** uno per squadra, facoltativo, tasto "K" per riga nel wizard e in "Modifica giocatori"; mostrato come "(K)" a video e nel PDF. Colonna `players.captain` aggiunta con migrazione sicura.
- **Avviso 2° periodo:** nella scelta dei giocatori del 2° periodo, se la squadra ha più di 7 atleti e si scelgono atleti già scesi in campo nel 1° mentre altri non hanno ancora giocato, compare un avviso (non bloccante) e una conferma prima di iniziare.

## v6.1: tooltip statistiche, evidenza parziali, link titolo
- **Statistiche**: passando il mouse (o toccando) su una fetta dei grafici compare "#numero NOME · punti in Tx su TOT totali (%)".
- **Parziale per tempo**: l'etichetta di ogni fetta è "punti nel tempo / totale del giocatore" + "% del tot."
- **Bug corretto**: "Statistiche" dall'elenco partite dava `Cannot read properties of null (reading 'phase')`: `showStats(m)` usava la variabile globale `M` (null nell'elenco) invece del parametro `m`.
- Il titolo "Referto Minibasket" è un link all'elenco partite.
- Controllo regressione in Chrome headless: `python test_ui.py` (serve playwright; partite conclusa, in corso, giorno precedente, mai iniziata; nessun errore in console).

## v6.2: tolte le statistiche falli
- Nel modale Statistiche non ci sono più i grafici dei falli per tempo, la nota "nessun fallo" e i conteggi falli negli elenchi giocatori: restano solo i punti. I falli restano registrati e visibili durante la partita e nel PDF.
- Screenshot: `16_statistiche_falli.png` sostituito da `16_statistiche_riepilogo.png`.

## v6.3: ordine per maglia, modifica periodi, input numero maglia
- **Ordine**: giocatori sempre per numero di maglia (numerico) in selezione, panchina, righe di gioco, statistiche, riepilogo e PDF. Nel wizard le righe vengono riordinate quando premi Avanti/Salva.
- **Selezione giocatori**: campo "N° maglia" + Invio/«Aggiungi». Errori in riga: numero non presente, già selezionato, non disponibile (5 falli), già 4 scelti.
- **Modifica periodo precedente** («Modifica periodo» a partita conclusa, «Modifica periodo precedente» durante la partita). Conferma con avviso: per quel periodo **tutti** i dati (formazione, entrate, sostituzioni, canestri, falli) vengono eliminati e si riparte dalla scelta giocatori. Non è possibile con partite di giorni precedenti (sola lettura) né con partite chiuse per forfait.
  - Alla fine della modifica («Conferma…», poi «Termina modifica») si torna dove si era: partita conclusa, tempo in corso (con i suoi dati intatti), scelta giocatori o proposta supplementare.
  - Punti di periodo, progressivo, punteggio finale e overflow nel PDF sono calcolati dagli eventi: si ricalcolano da soli, anche per i periodi successivi. Se la proposta di supplementare non serve più si passa a «conclusa»; se nasce una parità compare «Aggiungi tempo supplementare»; supplementari già giocati ma non più necessari: avviso, restano registrati.
  - Durante la modifica contano solo i falli fino a quel periodo; il forfait automatico è sospeso fino al termine; «Termina partita» chiude prima la modifica.
- Test: `test_e2e.py`, `test_ui.py`. Screenshot: `screenshot/sezioni/` (05, 18, 19 nuovi/aggiornati).

## v6.3.1: supplementare dopo «Termina modifica»
- Se una modifica di periodo su una partita conclusa crea una parità totale (punti di periodo e progressivo), ora si torna alla schermata «Giochi il tempo supplementare?» (prima restava «conclusa» con solo il pulsante «Aggiungi tempo supplementare»).
- Regola invariata (guida CSI): il supplementare si propone solo con parità di punti di periodo **e** di progressivo; se i punti di periodo sono pari ma il progressivo no, decide il progressivo (13-12). Mai per Under 9 o con supplementare disattivato.

## v6.4: fino a 12 periodi, statistiche sul totale del periodo, tabelle nella modale
- **Periodi**: da 1 a 12 (wizard e API). PDF: il foglio con i periodi 1-6 contiene sempre anche il Supplementare; i periodi 7-12 vanno in un altro foglio (colonne «7° Periodo»…, «Entrate in gioco» 7…12, tabella punti 3-2-1 dei periodi 7-12). Progressivo, punteggio finale, intestazione e falli sono ripetuti uguali su ogni foglio; i canestri che sforano dal 6° periodo proseguono nel 7° sul foglio successivo (segno «\»).
- **Fogli**: con più di 12 giocatori si moltiplicano: ordine = per ogni gruppo di periodi, giocatori 1-12 poi 13+ (es. 9 periodi e 15 giocatori = 4 fogli). «Foglio X di Y» in alto, con la nota «periodi 7-9, giocatori 13+».
- **Statistiche per periodo**: la fetta e la percentuale sono la quota sul totale dei punti segnati dalla squadra in quel periodo (10 punti, 6 del giocatore = 60%). Etichetta «6 / 10 · 60%», tooltip «#7 ROSSI · 6 punti su 10 nel T2 (60%)». Nessun punto: cerchio grigio «nessun punto segnato».
- **Tabelle** («Parziali e progressivo» e quelle per squadra della Situazione riassuntiva) in contenitore con scroll orizzontale: non escono più dalla modale (colonna Squadra fissa). Test in `test_ui.py` a 1280 e 768 px con 6 e 12 periodi + supplementare.

## v6.5: MVP
- In «Partita conclusa» l'allenatore sceglie l'MVP (menu con i giocatori di entrambe le squadre, «Assegna/Cambia MVP», «Rimuovi»). Uno solo per partita, di una delle due squadre. Salvato nel DB (colonna `matches.mvp_player_id`, migrazione automatica).
- Elenco partite: colonna MVP con coppa dorata (SVG inline, offline); il click apre una modale con coppa grande, numero, nome, squadra e punti.
- Partite di giorni precedenti: MVP in sola lettura (visibile, non modificabile). Endpoint: `POST /api/matches/<id>/mvp {player_id|null}`, solo a partita conclusa.

## v6.6: impostazioni partita modificabili
- Pulsante **Impostazioni** nella barra (durante la partita e a partita conclusa; non per partite di giorni precedenti, chiuse per forfait o con una «Modifica periodo» aperta): numero di tempi (1-12), supplementare on/off, categoria, campo, girone, gara n°, arbitri, segnapunti, cronometrista. Endpoint `POST /api/matches/<id>/settings`.
- **Aumentare i tempi** su una partita conclusa (o in attesa di supplementare) la **riapre**, dopo conferma: si torna alla scelta giocatori del primo tempo nuovo e si gioca normalmente; risultato, vincitore, eventuale supplementare e PDF (secondo foglio dal 7° periodo) si ricalcolano a fine tempo. Una partita chiusa in anticipo con «Termina partita» (prima dell'ultimo tempo) non si riapre da sola.
- **Supplementari già giocati**: se rientrano nei nuovi tempi diventano tempi regolari (i punti restano, ora assegnano punti di periodo 3-2-1); quelli oltre restano supplementari.
- **MVP**: resta assegnato (la conferma lo ricorda); va ricontrollato a fine partita.
- **Diminuire i tempi**: solo se i tempi tolti sono vuoti e non ci sono supplementari giocati; altrimenti errore (nessuna perdita di dati: usare «Modifica periodo»). Riducendo fino ai tempi già giocati la partita termina (o propone il supplementare se c'è parità).
- Attivando/disattivando il supplementare: in attesa-supplementare → conclusa (off); conclusa in parità → proposta (on).

## v6.7: gestione squadre
- **Squadre** (pulsante nella barra): elenco squadre salvate, creazione, modifica, eliminazione (con conferma). Nome (maiuscolo, univoco), istruttore, giocatori con maglia, nome, cognome, anno di nascita (almeno 5 anni), capitano K facoltativo; maglie diverse, da 1 a 24 giocatori, ordinati per maglia. Stesse validazioni del form partita.
- **Nuova partita**: per la squadra A e/o B il menu «Richiama squadra salvata» + «Richiama» compila nome, istruttore e giocatori (con le maglie salvate; chiede conferma se hai già inserito dati). Poi il wizard prosegue come prima e si possono modificare i giocatori per quella partita senza toccare la squadra salvata. «Salva come squadra» salva la squadra inserita nell'archivio.
- I dati sono **copiati** nella partita: eliminare o modificare una squadra salvata non cambia le partite esistenti.
- DB: tabelle `saved_teams` / `saved_players` create in automatico. API: `GET/POST /api/teams`, `POST /api/teams/<id>`, `POST /api/teams/<id>/delete`.

## v6.8: rebrand HOOPLY
- Nome: «HOOPLY – Every game, a report» (titolo pagina, intestazione con icona + HOOPLY + tagline, ancora link all'elenco partite).
- Icone in `static/` (favicon 32/64/ico, apple-touch-icon 180, 192/512, `manifest.json` con theme color #1d2b4f): aggiungibile alla schermata Home del tablet. Servite da `app.py` (`/static/...`). Per rigenerarle da un PNG: `python tools/make_icons.py icona.png` (Pillow).
- Il PDF ufficiale CSI non cambia.
