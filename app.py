#!/usr/bin/env python3
"""Referto Minibasket v4 - solo libreria standard Python 3 (sqlite3 + http.server).
Avvio:  python3 app.py        (poi apre http://localhost:8000)
"""
import datetime, json, os, re, sqlite3, sys, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import pdfform

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("REFERTO_DB", os.path.join(HERE, "referto.db"))

# ---- Costanti configurabili ----
ON_COURT = 4          # giocatori in campo per squadra
MAX_PLAYERS = 24      # massimo giocatori per squadra (oltre 12 il PDF ha 2 fogli)
PLAYERS_PER_SHEET = 12   # righe giocatori del referto cartaceo
MAX_FOULS = 5         # limite falli personali
TEMPI = 6             # numero di tempi di default (configurabile per partita nel wizard)
MAX_TEMPI = 12        # fino a 12 periodi: il PDF usa un secondo foglio dal 7° periodo (primo foglio: 1-6 + supplementare)
OVERTIME_DEFAULT = True   # tempo supplementare previsto di default
YEAR_MIN = 2000
MIN_AGE = 5           # età minima degli atleti
YEAR_MAX = datetime.date.today().year - MIN_AGE   # anno di nascita massimo (2021 nel 2026)
MAX_POINTS_PER_EVENT = 3
POINT_VALUES = (1, 2, 3)   # un canestro vale solo 1, 2 o 3 punti

LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches(
  id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL,
  tempo INTEGER NOT NULL DEFAULT 1,
  phase TEXT NOT NULL DEFAULT 'lineup',   -- lineup | playing | ask_ot | finished
  category TEXT DEFAULT '', venue TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS teams(
  id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  side TEXT NOT NULL CHECK(side IN ('A','B')), name TEXT NOT NULL, UNIQUE(match_id, side));
CREATE TABLE IF NOT EXISTS players(
  id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  number INTEGER NOT NULL, first_name TEXT NOT NULL, last_name TEXT NOT NULL, birth_year INTEGER NOT NULL,
  UNIQUE(team_id, number));
CREATE TABLE IF NOT EXISTS onfield(
  match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE, tempo INTEGER NOT NULL,
  player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE, PRIMARY KEY(match_id,tempo,player_id));
CREATE TABLE IF NOT EXISTS subs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  tempo INTEGER NOT NULL, out_player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  in_player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  after_event_id INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS saved_teams(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, coach TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS saved_players(
  id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL REFERENCES saved_teams(id) ON DELETE CASCADE,
  number INTEGER NOT NULL, first_name TEXT NOT NULL, last_name TEXT NOT NULL, birth_year INTEGER NOT NULL, captain INTEGER NOT NULL DEFAULT 0,
  UNIQUE(team_id, number));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  tempo INTEGER NOT NULL, player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('points','foul')), value INTEGER NOT NULL DEFAULT 1,
  created TEXT NOT NULL);
"""
# Colonne aggiunte nella v4: migrazione sicura (ALTER TABLE solo se mancano) per i referto.db esistenti.
MIGRATIONS = {
    "matches": [("n_tempi", "INTEGER NOT NULL DEFAULT 4"), ("ot_enabled", "INTEGER NOT NULL DEFAULT 1"),
                ("ot_played", "INTEGER NOT NULL DEFAULT 0"), ("girone", "TEXT DEFAULT ''"), ("gara_n", "TEXT DEFAULT ''"),
                ("arbitri", "TEXT DEFAULT ''"), ("segnapunti", "TEXT DEFAULT ''"), ("cronometrista", "TEXT DEFAULT ''"),
                ("forfeit", "TEXT DEFAULT ''"), ("edit_tempo", "INTEGER NOT NULL DEFAULT 0"),
                ("resume_tempo", "INTEGER NOT NULL DEFAULT 0"), ("resume_phase", "TEXT DEFAULT ''"), ("mvp_player_id", "INTEGER")],
    "teams": [("coach", "TEXT DEFAULT ''")],
    "players": [("captain", "INTEGER NOT NULL DEFAULT 0")],
}

class ApiError(Exception):
    def __init__(self, msg, code=400): self.msg, self.code = msg, code

def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    c = db(); c.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have: c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    # dati gia' presenti: tutto in maiuscolo (idempotente)
    for table, cols in (("matches", ("category", "venue", "girone", "gara_n", "arbitri", "segnapunti", "cronometrista")),
                        ("teams", ("name", "coach")), ("players", ("first_name", "last_name"))):
        for r in c.execute(f"SELECT id,{','.join(cols)} FROM {table}").fetchall():
            for col in cols:
                v = r[col]
                if isinstance(v, str) and v != v.upper(): c.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (v.upper(), r["id"]))
    c.commit(); c.close()

# ---------- logica di calcolo ----------
def awarded(pa, pb, n_reg, upto):
    """Punti per periodo concluso (guida CSI): vittoria 3, parità 2, sconfitta 1. I supplementari non assegnano punti per periodo:
    la vincente ottiene +1 sul totale (13-12), vedi build_state/'result'."""
    ra, rb = [], []
    for k in range(len(pa)):
        if k >= upto or k >= n_reg: ra.append(None); rb.append(None); continue
        if pa[k] > pb[k]: ra.append(3); rb.append(1)
        elif pa[k] < pb[k]: ra.append(1); rb.append(3)
        else: ra.append(2); rb.append(2)
    return ra, rb

def is_under9(category):
    return bool(re.search(r"(?:\bU|UNDER)\s*-?\s*9\b", (category or "").upper()))

def needs_ot(s, upto, manual=False):
    """Supplementare da proporre (guida CSI): solo se dopo i periodi regolari i punti di periodo sono pari E il progressivo (canestri)
    e' pari; poi si ripete finche' un supplementare non designa la vincente. Mai per Under 9 (il pareggio e' ammesso) o forfait."""
    n = s["n_tempi"]
    if s["forfeit"] or s["under9"] or upto < n or (not manual and not s["ot_enabled"]): return False
    pa, pb = s["teams"]["A"]["period"], s["teams"]["B"]["period"]
    aw = awarded(pa[:n], pb[:n], n, n)
    if sum(x or 0 for x in aw[0]) != sum(x or 0 for x in aw[1]): return False
    if sum(pa[:n]) != sum(pb[:n]): return False
    return sum(pa[n:upto]) == sum(pb[n:upto])

def is_readonly(created):
    """Partita di un giorno precedente a oggi (data = data di creazione): solo consultazione."""
    return str(created)[:10] < datetime.date.today().isoformat()

def build_state(c, mid):
    m = c.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
    if not m: raise ApiError("Partita non trovata", 404)
    n = m["n_tempi"]; periods = n + (m["ot_played"] or 0)
    evs = [dict(r) for r in c.execute("SELECT * FROM events WHERE match_id=? ORDER BY id", (mid,))]
    onf = {}
    for r in c.execute("SELECT tempo,player_id FROM onfield WHERE match_id=? ORDER BY rowid", (mid,)):
        onf.setdefault(r["tempo"], []).append(r["player_id"])
    sub_rows = [dict(r) for r in c.execute("SELECT * FROM subs WHERE match_id=? ORDER BY id", (mid,))]
    # partecipanti per tempo = titolari + entrati dalla panchina; in campo ora = titolari con le sostituzioni applicate (stesso posto)
    part = {k: set(v) for k, v in onf.items()}
    court_ids = list(onf.get(m["tempo"], []))
    for sb in sub_rows:
        part.setdefault(sb["tempo"], set()).add(sb["in_player_id"])
        if sb["tempo"] == m["tempo"] and sb["out_player_id"] in court_ids:
            court_ids[court_ids.index(sb["out_player_id"])] = sb["in_player_id"]
    teams = {}
    for t in c.execute("SELECT * FROM teams WHERE match_id=?", (mid,)):
        players = []
        for p in c.execute("SELECT * FROM players WHERE team_id=? ORDER BY number, id", (t["id"],)):
            pts = [0]*periods; fl = [0]*periods; seq = [[] for _ in range(periods)]; foul_tempi = []
            for e in evs:
                if e["player_id"] != p["id"]: continue
                k = e["tempo"] - 1
                if e["kind"] == "points": pts[k] += e["value"]; seq[k].append(e["value"])
                else: fl[k] += e["value"]; foul_tempi.append(e["tempo"])
            players.append(dict(id=p["id"], number=p["number"], first_name=p["first_name"], last_name=p["last_name"],
                birth_year=p["birth_year"], captain=bool(p["captain"]), pts=pts, seq=seq, total=sum(pts), fouls_by_tempo=fl, fouls=sum(fl),
                foul_tempi=foul_tempi, entries=sorted(k for k, ids in part.items() if p["id"] in ids),
                fouled_out=sum(fl[:m["tempo"]]) >= MAX_FOULS,   # in modifica di un periodo passato contano solo i falli fino a quel periodo
                
                on_field=p["id"] in court_ids and m["phase"] == "playing"))
        ptot = [sum(p["pts"][k] for p in players) for k in range(periods)]
        prog, s = [], 0
        for x in ptot: s += x; prog.append(s)
        tf = [sum(p["fouls_by_tempo"][k] for p in players) for k in range(periods)]
        teams[t["side"]] = dict(id=t["id"], side=t["side"], name=t["name"], coach=t["coach"] or "", players=players,
                                period=ptot, progressivo=prog, team_fouls=tf, score=prog[-1])
    if m["phase"] == "finished": done = min(m["tempo"], periods)   # tempi effettivamente giocati (anche se la partita e' terminata prima)
    elif m["phase"] == "ask_ot": done = m["tempo"]
    else: done = m["tempo"] - 1
    aw = awarded(teams["A"]["period"], teams["B"]["period"], n, done)
    ff = (m["forfeit"] or "") if "forfeit" in m.keys() else ""
    forfeit = None
    if ff and m["phase"] == "finished":
        winner = {"A": "B", "B": "A"}.get(ff)
        if winner:   # tempi regolari non giocati: 3 punti al vincitore, 1 allo sconfitto (come una vittoria di tempo)
            for k in range(done, n):
                aw[0 if winner == "A" else 1][k] = 3; aw[1 if winner == "A" else 0][k] = 1
            text = f'Partita terminata: squadra {teams[ff]["name"]} senza giocatori sufficienti, vittoria a squadra {teams[winner]["name"]}'
        else: text = "Partita terminata: entrambe le squadre senza giocatori sufficienti (doppio forfait), nessuna vittoria assegnata"
        forfeit = dict(loser=ff, winner=winner, text=text)
    for side, a in zip("AB", aw):
        teams[side]["awarded"] = a
        teams[side]["awarded_total"] = sum(x for x in a if x)
    # risultato (guida CSI): punti per periodo; a parita' vince chi e' avanti nel progressivo (13-12); poi supplementari (13-12)
    under9 = is_under9(m["category"]); ot_n = m["ot_played"] or 0
    fa, fb = teams["A"]["awarded_total"], teams["B"]["awarded_total"]; winner = None; reason = None
    if forfeit: winner = forfeit["winner"]
    elif m["phase"] == "finished":
        if fa != fb: winner = "A" if fa > fb else "B"
        else:
            ra, rb = sum(teams["A"]["period"][:min(done, n)]), sum(teams["B"]["period"][:min(done, n)])
            oa, ob = sum(teams["A"]["period"][n:]), sum(teams["B"]["period"][n:])
            if ra != rb: winner, reason = ("A" if ra > rb else "B"), "progressivo"
            elif ot_n and oa != ob: winner, reason = ("A" if oa > ob else "B"), "supplementare"
            if winner:
                if winner == "A": fa += 1
                else: fb += 1
    teams["A"]["final"], teams["B"]["final"] = fa, fb
    result = dict(final=dict(A=fa, B=fb), winner=winner, reason=reason, tie=(m["phase"] == "finished" and winner is None and not (forfeit and not forfeit["winner"]) ),
                  dts=bool(ot_n), under9=under9, provisional=m["phase"] != "finished")
    pidmap = {p["id"]: (side, p) for side in "AB" for p in teams[side]["players"]}
    for e in evs:
        side, p = pidmap[e["player_id"]]
        e["side"] = side; e["number"] = p["number"]; e["name"] = f'{p["first_name"]} {p["last_name"]}'
    evp = {e["player_id"] for e in evs}
    for sd in "AB":
        for p in teams[sd]["players"]: p["locked"] = bool(p["entries"]) or p["id"] in evp
    order = list(onf.get(m["tempo"], []))
    for sb in sub_rows:
        if sb["tempo"] == m["tempo"] and sb["in_player_id"] not in order: order.append(sb["in_player_id"])
    bynum = lambda i: (pidmap[i][1]["number"], i)   # sempre ordinati per numero di maglia
    roster = {sd: sorted([i for i in order if pidmap[i][0] == sd], key=bynum) if m["phase"] == "playing" else [] for sd in "AB"}
    court = {sd: sorted([i for i in court_ids if i in {p["id"] for p in teams[sd]["players"]}], key=bynum) if m["phase"] == "playing" else [] for sd in "AB"}
    max_ev = evs[-1]["id"] if evs else 0
    subs = []
    for i, sb in enumerate(sub_rows):
        so, p_in = pidmap[sb["out_player_id"]], pidmap[sb["in_player_id"]]
        cur_t = sb["tempo"] == m["tempo"] and m["phase"] == "playing"
        subs.append(dict(id=sb["id"], tempo=sb["tempo"], side=so[0], out=sb["out_player_id"], inn=sb["in_player_id"],
                         out_name=f'#{so[1]["number"]} {so[1]["last_name"]}', in_name=f'#{p_in[1]["number"]} {p_in[1]["last_name"]}',
                         after_event_id=sb["after_event_id"], created=sb["created"],
                         undoable=cur_t and i == len(sub_rows) - 1 and sb["after_event_id"] == max_ev))
    st = dict(id=m["id"], created=m["created"], tempo=m["tempo"], phase=m["phase"], tempi_done=done, forfeit=forfeit, readonly=is_readonly(m["created"]), court=court, roster=roster, subs=subs,
                n_tempi=n, ot_enabled=bool(m["ot_enabled"]), has_ot=bool(m["ot_played"]), periods=periods,
                category=m["category"], venue=m["venue"],
                header=dict(category=m["category"] or "", venue=m["venue"] or "", girone=m["girone"] or "", gara_n=m["gara_n"] or "",
                            arbitri=m["arbitri"] or "", segnapunti=m["segnapunti"] or "", cronometrista=m["cronometrista"] or ""),
                teams=teams, events=evs, lineup={str(k): v for k, v in onf.items()},
                under9=under9, result=result,
                editing=(dict(tempo=m["edit_tempo"], resume_tempo=m["resume_tempo"], resume_phase=m["resume_phase"]) if m["edit_tempo"] else None))
    mv = next(((sd, p) for sd in "AB" for p in teams[sd]["players"] if p["id"] == m["mvp_player_id"]), None) if m["mvp_player_id"] else None
    st["mvp"] = dict(player_id=mv[1]["id"], side=mv[0], team=teams[mv[0]]["name"], number=mv[1]["number"], name=f'{mv[1]["first_name"]} {mv[1]["last_name"]}',
                     captain=mv[1]["captain"], points=mv[1]["total"]) if mv else None
    st["editable"] = list(range(1, done + 1)) if (not st["readonly"] and not st["editing"] and not forfeit) else []
    st["ot_stale"] = bool(m["phase"] == "finished" and m["ot_played"] and not forfeit and not needs_ot(st, n, True))
    st["can_ot"] = m["phase"] == "finished" and not st["readonly"] and needs_ot(st, m["tempo"], True)
    return st

def list_matches(c):
    out = []
    for m in c.execute("SELECT id FROM matches ORDER BY id DESC"):
        s = build_state(c, m["id"])
        out.append(dict(id=s["id"], created=s["created"], phase=s["phase"], tempo=s["tempo"], n_tempi=s["n_tempi"], has_ot=s["has_ot"],
                        A=s["teams"]["A"]["name"], B=s["teams"]["B"]["name"],
                        scoreA=s["teams"]["A"]["score"], scoreB=s["teams"]["B"]["score"], finalA=s["teams"]["A"]["final"], finalB=s["teams"]["B"]["final"], readonly=s["readonly"], forfeit=bool(s["forfeit"]), mvp=s["mvp"]))
    return out

# ---------- squadre salvate (copiate nelle partite, mai referenziate) ----------
def team_dict(c, r):
    pl = [dict(number=p["number"], first_name=p["first_name"], last_name=p["last_name"], birth_year=p["birth_year"], captain=bool(p["captain"]))
          for p in c.execute("SELECT * FROM saved_players WHERE team_id=? ORDER BY number", (r["id"],))]
    return dict(id=r["id"], name=r["name"], coach=r["coach"] or "", players=pl)

def list_teams(c):
    return [team_dict(c, r) for r in c.execute("SELECT * FROM saved_teams ORDER BY name")]

def save_team(c, tid, body):
    name, rows, coach = clean_team("salvata", body or {}, 1)
    dup = c.execute("SELECT id FROM saved_teams WHERE name=? AND id IS NOT ?", (name, tid)).fetchone()
    if dup: raise ApiError(f"Esiste già una squadra salvata con il nome {name}", 409)
    if tid is None: tid = c.execute("INSERT INTO saved_teams(name,coach) VALUES(?,?)", (name, coach)).lastrowid
    else:
        if not c.execute("SELECT 1 FROM saved_teams WHERE id=?", (tid,)).fetchone(): raise ApiError("Squadra non trovata", 404)
        c.execute("UPDATE saved_teams SET name=?, coach=? WHERE id=?", (name, coach, tid)); c.execute("DELETE FROM saved_players WHERE team_id=?", (tid,))
    c.executemany("INSERT INTO saved_players(team_id,number,first_name,last_name,birth_year,captain) VALUES(?,?,?,?,?,?)", [(tid,) + p for p in sorted(rows, key=lambda x: x[0])])
    return team_dict(c, c.execute("SELECT * FROM saved_teams WHERE id=?", (tid,)).fetchone())

# ---------- operazioni ----------
def clean_team(side, t, minp=None):
    name = str(t.get("name", "")).strip().upper()
    if not name: raise ApiError(f"Squadra {side}: inserisci il nome")
    pl = t.get("players") or []
    minp = ON_COURT if minp is None else minp
    if len(pl) < minp: raise ApiError(f"Squadra {side}: servono almeno {minp} giocatori")
    if len(pl) > MAX_PLAYERS: raise ApiError(f"Squadra {side}: massimo {MAX_PLAYERS} giocatori")
    seen, out = set(), []
    if sum(1 for p in pl if p.get("captain")) > 1: raise ApiError(f"Squadra {side}: un solo capitano (K) per squadra")
    for i, p in enumerate(pl, 1):
        fn, ln = str(p.get("first_name", "")).strip().upper(), str(p.get("last_name", "")).strip().upper()
        try: num = int(p.get("number")); yr = int(p.get("birth_year"))
        except (TypeError, ValueError): raise ApiError(f"Squadra {side}, giocatore {i}: numero di maglia e anno di nascita sono obbligatori")
        if not fn or not ln: raise ApiError(f"Squadra {side}, giocatore {i}: nome e cognome obbligatori")
        if not 0 <= num <= 99: raise ApiError(f"Squadra {side}, giocatore {i}: maglia tra 0 e 99")
        if not YEAR_MIN <= yr <= YEAR_MAX: raise ApiError(f"Squadra {side}, giocatore {i}: anno di nascita tra {YEAR_MIN} e {YEAR_MAX} (gli atleti devono avere almeno {MIN_AGE} anni)")
        if num in seen: raise ApiError(f"Squadra {side}: numero di maglia {num} duplicato")
        seen.add(num); out.append((num, fn, ln, yr, 1 if p.get("captain") else 0))
    return name, out, str(t.get("coach", "")).strip().upper()

def create_match(c, body):
    act = c.execute("SELECT id FROM matches WHERE phase!='finished' AND substr(created,1,10)>=? LIMIT 1", (datetime.date.today().isoformat(),)).fetchone()
    if act: raise ApiError("C'è già una partita in corso: terminala prima di crearne una nuova", 409)
    ta, tb = clean_team("A", body.get("A") or {}), clean_team("B", body.get("B") or {})
    try: n = int(body.get("n_tempi", TEMPI))
    except (TypeError, ValueError): raise ApiError("Numero di tempi non valido")
    if not 1 <= n <= MAX_TEMPI: raise ApiError(f"Numero di tempi da 1 a {MAX_TEMPI}")
    ot = 1 if body.get("ot_enabled", OVERTIME_DEFAULT) else 0
    g = lambda k: str(body.get(k, "")).strip().upper()
    cur = c.execute("INSERT INTO matches(created,category,venue,n_tempi,ot_enabled,girone,gara_n,arbitri,segnapunti,cronometrista) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), g("category"), g("venue"), n, ot, g("girone"), g("gara_n"), g("arbitri"), g("segnapunti"), g("cronometrista")))
    mid = cur.lastrowid
    for side, (name, pls, coach) in (("A", ta), ("B", tb)):
        tid = c.execute("INSERT INTO teams(match_id,side,name,coach) VALUES(?,?,?,?)", (mid, side, name, coach)).lastrowid
        c.executemany("INSERT INTO players(team_id,number,first_name,last_name,birth_year,captain) VALUES(?,?,?,?,?,?)",
                      [(tid,) + p for p in sorted(pls, key=lambda r: r[0])])
    return mid

def start_tempo(c, mid, body):
    s = build_state(c, mid)
    if s["phase"] != "lineup": raise ApiError("Il tempo non è in fase di scelta dei giocatori")
    for side in "AB":
        ids = body.get(side) or []
        if len(set(ids)) != ON_COURT: raise ApiError(f"Squadra {side}: scegli esattamente {ON_COURT} giocatori diversi")
        valid = {p["id"]: p for p in s["teams"][side]["players"]}
        for i in ids:
            if i not in valid: raise ApiError("Giocatore non appartenente alla squadra")
            if valid[i]["fouled_out"]: raise ApiError(f'{valid[i]["last_name"]} ha raggiunto {MAX_FOULS} falli: non può giocare')
    c.execute("DELETE FROM onfield WHERE match_id=? AND tempo=?", (mid, s["tempo"]))
    for side in "AB":
        for i in body[side]: c.execute("INSERT INTO onfield VALUES(?,?,?)", (mid, s["tempo"], i))
    c.execute("UPDATE matches SET phase='playing' WHERE id=?", (mid,))

def add_event(c, mid, body):
    s = build_state(c, mid)
    if s["phase"] != "playing": raise ApiError("Nessun tempo in corso")
    pid, kind = body.get("player_id"), body.get("kind")
    p = next((p for side in "AB" for p in s["teams"][side]["players"] if p["id"] == pid), None)
    if not p or not p["on_field"]: raise ApiError("Il giocatore non è in campo")
    if kind == "points":
        v = body.get("value")
        if isinstance(v, bool) or not isinstance(v, int) or v not in POINT_VALUES: raise ApiError("Un canestro vale solo 1, 2 o 3 punti")
    elif kind == "foul": v = 1
    else: raise ApiError("Tipo di evento non valido")
    c.execute("INSERT INTO events(match_id,tempo,player_id,kind,value,created) VALUES(?,?,?,?,?,?)",
              (mid, s["tempo"], pid, kind, v, datetime.datetime.now().strftime("%H:%M:%S")))

def delete_event(c, mid, eid):
    s = build_state(c, mid)
    if s["phase"] != "playing": raise ApiError("Si può annullare solo durante il tempo in corso")
    e = next((e for e in s["events"] if e["id"] == eid), None)
    if not e: raise ApiError("Evento non trovato", 404)
    if e["tempo"] != s["tempo"]: raise ApiError("Evento di un altro tempo")
    c.execute("DELETE FROM events WHERE id=?", (eid,))

def add_sub(c, mid, body):
    s = build_state(c, mid)
    if s["phase"] != "playing": raise ApiError("Nessun tempo in corso")
    pin, pout = body.get("in"), body.get("out")
    allp = {p["id"]: (sd, p) for sd in "AB" for p in s["teams"][sd]["players"]}
    if pin not in allp or pout not in allp or allp[pin][0] != allp[pout][0]: raise ApiError("Giocatori non validi")
    if not allp[pout][1]["on_field"]: raise ApiError("Il giocatore che esce non è in campo")
    if allp[pin][1]["on_field"]: raise ApiError("Il giocatore che entra è già in campo")
    if allp[pin][1]["fouled_out"]: raise ApiError(f'{allp[pin][1]["last_name"]} ha raggiunto {MAX_FOULS} falli: non può entrare')
    max_ev = s["events"][-1]["id"] if s["events"] else 0
    c.execute("INSERT INTO subs(match_id,tempo,out_player_id,in_player_id,after_event_id,created) VALUES(?,?,?,?,?,?)",
              (mid, s["tempo"], pout, pin, max_ev, datetime.datetime.now().strftime("%H:%M:%S")))

def undo_sub(c, mid, sid):
    s = build_state(c, mid)
    sb = next((x for x in s["subs"] if x["id"] == sid), None)
    if not sb: raise ApiError("Sostituzione non trovata", 404)
    if not sb["undoable"]: raise ApiError("Si può annullare solo l'ultima sostituzione, se dopo non è stato registrato altro")
    c.execute("DELETE FROM subs WHERE id=?", (sid,))

def check_forfeit(c, mid):
    """Una squadra con meno di ON_COURT giocatori schierabili (non usciti per falli) perde a tavolino: partita terminata."""
    s = build_state(c, mid)
    if s["phase"] == "finished" or s["editing"]: return
    lost = "".join(sd for sd in "AB" if sum(1 for p in s["teams"][sd]["players"] if not p["fouled_out"]) < ON_COURT)
    if not lost: return
    played = s["tempo"] if s["phase"] in ("playing", "ask_ot") else s["tempo"] - 1   # il tempo in corso conta come giocato
    c.execute("UPDATE matches SET phase='finished', tempo=?, forfeit=? WHERE id=?", (max(played, 0), lost, mid))

def update_roster(c, mid, body):
    s = build_state(c, mid)
    if s["phase"] == "finished": raise ApiError("La partita è terminata")
    cleaned = {}
    for side in "AB":
        t = body.get(side) or {}
        cleaned[side] = (clean_team(side, t, 1), [p.get("id") for p in (t.get("players") or [])])
    for side in "AB":
        (name, rows, coach), ids = cleaned[side]; cur = {p["id"]: p for p in s["teams"][side]["players"]}
        keep = {i for i in ids if i is not None}
        if keep - set(cur): raise ApiError(f"Squadra {side}: giocatore non valido")
        for pid, p in cur.items():
            if pid not in keep and p["locked"]:
                raise ApiError(f'Squadra {side}: {p["last_name"]} {p["first_name"]} non può essere rimosso (ha già punti, falli o partecipazione ai tempi)')
    for side in "AB":
        (name, rows, coach), ids = cleaned[side]; tid = s["teams"][side]["id"]
        cur = {p["id"] for p in s["teams"][side]["players"]}
        for pid in cur - {i for i in ids if i is not None}: c.execute("DELETE FROM players WHERE id=?", (pid,))
        c.execute("UPDATE teams SET name=?, coach=? WHERE id=?", (name, coach, tid))
        for pid in ids:
            if pid is not None: c.execute("UPDATE players SET number=-id WHERE id=?", (pid,))   # evita conflitti UNIQUE negli scambi di maglia
        for pid, (num, fn, ln, yr, cap) in zip(ids, rows):
            if pid is not None: c.execute("UPDATE players SET number=?,first_name=?,last_name=?,birth_year=?,captain=? WHERE id=?", (num, fn, ln, yr, cap, pid))
            else: c.execute("INSERT INTO players(team_id,number,first_name,last_name,birth_year,captain) VALUES(?,?,?,?,?,?)", (tid, num, fn, ln, yr, cap))
    check_forfeit(c, mid)

def end_tempo(c, mid):
    s = build_state(c, mid)
    if s["phase"] != "playing": raise ApiError("Nessun tempo in corso")
    n, t = s["n_tempi"], s["tempo"]
    if s["editing"]: return restore_edit(c, mid)
    if t < n: c.execute("UPDATE matches SET phase='lineup', tempo=tempo+1 WHERE id=?", (mid,))
    elif needs_ot(s, t): c.execute("UPDATE matches SET phase='ask_ot' WHERE id=?", (mid,))   # parita' di punti e di progressivo: propone il supplementare
    else: c.execute("UPDATE matches SET phase='finished' WHERE id=?", (mid,))

def restore_edit(c, mid):
    """Fine modifica di un periodo passato: si torna alla situazione precedente (tempo e fase), con i totali ricalcolati."""
    m = c.execute("SELECT resume_tempo,resume_phase FROM matches WHERE id=?", (mid,)).fetchone()
    c.execute("UPDATE matches SET tempo=?, phase=?, edit_tempo=0, resume_tempo=0, resume_phase='' WHERE id=?", (m["resume_tempo"], m["resume_phase"], mid))
    s = build_state(c, mid)
    if s["phase"] == "ask_ot" and not needs_ot(s, s["tempo"]):   # dopo la modifica non c'e' piu' parita': niente supplementare
        c.execute("UPDATE matches SET phase='finished' WHERE id=?", (mid,))
    elif s["phase"] == "finished" and not s["forfeit"] and needs_ot(s, s["tempo"]):   # la modifica ha creato una parita' totale: si ripropone il supplementare
        c.execute("UPDATE matches SET phase='ask_ot' WHERE id=?", (mid,))

def reopen_tempo(c, mid, body):
    """Modifica di un periodo gia' concluso: TUTTI i dati salvati per quel periodo (formazione, entrate, sostituzioni, canestri, falli)
    vengono cancellati; si riparte dalla scelta dei giocatori. Il periodo in corso (o la fase) viene ripreso alla fine."""
    s = build_state(c, mid)
    try: k = int(body.get("tempo"))
    except (TypeError, ValueError): raise ApiError("Periodo non valido")
    if s["editing"]: raise ApiError("C'è già una modifica di periodo in corso: terminala prima")
    if s["forfeit"]: raise ApiError("Partita terminata per forfait: non modificabile")
    if k not in s["editable"]: raise ApiError("Periodo non modificabile")
    c.execute("DELETE FROM events WHERE match_id=? AND tempo=?", (mid, k))
    c.execute("DELETE FROM subs WHERE match_id=? AND tempo=?", (mid, k))
    c.execute("DELETE FROM onfield WHERE match_id=? AND tempo=?", (mid, k))
    c.execute("UPDATE matches SET edit_tempo=?, resume_tempo=tempo, resume_phase=phase, tempo=?, phase='lineup' WHERE id=?", (k, k, mid))

def set_mvp(c, mid, body):
    """MVP della partita (scelto dall'allenatore): un solo giocatore, di una delle due squadre; player_id nullo = rimuovi."""
    s = build_state(c, mid)
    if s["phase"] != "finished": raise ApiError("L'MVP si sceglie a partita conclusa")
    pid = body.get("player_id")
    if pid is not None:
        if isinstance(pid, bool) or not isinstance(pid, int) or not any(p["id"] == pid for sd in "AB" for p in s["teams"][sd]["players"]):
            raise ApiError("Giocatore non valido")
    c.execute("UPDATE matches SET mvp_player_id=? WHERE id=?", (pid, mid))

def update_settings(c, mid, body):
    """Impostazioni partita modificabili in ogni momento (non per partite di giorni precedenti, forfait o con modifica periodo aperta).
    - Aumentare i periodi su una partita conclusa (o in attesa di supplementare) la riapre: scelta giocatori del primo periodo nuovo.
      I supplementari gia' giocati che rientrano nei nuovi periodi diventano periodi regolari (i loro punti restano); gli altri restano supplementari.
    - Diminuire i periodi e' consentito solo se i periodi tolti sono vuoti e non ci sono supplementari: niente perdita di dati (altrimenti errore).
    - Supplementare on/off e intestazione: sempre; il risultato e il PDF si ricalcolano."""
    s = build_state(c, mid)
    if s["forfeit"]: raise ApiError("Partita chiusa per forfait: impostazioni non modificabili")
    if s["editing"]: raise ApiError("Termina prima la modifica del periodo in corso")
    n0, ot0 = s["n_tempi"], c.execute("SELECT ot_played FROM matches WHERE id=?", (mid,)).fetchone()["ot_played"] or 0
    try: n1 = int(body.get("n_tempi", n0))
    except (TypeError, ValueError): raise ApiError("Numero di tempi non valido")
    if not 1 <= n1 <= MAX_TEMPI: raise ApiError(f"Numero di tempi da 1 a {MAX_TEMPI}")
    ot_en = 1 if body.get("ot_enabled", s["ot_enabled"]) else 0
    g = lambda k, cur: str(body.get(k, cur or "")).strip().upper()
    h = s["header"]; phase, tempo, total = s["phase"], s["tempo"], n0 + ot0
    if n1 < n0:
        used = tempo if phase in ("playing", "ask_ot", "finished") else tempo - 1
        if ot0 or n1 < used:
            raise ApiError(f"Non si può scendere a {n1} periodi: il periodo {total if ot0 else used} contiene già dati (usa «Modifica periodo» per correggerli). Si può ridurre solo se i periodi tolti sono ancora vuoti.")
    reopened = False
    if n1 > n0:
        ot1 = max(0, total - n1)
        c.execute("UPDATE matches SET ot_played=? WHERE id=?", (ot1, mid))
        done = s["tempi_done"]
        if phase in ("ask_ot", "finished") and tempo >= n0 and done < n1:
            if c.execute("SELECT 1 FROM matches WHERE phase!='finished' AND id!=? AND substr(created,1,10)>=? LIMIT 1", (mid, datetime.date.today().isoformat())).fetchone():
                raise ApiError("C'è un'altra partita in corso: terminala prima di riaprire questa")
            c.execute("UPDATE matches SET phase='lineup', tempo=? WHERE id=?", (done + 1, mid)); reopened = True
    c.execute("UPDATE matches SET n_tempi=?, ot_enabled=?, category=?, venue=?, girone=?, gara_n=?, arbitri=?, segnapunti=?, cronometrista=? WHERE id=?",
              (n1, ot_en, g("category", h["category"]), g("venue", h["venue"]), g("girone", h["girone"]), g("gara_n", h["gara_n"]),
               g("arbitri", h["arbitri"]), g("segnapunti", h["segnapunti"]), g("cronometrista", h["cronometrista"]), mid))
    s2 = build_state(c, mid)
    if s2["phase"] == "lineup" and not reopened and s2["tempo"] > s2["periods"] and s2["tempo"] > n1 and ot0 == 0 and n1 < n0:
        # periodi ridotti fino a quelli giocati: la partita e' finita (o propone il supplementare)
        c.execute("UPDATE matches SET phase=? WHERE id=?", ("ask_ot" if needs_ot(s2, n1) else "finished", mid))
        c.execute("UPDATE matches SET tempo=? WHERE id=?", (n1, mid))
    s2 = build_state(c, mid)
    if s2["phase"] == "ask_ot" and not needs_ot(s2, s2["tempo"]): c.execute("UPDATE matches SET phase='finished' WHERE id=?", (mid,))
    elif s2["phase"] == "finished" and not s2["forfeit"] and not reopened and needs_ot(s2, s2["tempo"]): c.execute("UPDATE matches SET phase='ask_ot' WHERE id=?", (mid,))
    return reopened

def finish_match(c, mid):
    s = build_state(c, mid)
    if s["editing"]:   # termina partita durante una modifica: si chiude la modifica e poi la partita
        restore_edit(c, mid); s = build_state(c, mid)
        if s["phase"] == "finished": return
    if s["phase"] == "finished": raise ApiError("La partita è già terminata")
    # termina partita = chiude il tempo in corso (se aperto) senza supplementare; i tempi non giocati restano vuoti
    played = s["tempo"] if s["phase"] in ("playing", "ask_ot") else s["tempo"] - 1
    c.execute("UPDATE matches SET phase='finished', tempo=? WHERE id=?", (max(played, 0), mid))

def decide_ot(c, mid, play):
    s = build_state(c, mid)
    if s["forfeit"]: raise ApiError("La partita è terminata per forfait")
    if s["phase"] == "ask_ot" or (play and s["can_ot"]):
        if play: c.execute("UPDATE matches SET phase='lineup', tempo=?, ot_played=ot_played+1 WHERE id=?", (s["periods"] + 1, mid))
        else: c.execute("UPDATE matches SET phase='finished' WHERE id=?", (mid,))
    else: raise ApiError("Il tempo supplementare non può essere aggiunto ora")

def make_pdf(s):
    return pdfform.make_pdf(s)

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    server_version = "Hooply/6"
    def log_message(self, *a): pass
    def _send(self, code, data, ctype="application/json", extra=None):
        if not isinstance(data, (bytes, bytearray)): data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype == "application/json" else ""))
        self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}
    def handle_any(self, method):
        path = urlparse(self.path).path
        try:
            if method == "GET" and path in ("/", "/index.html"):
                with open(os.path.join(HERE, "index.html"), "rb") as f: return self._send(200, f.read(), "text/html")
            if method == "GET" and path.startswith("/static/") and "/" not in path[8:] and ".." not in path:
                fp = os.path.join(HERE, "static", path[8:])
                if os.path.isfile(fp):
                    ct = {"png": "image/png", "ico": "image/x-icon", "json": "application/manifest+json"}.get(fp.rsplit(".", 1)[-1], "application/octet-stream")
                    with open(fp, "rb") as f: return self._send(200, f.read(), ct)
            if not path.startswith("/api/"): return self._send(404, {"error": "non trovato"})
            body = self._body() if method == "POST" else {}
            with LOCK:
                c = db()
                try:
                    r = self.route(c, method, path, body); c.commit()
                finally: c.close()
            if isinstance(r, tuple): return self._send(200, r[0], r[1], r[2])
            return self._send(200, r)
        except ApiError as e: return self._send(e.code, {"error": e.msg})
        except json.JSONDecodeError: return self._send(400, {"error": "JSON non valido"})
        except Exception as e:
            import traceback; traceback.print_exc(); return self._send(500, {"error": "errore interno: %s" % e})
    def route(self, c, m, path, body):
        if m == "GET" and path == "/api/config":
            return dict(on_court=ON_COURT, max_players=MAX_PLAYERS, per_sheet=PLAYERS_PER_SHEET, max_fouls=MAX_FOULS, tempi=TEMPI, max_tempi=MAX_TEMPI,
                        ot_default=OVERTIME_DEFAULT, year_min=YEAR_MIN, year_max=YEAR_MAX, min_age=MIN_AGE, max_points=MAX_POINTS_PER_EVENT)
        if path == "/api/matches":
            if m == "GET": return list_matches(c)
            if m == "POST": return build_state(c, create_match(c, body))
        if path == "/api/teams":
            if m == "GET": return list_teams(c)
            if m == "POST": return save_team(c, None, body)
        g = re.fullmatch(r"/api/teams/(\d+)(?:/(delete))?", path)
        if g and m == "POST":
            tid = int(g.group(1))
            if g.group(2):
                if not c.execute("DELETE FROM saved_teams WHERE id=?", (tid,)).rowcount: raise ApiError("Squadra non trovata", 404)
                return {"ok": True}
            return save_team(c, tid, body)
        g = re.fullmatch(r"/api/matches/(\d+)(?:/(\w+)(?:/(\d+))?)?", path)
        if g:
            mid, act, arg = int(g.group(1)), g.group(2), g.group(3)
            if m == "GET" and not act: return build_state(c, mid)
            if m != "GET":
                row = c.execute("SELECT created FROM matches WHERE id=?", (mid,)).fetchone()
                if row and is_readonly(row["created"]): raise ApiError("Partita di un giorno precedente: si può solo consultare (riepilogo, statistiche, PDF), non modificare", 403)
            if m == "GET" and act == "pdf":
                s = build_state(c, mid)
                if s["phase"] != "finished": raise ApiError("Il PDF è disponibile a fine partita (dopo l'ultimo tempo)")
                return make_pdf(s), "application/pdf", {"Content-Disposition": f'attachment; filename="referto-{mid}.pdf"'}
            if m == "POST" and act == "start_tempo": start_tempo(c, mid, body); return build_state(c, mid)
            if m == "POST" and act == "event": add_event(c, mid, body); check_forfeit(c, mid); return build_state(c, mid)
            if m == "POST" and act == "sub": add_sub(c, mid, body); return build_state(c, mid)
            if m == "POST" and act == "undo_sub" and arg: undo_sub(c, mid, int(arg)); return build_state(c, mid)
            if m == "POST" and act == "roster": update_roster(c, mid, body); return build_state(c, mid)
            if m == "POST" and act == "settings":
                rp = update_settings(c, mid, body); st = build_state(c, mid); st["reopened"] = rp; return st
            if m == "POST" and act == "mvp": set_mvp(c, mid, body); return build_state(c, mid)
            if m == "POST" and act == "reopen": reopen_tempo(c, mid, body); return build_state(c, mid)
            if m == "POST" and act == "finish": finish_match(c, mid); return build_state(c, mid)
            if m == "POST" and act == "end_tempo": end_tempo(c, mid); check_forfeit(c, mid); return build_state(c, mid)
            if m == "POST" and act == "overtime": decide_ot(c, mid, bool(body.get("play"))); check_forfeit(c, mid); return build_state(c, mid)
            if m == "POST" and act == "delete":
                build_state(c, mid); c.execute("DELETE FROM matches WHERE id=?", (mid,)); return {"ok": True}
            if m == "POST" and act == "undo" and arg: delete_event(c, mid, int(arg)); return build_state(c, mid)
        raise ApiError("non trovato", 404)
    def do_GET(self): self.handle_any("GET")
    def do_POST(self): self.handle_any("POST")

def main():
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8000))
    init_db()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://localhost:{port}"
    print(f"Referto Minibasket v4 in esecuzione su {url}  (DB: {DB_PATH})\nCtrl+C per fermare.")
    if "--no-browser" not in sys.argv and not os.environ.get("NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nChiuso.")

if __name__ == "__main__": main()
