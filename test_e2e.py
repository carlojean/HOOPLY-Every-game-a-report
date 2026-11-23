import json, os, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
port = 8765; db = tempfile.mktemp(suffix=".db")
env = dict(os.environ, REFERTO_DB=db, PORT=str(port), NO_BROWSER="1")
os.environ["REFERTO_DB"] = db
import app as appmod, pdfform

# ---- migrazione sicura di un vecchio referto.db (schema v2/v3, senza le colonne nuove) ----
old = sqlite3.connect(db)
old.executescript("""CREATE TABLE matches(id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL, tempo INTEGER NOT NULL DEFAULT 1,
 phase TEXT NOT NULL DEFAULT 'lineup', category TEXT DEFAULT '', venue TEXT DEFAULT '');
 CREATE TABLE teams(id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL, side TEXT NOT NULL, name TEXT NOT NULL);
 INSERT INTO matches(created,phase,tempo) VALUES('2026-01-01 10:00','finished',4);
 INSERT INTO teams(match_id,side,name) VALUES(1,'A','Vecchia A'),(1,'B','Vecchia B');""")
old.commit(); old.close()
appmod.init_db(); appmod.init_db()   # idempotente
c = sqlite3.connect(db); cols = {r[1] for r in c.execute("PRAGMA table_info(matches)")}
assert {"n_tempi", "ot_enabled", "ot_played", "girone", "arbitri"} <= cols
assert c.execute("SELECT n_tempi,ot_enabled,ot_played FROM matches WHERE id=1").fetchone() == (4, 1, 0)   # dati vecchi intatti
assert "coach" in {r[1] for r in c.execute("PRAGMA table_info(teams)")}
c = sqlite3.connect(db); assert c.execute("SELECT name FROM teams WHERE match_id=1 AND side='A'").fetchone()[0] == "VECCHIA A"; c.close()   # dati esistenti migrati in maiuscolo

srv = subprocess.Popen([sys.executable, os.path.join(HERE, "app.py")], env=env, stdout=subprocess.DEVNULL)
time.sleep(1)
B = f"http://127.0.0.1:{port}"
NOAUTOFIN = False
DEFAULT_TEMPI = False
def call(p, m="GET", b=None, raw=False):
    if p == "/api/matches" and m == "POST" and not NOAUTOFIN:   # una sola partita in corso alla volta: chiudo quelle aperte
        for x in json.loads(urllib.request.urlopen(B + "/api/matches").read()):
            if x["phase"] != "finished": call(f"/api/matches/{x['id']}/finish", "POST", {})
    if p == "/api/matches" and m == "POST" and isinstance(b, dict) and "n_tempi" not in b and not DEFAULT_TEMPI: b = dict(b, n_tempi=4)   # i vecchi test ragionano su 4 tempi
    req = urllib.request.Request(B+p, method=m, data=json.dumps(b).encode() if b is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req); d = r.read()
        return (r.status, d if raw else json.loads(d))
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
def team(n, k): return {"name": n, "players": [{"number": i+1, "first_name": f"N{i}", "last_name": f"{n}{i}", "birth_year": 2012+i%3} for i in range(k)]}
def pdfinfo(data, name, pages=1):
    path = os.path.join(tempfile.gettempdir(), name); open(path, "wb").write(data)
    out = subprocess.run(["pdfinfo", path], capture_output=True, text=True).stdout
    import re
    w, h = map(float, re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", out).groups())
    assert f"Pages:           {pages}" in out and abs(w - 841.89) < 0.5 and abs(h - 595.3) < 0.5 and w > h, out
    return path
def play(mid, t, la, lb, pa, pb, events):
    st, s = call(f"/api/matches/{mid}/start_tempo", "POST", {"A": [pa[i] for i in la], "B": [pb[i] for i in lb]}); assert st == 200, s
    for side, i, kind, v in events:
        st, s = call(f"/api/matches/{mid}/event", "POST", {"player_id": (pa if side == "A" else pb)[i], "kind": kind, "value": v}); assert st == 200, s
    return call(f"/api/matches/{mid}/end_tempo", "POST", {})
try:
    cfg = call("/api/config")[1]; assert cfg["year_max"] == 2026 - 5 == 2021 and cfg["min_age"] == 5 and cfg["on_court"] == 4 and cfg["tempi"] == 6 and cfg["ot_default"]
    # vecchia partita migrata ancora leggibile
    assert call("/api/matches/1")[1]["n_tempi"] == 4 and call("/api/matches/1")[1]["phase"] == "finished"
    # validazioni: anno di nascita 2000..(anno corrente-5); un atleta deve avere almeno 5 anni
    for yr, code in ((2021, 200), (2022, 400), (2026, 400), (1999, 400), (2000, 200)):
        tm = team("A", 5); tm["players"][0]["birth_year"] = yr
        st, r = call("/api/matches", "POST", {"A": tm, "B": team("B", 5)}); assert st == code, (yr, st, r)
        if code == 400: assert "almeno 5 anni" in r["error"] or "1999" in r["error"] or "anno" in r["error"]
    bad = team("A", 5); bad["players"][1]["number"] = 1
    assert call("/api/matches", "POST", {"A": bad, "B": team("B", 5)})[0] == 400
    assert call("/api/matches", "POST", {"A": team("A", 5), "B": team("B", 5), "n_tempi": 0})[0] == 400
    assert call("/api/matches", "POST", {"A": team("A", 5), "B": team("B", 5), "n_tempi": 13})[0] == 400
    assert call("/api/matches", "POST", {"A": team("A", 3), "B": team("B", 5)})[0] == 400

    # ===== Partita 1: 4 tempi (default) + supplementare accettato =====
    s = call("/api/matches", "POST", {"A": team("Aquile", 12), "B": team("Bisonti", 6), "category": "U13", "girone": "G1",
                                       "arbitri": "Rossi / Bianchi", "A_coach": 1})[1]
    mid = s["id"]; assert s["n_tempi"] == 4 and s["ot_enabled"] and not s["has_ot"]
    pa = [p["id"] for p in s["teams"]["A"]["players"]]; pb = [p["id"] for p in s["teams"]["B"]["players"]]
    assert call(f"/api/matches/{mid}/pdf")[0] == 400
    LA = {1: [0,1,2,3], 2: [4,1,2,3], 3: [1,2,3,4], 4: [4,1,2,3], 5: [1,2,3,4]}
    plan = {1: [("A",0,2),("A",1,3),("A",0,1),("A",2,2),("A",3,2),("B",0,2),("B",1,3)],
            2: [("A",4,3),("A",1,2),("B",2,3),("B",2,3),("B",3,2),("B",3,2)],
            3: [("A",1,2),("B",1,2)],
            4: [("A",2,3),("B",0,1),("B",1,2)]}
    for t in range(1, 5):
        s = call(f"/api/matches/{mid}")[1]; assert s["phase"] == "lineup" and s["tempo"] == t
        if t == 2: assert call(f"/api/matches/{mid}/start_tempo", "POST", {"A": [pa[i] for i in [0,1,2,3]], "B": pb[:4]})[0] == 400
        st, s = call(f"/api/matches/{mid}/start_tempo", "POST", {"A": [pa[i] for i in LA[t]], "B": pb[:4]}); assert st == 200, s
        assert call(f"/api/matches/{mid}/event", "POST", {"player_id": pa[11], "kind": "points", "value": 1})[0] == 400
        for bad_v in (0, 4, -1, 2.5, "2", None, True, 10):   # solo 1, 2, 3 sono ammessi
            assert call(f"/api/matches/{mid}/event", "POST", {"player_id": pb[0], "kind": "points", "value": bad_v})[0] == 400, bad_v
        for side, i, v in plan[t]:
            assert call(f"/api/matches/{mid}/event", "POST", {"player_id": (pa if side == "A" else pb)[i], "kind": "points", "value": v})[0] == 200
        if t == 1:
            s = call(f"/api/matches/{mid}/event", "POST", {"player_id": pa[0], "kind": "points", "value": 3})[1]
            assert s["teams"]["A"]["period"][0] == 13
            s = call(f"/api/matches/{mid}/undo/{s['events'][-1]['id']}", "POST", {})[1]
            assert s["teams"]["A"]["period"][0] == 10
            for _ in range(5): s = call(f"/api/matches/{mid}/event", "POST", {"player_id": pa[0], "kind": "foul"})[1]
            assert s["teams"]["A"]["players"][0]["fouled_out"] and s["teams"]["A"]["team_fouls"][0] == 5
            assert call(f"/api/matches/{mid}/event", "POST", {"player_id": pb[2], "kind": "foul"})[0] == 200
        st, s = call(f"/api/matches/{mid}/end_tempo", "POST", {}); assert st == 200
        assert call(f"/api/matches/{mid}/undo/1", "POST", {})[0] == 400
    # tutti i tempi conclusi -> l'app chiede se aggiungere il supplementare
    assert s["phase"] == "ask_ot" and s["periods"] == 4
    assert call(f"/api/matches/{mid}/pdf")[0] == 400                      # non ancora finita
    A = s["teams"]["A"]; Bt = s["teams"]["B"]
    assert A["progressivo"] == [10, 15, 17, 20] and Bt["progressivo"] == [5, 15, 17, 20]
    assert pdfform.highlights(A["progressivo"]) == [10, 15, 17, 20]
    st, s = call(f"/api/matches/{mid}/overtime", "POST", {"play": True}); assert st == 200
    assert s["phase"] == "lineup" and s["tempo"] == 5 and s["has_ot"] and s["periods"] == 5
    st, s = play(mid, 5, LA[5], [0,1,2,3], pa, pb, [("A",1,"points",3),("A",1,"points",1),("B",0,"points",2)])
    assert st == 200 and s["phase"] == "finished" and s["periods"] == 5
    A, Bt = s["teams"]["A"], s["teams"]["B"]
    assert A["period"] == [10,5,2,3,4] and A["progressivo"] == [10,15,17,20,24], A
    assert Bt["period"] == [5,10,2,3,2] and Bt["progressivo"] == [5,15,17,20,22]
    assert A["awarded"] == [3,1,2,2,None] and Bt["awarded"] == [1,3,2,2,None]
    assert A["players"][1]["seq"][4] == [3,1] and A["players"][1]["total"] == 3+2+2+0+4 + 0
    assert all(sum(q) == p["pts"][i] for T in (A, Bt) for p in T["players"] for i, q in enumerate(p["seq"]))
    assert call(f"/api/matches/{mid}/overtime", "POST", {"play": True})[0] == 400  # gia' giocato
    st, pdf = call(f"/api/matches/{mid}/pdf", "GET", None, True); assert st == 200 and pdf[:5] == b"%PDF-"
    esempio = pdfinfo(pdf, "esempio.pdf")

    # ===== Partita 2: 2 tempi, supplementare rifiutato =====
    s = call("/api/matches", "POST", {"A": team("Aquile", 5), "B": team("Bisonti", 5), "n_tempi": 2})[1]; m2 = s["id"]
    qa = [p["id"] for p in s["teams"]["A"]["players"]]; qb = [p["id"] for p in s["teams"]["B"]["players"]]
    st, s = play(m2, 1, [0,1,2,3], [0,1,2,3], qa, qb, [("A",0,"points",2),("B",0,"points",2)]); assert s["phase"] == "lineup" and s["tempo"] == 2
    st, s = play(m2, 2, [0,1,2,3], [0,1,2,3], qa, qb, [("A",0,"points",3),("B",0,"points",3)]); assert s["phase"] == "ask_ot" and s["periods"] == 2
    st, s = call(f"/api/matches/{m2}/overtime", "POST", {"play": False}); assert s["phase"] == "finished" and not s["has_ot"]
    assert s["teams"]["A"]["progressivo"] == [2, 5] and s["teams"]["A"]["awarded"] == [2, 2] and s["result"]["tie"] and s["result"]["final"] == {"A": 4, "B": 4}
    pdfinfo(call(f"/api/matches/{m2}/pdf", "GET", None, True)[1], "due_tempi.pdf")

    # ===== Partita 3: supplementare disattivato -> finisce subito =====
    s = call("/api/matches", "POST", {"A": team("A", 5), "B": team("B", 5), "n_tempi": 1, "ot_enabled": False})[1]; m3 = s["id"]
    ra = [p["id"] for p in s["teams"]["A"]["players"]]; rb = [p["id"] for p in s["teams"]["B"]["players"]]
    st, s = play(m3, 1, [0,1,2,3], [0,1,2,3], ra, rb, [("A",0,"points",1)]); assert s["phase"] == "finished"

    # ===== Partita 4: 15 canestri in un tempo (overflow nei tempi successivi) + esempio 2,4,3,5 -> 2,6,9,14 =====
    s = call("/api/matches", "POST", {"A": team("Aquile", 5), "B": team("Bisonti", 5), "ot_enabled": False})[1]; m4 = s["id"]
    qa = [p["id"] for p in s["teams"]["A"]["players"]]; qb = [p["id"] for p in s["teams"]["B"]["players"]]
    ev = {1: [("A",0,"points",2)], 2: [("A",1,"points",2),("A",1,"points",2)], 3: [("A",2,"points",3)], 4: [("A",3,"points",2)]*2 + [("A",3,"points",1)] + [("A",2,"points",2)]*0}
    ev[4] = [("A",3,"points",2),("A",3,"points",3)]
    ev[1] += [("A",0,"points",v) for v in [1,2,3,1,1,2,2,3,1,2,1,1,3,2]][0:0]
    for t in range(1, 5): st, s = play(m4, t, [0,1,2,3], [0,1,2,3], qa, qb, ev[t])
    assert s["phase"] == "finished" and s["teams"]["A"]["period"] == [2,4,3,5] and s["teams"]["A"]["progressivo"] == [2,6,9,14]
    assert pdfform.highlights(s["teams"]["A"]["progressivo"]) == [2,6,9,14]
    pdfinfo(call(f"/api/matches/{m4}/pdf", "GET", None, True)[1], "esempio_2_6_9_14.pdf")

    # overflow: un giocatore con 15 canestri nel 1° tempo + 20 nel 4° + supplementare
    s = call("/api/matches", "POST", {"A": team("Aquile", 5), "B": team("Bisonti", 5)})[1]; m5 = s["id"]
    qa = [p["id"] for p in s["teams"]["A"]["players"]]; qb = [p["id"] for p in s["teams"]["B"]["players"]]
    for t in range(1, 5):
        e = []
        if t == 1: e = [("A",0,"points",v) for v in [1,2,3,1,1,2,2,3,1,2,1,1,3,2,2]]
        if t == 4: e = [("A",1,"points",2)]*20
        s = play(m5, t, [0,1,2,3], [0,1,2,3], qa, qb, e)[1]
    import sqlite3 as _s5; _c = _s5.connect(db); _c.execute("UPDATE matches SET phase='lineup', tempo=5, ot_played=1 WHERE id=?", (m5,)); _c.commit(); _c.close()   # forzo il supplementare (qui A vince nettamente, non verrebbe proposto)
    s = play(m5, 5, [0,1,2,3], [0,1,2,3], qa, qb, [("A",1,"points",3)]*3)[1]
    p0 = s["teams"]["A"]["players"][0]; assert len(p0["seq"][0]) == 15 and p0["total"] == 27
    assert s["teams"]["A"]["progressivo"] == [27, 27, 27, 67, 76]
    for pl in s["teams"]["A"]["players"]:   # nessun canestro perso nella distribuzione sulle celle
        blocks = pdfform.blocks_for(pl["seq"], 4)
        shown = sorted(t for toks, _ in blocks for t, _ in toks)
        assert shown == sorted(str(v) for q in pl["seq"] for v in q), (shown, pl["seq"])
    assert pdfform.blocks_for(p0["seq"], 4)[1][0][0][1] == "carry"          # i canestri oltre 12 proseguono nel tempo dopo
    assert all(k == "carry" for t, k in pdfform.blocks_for(p0["seq"], 4)[1][0][:3])
    assert pdfform.blocks_for(s["teams"]["A"]["players"][1]["seq"], 4)[3][1]   # 4° tempo + suppl. oltre 12 -> compatto
    assert len(pdfform.blocks_for(p0["seq"], 4)) == 7 and pdfform.blocks_for(p0["seq"], 6)[6][0] == [(str(v), "ot") for v in p0["seq"][4]] if len(p0["seq"]) > 4 and p0["seq"][4] else True   # 6 periodi + supplementare
    assert "UNDER 9 - UNDER 10 - UNDER 11" in pdfform.build_overlay(s) and "Entrate in gioco" in pdfform.build_overlay(s)   # modello CSI
    over = pdfinfo(call(f"/api/matches/{m5}/pdf", "GET", None, True)[1], "overflow.pdf")

    # ===== una sola partita in corso + termina partita =====
    NOAUTOFIN = True
    s = call("/api/matches", "POST", {"A": team("Uno", 5), "B": team("Due", 5)})[1]; mf = s["id"]
    fa = [p["id"] for p in s["teams"]["A"]["players"]]; fb = [p["id"] for p in s["teams"]["B"]["players"]]
    st, r = call("/api/matches", "POST", {"A": team("Tre", 5), "B": team("Quattro", 5)}); assert st == 409 and "partita in corso" in r["error"], r
    assert [x["id"] for x in call("/api/matches")[1] if x["phase"] != "finished"] == [mf]
    play(mf, 1, [0,1,2,3], [0,1,2,3], fa, fb, [("A",0,"points",2),("B",1,"points",3)])
    call(f"/api/matches/{mf}/start_tempo", "POST", {"A": fa[:4], "B": fb[:4]})
    call(f"/api/matches/{mf}/event", "POST", {"player_id": fa[0], "kind": "points", "value": 3})
    st, s = call(f"/api/matches/{mf}/finish", "POST", {}); assert st == 200 and s["phase"] == "finished"   # tempo 2 aperto: chiuso senza supplementare
    assert s["teams"]["A"]["period"][:2] == [2, 3] and s["teams"]["A"]["score"] == 5 and s["teams"]["B"]["score"] == 3 and not s["has_ot"]
    assert s["tempi_done"] == 2 and s["teams"]["A"]["awarded"][2] is None if "awarded" in s["teams"]["A"] else True
    assert call(f"/api/matches/{mf}/finish", "POST", {})[0] == 400                      # gia' terminata
    assert call(f"/api/matches/{mf}/event", "POST", {"player_id": fa[0], "kind": "points", "value": 1})[0] == 400
    pdfinfo(call(f"/api/matches/{mf}/pdf", "GET", None, True)[1], "terminata_prima.pdf")
    st, r = call("/api/matches", "POST", {"A": team("Tre", 5), "B": team("Quattro", 5)}); assert st == 200   # dopo la fine si puo' creare
    ms = r["id"]; assert call(f"/api/matches/{ms}/finish", "POST", {})[1]["phase"] == "finished"   # terminata anche da lineup
    NOAUTOFIN = False
    # ===== modifica giocatori durante la partita =====
    s = call("/api/matches", "POST", {"A": team("Alfa", 6), "B": team("Beta", 5)})[1]; mr = s["id"]
    ra = s["teams"]["A"]["players"]; rb = s["teams"]["B"]["players"]
    call(f"/api/matches/{mr}/start_tempo", "POST", {"A": [p["id"] for p in ra[:4]], "B": [p["id"] for p in rb[:4]]})
    call(f"/api/matches/{mr}/event", "POST", {"player_id": ra[0]["id"], "kind": "points", "value": 2})
    def roster(A, Bt): return call(f"/api/matches/{mr}/roster", "POST", {"A": A, "B": Bt})
    cur = lambda: call(f"/api/matches/{mr}")[1]
    pl = lambda side: [{"id": p["id"], "number": p["number"], "first_name": p["first_name"], "last_name": p["last_name"], "birth_year": p["birth_year"]} for p in cur()["teams"][side]["players"]]
    TA = lambda: {"name": "alfa", "coach": "", "players": pl("A")}; TB = lambda: {"name": "Beta", "coach": "", "players": pl("B")}
    assert cur()["teams"]["A"]["players"][0]["locked"] and not cur()["teams"]["A"]["players"][5]["locked"]
    t = TA(); t["players"] = t["players"][1:]; st, r = roster(t, TB()); assert st == 400 and "non può essere rimosso" in r["error"]   # ha punti/presenze
    t = TA(); t["players"].append({"number": 40, "first_name": "nuovo", "last_name": "giocatore", "birth_year": 2014}); t["players"][1]["last_name"] = "rinominato"; t["players"][5]["number"] = 41
    st, r = roster(t, TB()); assert st == 200, r
    P = r["teams"]["A"]["players"]; assert len(P) == 7 and P[1]["last_name"] == "RINOMINATO" and P[5]["first_name"] == "NUOVO" and [p["number"] for p in P] == sorted(p["number"] for p in P) and P[0]["total"] == 2 and r["phase"] == "playing"
    t = TA(); t["players"][6]["number"] = t["players"][0]["number"]; assert roster(t, TB())[0] == 400   # maglia duplicata
    t = TA(); t["players"] = [p for p in t["players"] if p["number"] != 41]; st, r = roster(t, TB()); assert st == 200 and len(r["teams"]["A"]["players"]) == 6   # rimosso chi non ha mai giocato
    t = TA(); t["players"][0]["birth_year"] = 2022; assert roster(t, TB())[0] == 400
    call(f"/api/matches/{mr}/finish", "POST", {}); assert call(f"/api/matches/{mr}/roster", "POST", {"A": TA(), "B": TB()})[0] == 400

    # ===== forfait: squadra senza 4 giocatori schierabili =====
    s = call("/api/matches", "POST", {"A": team("Alfa", 5), "B": team("Beta", 6)})[1]; mq = s["id"]
    qa = [p["id"] for p in s["teams"]["A"]["players"]]; qb = [p["id"] for p in s["teams"]["B"]["players"]]
    call(f"/api/matches/{mq}/start_tempo", "POST", {"A": qa[:4], "B": qb[:4]})
    call(f"/api/matches/{mq}/event", "POST", {"player_id": qa[0], "kind": "points", "value": 2})
    for i in (0, 1):
        for _ in range(5): st, s = call(f"/api/matches/{mq}/event", "POST", {"player_id": qa[i], "kind": "foul"})
    assert s["phase"] == "finished" and s["forfeit"]["loser"] == "A" and s["forfeit"]["winner"] == "B" and "vittoria a squadra BETA" in s["forfeit"]["text"], s["forfeit"]
    assert s["teams"]["A"]["awarded"] == [3, 1, 1, 1] and s["teams"]["B"]["awarded"] == [1, 3, 3, 3]   # T1 giocato (A avanti), restanti a B
    assert call(f"/api/matches/{mq}/overtime", "POST", {"play": True})[0] == 400
    pdfinfo(call(f"/api/matches/{mq}/pdf", "GET", None, True)[1], "forfait.pdf")
    assert "SENZA GIOCATORI SUFFICIENTI" in pdfform.build_overlay(s)
    # forfait al lineup dopo la modifica giocatori: una squadra sola, poi entrambe
    s = call("/api/matches", "POST", {"A": team("Alfa", 5), "B": team("Beta", 5)})[1]; mr = s["id"]
    ids = lambda sd: [{"id": p["id"], "number": p["number"], "first_name": p["first_name"], "last_name": p["last_name"], "birth_year": p["birth_year"]} for p in s["teams"][sd]["players"]]
    st, r = call(f"/api/matches/{mr}/roster", "POST", {"A": {"name": "Alfa", "players": ids("A")[:3]}, "B": {"name": "Beta", "players": ids("B")}})
    assert st == 200 and r["phase"] == "finished" and r["forfeit"]["loser"] == "A" and r["teams"]["B"]["awarded"] == [3, 3, 3, 3] and r["teams"]["A"]["awarded"] == [1, 1, 1, 1]
    s = call("/api/matches", "POST", {"A": team("Alfa", 5), "B": team("Beta", 5)})[1]; mr = s["id"]
    st, r = call(f"/api/matches/{mr}/roster", "POST", {"A": {"name": "Alfa", "players": ids("A")[:2]}, "B": {"name": "Beta", "players": ids("B")[:3]}})
    assert r["forfeit"]["loser"] == "AB" and r["forfeit"]["winner"] is None and "doppio forfait" in r["forfeit"]["text"] and r["teams"]["A"]["awarded"] == [None] * 4
    pdfinfo(call(f"/api/matches/{mr}/pdf", "GET", None, True)[1], "doppio_forfait.pdf")

    # ===== partite di giorni precedenti: sola consultazione =====
    s = call("/api/matches", "POST", {"A": team("Vecchia", 5), "B": team("Partita", 5)})[1]; mo = s["id"]
    oa = [p["id"] for p in s["teams"]["A"]["players"]]; ob = [p["id"] for p in s["teams"]["B"]["players"]]
    call(f"/api/matches/{mo}/start_tempo", "POST", {"A": oa[:4], "B": ob[:4]})
    call(f"/api/matches/{mo}/event", "POST", {"player_id": oa[0], "kind": "points", "value": 2})
    assert call("/api/matches")[1][0]["readonly"] is False
    import sqlite3 as _sq; _c = _sq.connect(db); _c.execute("UPDATE matches SET created='2020-01-15 18:30' WHERE id=?", (mo,)); _c.commit(); _c.close()
    assert call(f"/api/matches/{mo}")[1]["readonly"] is True
    for path, body in ((f"/event", {"player_id": oa[0], "kind": "points", "value": 1}), ("/finish", {}), ("/end_tempo", {}), ("/roster", {}),
                       ("/sub", {"in": oa[4], "out": oa[0]}), ("/undo/1", {}), ("/start_tempo", {}), ("/delete", {})):
        st, r = call(f"/api/matches/{mo}{path}", "POST", body); assert st == 403 and "giorno precedente" in r["error"], (path, st, r)
    assert call(f"/api/matches/{mo}")[1]["teams"]["A"]["players"][0]["total"] == 2
    # una partita vecchia non terminata non blocca la creazione di una nuova
    st, r = call("/api/matches", "POST", {"A": team("Nuova", 5), "B": team("Oggi", 5)}); assert st == 200 and r["readonly"] is False
    NOAUTOFIN = False

    # ===== maiuscolo ovunque =====
    lo = {"A": {"name": "squadra uno", "coach": "mario rossi", "players": [{"number": i+1, "first_name": f"giù{i}", "last_name": f"bianchi{i}", "birth_year": 2012} for i in range(5)]},
          "B": team("Bisonti", 5), "category": "u13", "venue": "palazzetto", "girone": "g1", "gara_n": "ab1", "arbitri": "rossi / bianchi", "segnapunti": "verdi", "cronometrista": "neri"}
    st, s = call("/api/matches", "POST", lo); assert st == 200
    assert s["teams"]["A"]["name"] == "SQUADRA UNO" and s["teams"]["A"]["coach"] == "MARIO ROSSI" and s["teams"]["A"]["players"][0]["first_name"] == "GIÙ0"
    assert all(v == v.upper() for v in s["header"].values() if isinstance(v, str)) and s["header"]["arbitri"] == "ROSSI / BIANCHI"
    ov = pdfform.build_overlay(s); assert "SQUADRA UNO" in ov and "BIANCHI0" in ov and "squadra uno" not in ov
    # ===== >12 giocatori, panchina e sostituzioni =====
    assert call("/api/matches", "POST", {"A": team("A", 25), "B": team("B", 5)})[0] == 400
    s = call("/api/matches", "POST", {"A": team("Aquile", 15), "B": team("Bisonti", 8)})[1]; m6 = s["id"]
    assert [p["number"] for p in s["teams"]["A"]["players"]] == list(range(1, 16))     # ordine del wizard
    qa = [p["id"] for p in s["teams"]["A"]["players"]]; qb = [p["id"] for p in s["teams"]["B"]["players"]]
    st, s = call(f"/api/matches/{m6}/start_tempo", "POST", {"A": qa[:4], "B": qb[:4]}); assert st == 200
    assert s["court"]["A"] == qa[:4]
    ev = lambda i, k="points", v=2, side="A": call(f"/api/matches/{m6}/event", "POST", {"player_id": (qa if side == "A" else qb)[i], "kind": k, "value": v})
    assert ev(0)[0] == 200 and ev(0, v=3)[0] == 200 and ev(0, "foul")[0] == 200
    assert ev(5)[0] == 400                                   # in panchina: non puo' segnare
    sub = lambda i, o, side="A": call(f"/api/matches/{m6}/sub", "POST", {"in": (qa if side == "A" else qb)[i], "out": (qa if side == "A" else qb)[o]})
    assert sub(5, 0)[0] == 200
    s = call(f"/api/matches/{m6}")[1]
    assert s["court"]["A"] == qa[1:4] + [qa[5]]              # entra al posto di chi esce
    P = s["teams"]["A"]["players"]
    assert not P[0]["on_field"] and P[5]["on_field"] and P[0]["total"] == 5 and P[0]["fouls"] == 1 and s["teams"]["A"]["score"] == 5
    assert P[5]["entries"] == [1] and P[0]["entries"] == [1] and P[6]["entries"] == []   # entrato = partecipante
    assert ev(5)[0] == 200 and ev(0)[0] == 400
    assert s["roster"]["A"] == qa[:4] + [qa[5]] and s["roster"]["B"] == qb[:4]   # il sostituito resta nell'elenco del tempo
    assert sub(6, 5, "B")[0] == 400 and sub(5, 1)[0] == 400   # squadra sbagliata / gia in campo
    # fallo fuori: 5 falli = non puo' entrare
    st, s = call(f"/api/matches/{m6}/sub", "POST", {"in": qa[6], "out": qa[1]}); assert st == 200   # 7 entra al posto di 2
    for _ in range(5): assert ev(6, "foul")[0] == 200
    assert call(f"/api/matches/{m6}")[1]["teams"]["A"]["players"][6]["fouled_out"]
    assert call(f"/api/matches/{m6}")[1]["roster"]["A"].count(qa[0]) == 1 and sub(0, 5)[0] == 200 and call(f"/api/matches/{m6}")[1]["roster"]["A"].count(qa[0]) == 1   # rientro: riga riattivata, non duplicata
    assert call(f"/api/matches/{m6}/undo_sub/{call(f'/api/matches/{m6}')[1]['subs'][-1]['id']}", 'POST', {})[0] == 200
    assert sub(1, 6)[0] == 200 and sub(6, 1)[0] == 400       # 7 e' uscito ma ha 5 falli: non puo' rientrare
    s = call(f"/api/matches/{m6}")[1]; assert s["subs"][-1]["undoable"]
    assert call(f"/api/matches/{m6}/undo_sub/{s['subs'][0]['id']}", "POST", {})[0] == 400     # solo l'ultima
    st, s2 = call(f"/api/matches/{m6}/undo_sub/{s['subs'][-1]['id']}", "POST", {}); assert st == 200 and len(s2["subs"]) == len(s["subs"]) - 1
    assert call(f"/api/matches/{m6}/undo_sub/{s['subs'][-1]['id']}", "POST", {})[0] == 404   # gia' annullata
    st, s = call(f"/api/matches/{m6}/end_tempo", "POST", {})
    assert s["teams"]["A"]["players"][0]["total"] == 5 and s["teams"]["A"]["players"][0]["pts"][0] == 5   # i punti del giocatore uscito contano
    assert s["teams"]["A"]["score"] == s["teams"]["A"]["period"][0] and s["teams"]["A"]["players"][5]["entries"] == [1]
    for t in range(2, 5): play(m6, t, [0,1,2,3], [0,1,2,3], qa, qb, [("A", 0, "points", 3)] if t == 2 else [])
    s = call(f"/api/matches/{m6}/overtime", "POST", {"play": False})[1] if call(f"/api/matches/{m6}")[1]["phase"] == "ask_ot" else call(f"/api/matches/{m6}")[1]
    assert s["phase"] == "finished"
    pdfinfo(call(f"/api/matches/{m6}/pdf", "GET", None, True)[1], "due_fogli.pdf", pages=2)

    # ===== v5: default 6 periodi, capitano (K), regole di risultato della guida CSI, avviso 2° periodo =====
    DEFAULT_TEMPI = True
    s = call("/api/matches", "POST", {"A": team("K1", 5), "B": team("K2", 5)})[1]; mk = s["id"]
    DEFAULT_TEMPI = False
    assert s["n_tempi"] == 6 and call("/api/config")[1]["tempi"] == 6
    call(f"/api/matches/{mk}/finish", "POST", {})
    two = team("CAP", 5); two["players"][0]["captain"] = True; two["players"][1]["captain"] = True
    st, r = call("/api/matches", "POST", {"A": two, "B": team("B", 5)}); assert st == 400 and "capitano" in r["error"]
    one = team("CAP", 5); one["players"][2]["captain"] = True
    s = call("/api/matches", "POST", {"A": one, "B": team("B", 5)})[1]; mc = s["id"]
    assert [p["captain"] for p in s["teams"]["A"]["players"]] == [False, False, True, False, False] and not any(p["captain"] for p in s["teams"]["B"]["players"])
    ros = lambda sd, caps: {"name": s["teams"][sd]["name"], "players": [{"id": p["id"], "number": p["number"], "first_name": p["first_name"], "last_name": p["last_name"], "birth_year": p["birth_year"], "captain": caps(i)} for i, p in enumerate(s["teams"][sd]["players"])]}
    st, s2 = call(f"/api/matches/{mc}/roster", "POST", {"A": ros("A", lambda i: i == 0), "B": ros("B", lambda i: False)}); assert st == 200, s2
    assert [p["captain"] for p in s2["teams"]["A"]["players"]] == [True, False, False, False, False]
    assert call(f"/api/matches/{mc}/roster", "POST", {"A": ros("A", lambda i: i < 2), "B": ros("B", lambda i: False)})[0] == 400
    assert "CAP0 N0 \\(K\\)" in pdfform.build_overlay(call(f"/api/matches/{mc}")[1])
    call(f"/api/matches/{mc}/finish", "POST", {})
    def mk_match(n, cat, **kw):
        s = call("/api/matches", "POST", dict({"A": team("A", 5), "B": team("B", 5), "n_tempi": n, "category": cat}, **kw))[1]
        return s["id"], [p["id"] for p in s["teams"]["A"]["players"]], [p["id"] for p in s["teams"]["B"]["players"]]
    L4 = [0, 1, 2, 3]
    # parita' di punti di periodo, progressivo diverso -> vince chi e' avanti nel progressivo, 13-12 (qui +1), nessun supplementare
    mid_, a_, b_ = mk_match(2, "UNDER 10")
    play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 3), ("B", 0, "points", 2)])
    st, s = play(mid_, 2, L4, L4, a_, b_, [("A", 0, "points", 2), ("B", 0, "points", 3), ("B", 0, "points", 1)])
    assert s["phase"] == "finished" and s["teams"]["A"]["awarded_total"] == s["teams"]["B"]["awarded_total"] == 4 and s["teams"]["A"]["score"] == 5 and s["teams"]["B"]["score"] == 6
    assert s["result"]["winner"] == "B" and s["result"]["reason"] == "progressivo" and s["result"]["final"] == {"A": 4, "B": 5} and not s["result"]["dts"] and not s["can_ot"]
    ov = pdfform.build_overlay(s); assert "13-12 per progressivo" in ov
    pdfinfo(call(f"/api/matches/{mid_}/pdf", "GET", None, True)[1], "tie_13_12.pdf")
    # Under 9: il pareggio e' ammesso e chiude la gara (nessun supplementare)
    mid_, a_, b_ = mk_match(1, "UNDER 9")
    st, s = play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2), ("B", 0, "points", 2)])
    assert s["phase"] == "finished" and s["under9"] and s["result"]["tie"] and s["result"]["winner"] is None and not s["can_ot"]
    assert call(f"/api/matches/{mid_}/overtime", "POST", {"play": True})[0] == 400
    # parita' totale -> supplementari ripetuti fino alla vincente: 13-12 e DTS "SI"; i supplementari non assegnano punti di periodo
    mid_, a_, b_ = mk_match(1, "UNDER 11")
    st, s = play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2), ("B", 0, "points", 2)]); assert s["phase"] == "ask_ot"
    assert call(f"/api/matches/{mid_}/overtime", "POST", {"play": True})[1]["tempo"] == 2
    st, s = play(mid_, 2, L4, L4, a_, b_, [("A", 0, "points", 1), ("B", 0, "points", 1)]); assert s["phase"] == "ask_ot" and s["periods"] == 2   # ancora pari: altro supplementare
    assert call(f"/api/matches/{mid_}/overtime", "POST", {"play": True})[1]["tempo"] == 3
    st, s = play(mid_, 3, L4, L4, a_, b_, [("A", 0, "points", 3)])
    assert s["phase"] == "finished" and s["periods"] == 3 and s["has_ot"] and s["teams"]["A"]["awarded"] == [2, None, None]
    assert s["result"]["winner"] == "A" and s["result"]["reason"] == "supplementare" and s["result"]["final"] == {"A": 3, "B": 2} and s["result"]["dts"]
    pdfinfo(call(f"/api/matches/{mid_}/pdf", "GET", None, True)[1], "tie_ot.pdf")
    # rifiuto del supplementare in caso di parita' totale: pareggio, ma si puo' ancora aggiungere dopo
    mid_, a_, b_ = mk_match(1, "UNDER 11")
    play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2), ("B", 0, "points", 2)])
    s = call(f"/api/matches/{mid_}/overtime", "POST", {"play": False})[1]; assert s["phase"] == "finished" and s["result"]["tie"] and s["can_ot"]
    assert call(f"/api/matches/{mid_}/overtime", "POST", {"play": True})[1]["phase"] == "lineup"
    # supplementare disattivato: parita' totale finisce subito
    mid_, a_, b_ = mk_match(1, "UNDER 11", ot_enabled=False)
    assert play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2), ("B", 0, "points", 2)])[1]["phase"] == "finished"
    # punti diversi nei periodi: nessun supplementare e nessun +1
    mid_, a_, b_ = mk_match(1, "UNDER 11")
    s = play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 3)])[1]; assert s["phase"] == "finished" and s["result"]["final"] == {"A": 3, "B": 1} and s["result"]["reason"] is None
    # avviso regola 2° periodo (guida CSI): dati per l'avviso = entries del 1° periodo
    mid_, a_, b_ = mk_match(3, "UNDER 10")
    s = call("/api/matches", "GET")[1] and play(mid_, 1, L4, L4, a_, b_, [])[1]
    pl = s["teams"]["A"]["players"]; assert [bool(p["entries"]) for p in pl] == [True] * 4 + [False] and s["tempo"] == 2 and len(pl) <= 7
    assert 'lineupWarn' in open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
    # ===== v6.3: ordine per maglia, modifica di un periodo passato =====
    sh = [{"number": n, "first_name": f"N{n}", "last_name": f"X{n}", "birth_year": 2013} for n in (9, 3, 12, 1, 7, 5)]
    s = call("/api/matches", "POST", {"A": {"name": "Ordine", "players": sh}, "B": team("B", 5), "n_tempi": 3, "category": "UNDER 10"})[1]
    assert [p["number"] for p in s["teams"]["A"]["players"]] == [1, 3, 5, 7, 9, 12]
    ia = [p["id"] for p in s["teams"]["A"]["players"]]; ib = [p["id"] for p in s["teams"]["B"]["players"]]
    st, s = call(f"/api/matches/{s['id']}/start_tempo", "POST", {"A": [ia[4], ia[0], ia[2], ia[5]], "B": ib[:4]}); assert st == 200
    assert s["court"]["A"] == [ia[0], ia[2], ia[4], ia[5]] and s["roster"]["A"] == s["court"]["A"]
    # modifica: periodo 1 e 2 conclusi, 3 in corso
    mid_, a_, b_ = mk_match(3, "UNDER 10")
    play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2), ("A", 0, "foul", 1), ("B", 0, "points", 1)])
    play(mid_, 2, L4, L4, a_, b_, [("A", 1, "points", 3), ("B", 1, "points", 2)])
    call(f"/api/matches/{mid_}/start_tempo", "POST", {"A": a_[:4], "B": b_[:4]}); call(f"/api/matches/{mid_}/event", "POST", {"player_id": a_[2], "kind": "points", "value": 1})
    s = call(f"/api/matches/{mid_}")[1]; assert s["editable"] == [1, 2] and s["phase"] == "playing" and not s["editing"]
    st, s = call(f"/api/matches/{mid_}/reopen", "POST", {"tempo": 1}); assert st == 200 and s["phase"] == "lineup" and s["tempo"] == 1 and s["editing"]["resume_phase"] == "playing"
    assert s["teams"]["A"]["period"] == [0, 3, 1] and s["teams"]["B"]["period"] == [0, 2, 0] and 1 not in s["teams"]["A"]["players"][0]["entries"] and s["subs"] == []   # dati del periodo 1 azzerati, gli altri intatti
    assert s["teams"]["A"]["players"][0]["fouls"] == 0 and s["editable"] == []
    assert call(f"/api/matches/{mid_}/reopen", "POST", {"tempo": 2})[0] == 400
    call(f"/api/matches/{mid_}/start_tempo", "POST", {"A": a_[1:5], "B": b_[1:5]})
    call(f"/api/matches/{mid_}/event", "POST", {"player_id": a_[1], "kind": "points", "value": 3}); call(f"/api/matches/{mid_}/event", "POST", {"player_id": a_[0], "kind": "points", "value": 1})[0] == 400   # a_[0] non e' in campo
    st, s = call(f"/api/matches/{mid_}/end_tempo", "POST", {}); assert st == 200 and s["phase"] == "playing" and s["tempo"] == 3 and not s["editing"]
    assert s["teams"]["A"]["period"] == [3, 3, 1] and s["teams"]["A"]["progressivo"] == [3, 6, 7]
    assert s["teams"]["A"]["players"][1]["entries"][0] == 1 and s["teams"]["A"]["players"][0]["entries"][0] != 1
    assert s["teams"]["A"]["awarded"][:2] == [3, 3] and s["teams"]["B"]["awarded"][:2] == [1, 1] and s["editable"] == [1, 2]   # nuovi punti di periodo ricalcolati
    # partita conclusa: modifica del periodo che cambia l'esito, poi supplementare proposto/non piu' necessario
    mid_, a_, b_ = mk_match(2, "UNDER 10")
    play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2)]); s = play(mid_, 2, L4, L4, a_, b_, [("B", 0, "points", 2)])[1]
    assert s["phase"] == "ask_ot"
    s = call(f"/api/matches/{mid_}/reopen", "POST", {"tempo": 2})[1]; assert s["editing"]["resume_phase"] == "ask_ot"
    play(mid_, 2, L4, L4, a_, b_, [("A", 0, "points", 3)]); s = call(f"/api/matches/{mid_}")[1]
    assert s["phase"] == "finished" and s["result"]["winner"] == "A" and not s["can_ot"]      # niente piu' parita': niente supplementare
    s = call(f"/api/matches/{mid_}/reopen", "POST", {"tempo": 2})[1]; assert s["editing"]["resume_phase"] == "finished"
    s = play(mid_, 2, L4, L4, a_, b_, [("B", 0, "points", 2)])[1]
    assert s["phase"] == "ask_ot"      # dopo "Termina modifica" la parita' totale ripropone il supplementare
    mid_, a_, b_ = mk_match(6, "UNDER 10")
    for k in range(1, 7): s = play(mid_, k, L4, L4, a_, b_, [("A", 0, "points", 2)] if k % 2 else [("B", 0, "points", 2)])[1]
    assert s["phase"] == "ask_ot", s["phase"]
    mid_, a_, b_ = mk_match(6, "UNDER 10")
    for k in range(1, 7): s = play(mid_, k, L4, L4, a_, b_, [("A", 0, "points", 2)] if k % 2 else [("B", 0, "points", 3 if k == 2 else 2)])[1]
    assert s["phase"] == "finished" and s["result"]["reason"] == "progressivo"      # periodi pari, progressivo decide: nessun supplementare (guida)
    # finish durante modifica, forfait e giorno precedente
    mid_, a_, b_ = mk_match(2, "UNDER 10"); play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2)])
    call(f"/api/matches/{mid_}/reopen", "POST", {"tempo": 1}); s = call(f"/api/matches/{mid_}/finish", "POST", {})[1]
    assert s["phase"] == "finished" and not s["editing"] and s["teams"]["A"]["score"] == 0
    mid_, a_, b_ = mk_match(2, "UNDER 10"); play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2)]); call(f"/api/matches/{mid_}/finish", "POST", {})
    cx = sqlite3.connect(db); cx.execute("UPDATE matches SET created='2020-01-01 10:00' WHERE id=?", (mid_,)); cx.commit(); cx.close()
    s = call(f"/api/matches/{mid_}")[1]; assert s["editable"] == [] and call(f"/api/matches/{mid_}/reopen", "POST", {"tempo": 1})[0] == 403
    html = open(os.path.join(HERE, "index.html"), encoding="utf-8").read(); assert "addNum" in html and "askReopen" in html
    # ===== v6.4: fino a 12 periodi, PDF su piu' fogli =====
    assert call("/api/config")[1]["max_tempi"] == 12 and call("/api/matches", "POST", {"A": team("A", 5), "B": team("B", 5), "n_tempi": 0})[0] == 400
    mid_, a_, b_ = mk_match(9, "UNDER 10")
    for k in range(1, 10): s = play(mid_, k, L4, L4, a_, b_, [("A", 0, "points", 1)] * (12 if k == 6 else 1) + [("B", 0, "points", 2)])[1]
    assert s["phase"] == "finished" and s["periods"] == 9 and s["teams"]["A"]["period"][5] == 12 and len(s["teams"]["A"]["awarded"]) == 9
    import pdfcsi
    assert pdfcsi.n_pages(s) == 2 and pdfcsi.period_sheets(s) == 2
    pdf = call(f"/api/matches/{mid_}/pdf", "GET", None, True)[1]; pdfinfo(pdf, "nove_periodi.pdf", 2)
    ov1, ov2 = pdfcsi.build_page(s, 0), pdfcsi.build_page(s, 1)
    assert "7° Periodo" in ov2 and "7° Periodo" not in ov1 and "Supplement." in ov1 and "Foglio 2 di 2" in ov2 and "periodi 7-9" in ov2
    per, ot = pdfcsi.blocks_all([[1] * 12, [1], [], [], [], [1] * 12, [1] * 3, [], []], 9)
    assert len(per) == 9 and len(per[5][0]) == 8 and [k for _, k in per[6][0]][:4] == ["carry"] * 4     # lo sforamento del 6° prosegue nel 7° (altro foglio)
    mid_, a_, b_ = mk_match(12, "UNDER 10", A=team("A", 15)); s = call(f"/api/matches/{mid_}")[1]; assert pdfcsi.n_pages(s) == 4   # 12 periodi x 15 giocatori: 2 x 2 fogli
    mid_, a_, b_ = mk_match(6, "UNDER 10"); assert pdfcsi.n_pages(call(f"/api/matches/{mid_}")[1]) == 1
    assert "nessun punto segnato" in html and "' su '+tot+' nel '" in html
    # ===== v6.5: MVP =====
    mid_, a_, b_ = mk_match(1, "UNDER 10")
    assert call(f"/api/matches/{mid_}/mvp", "POST", {"player_id": a_[0]})[0] == 400            # solo a partita conclusa
    play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 3), ("B", 1, "points", 2)])
    assert call(f"/api/matches/{mid_}/mvp", "POST", {"player_id": 99999})[0] == 400 and call(f"/api/matches/{mid_}/mvp", "POST", {"player_id": "x"})[0] == 400
    st, s = call(f"/api/matches/{mid_}/mvp", "POST", {"player_id": b_[1]}); assert st == 200 and s["mvp"]["side"] == "B" and s["mvp"]["number"] == 2 and s["mvp"]["points"] == 2
    s = call(f"/api/matches/{mid_}/mvp", "POST", {"player_id": a_[0]})[1]; assert s["mvp"]["side"] == "A" and s["mvp"]["points"] == 3        # cambio: uno solo per partita
    assert [x for x in call("/api/matches")[1] if x["id"] == mid_][0]["mvp"]["name"] == "N0 A0"
    cx = sqlite3.connect(db); cx.execute("UPDATE matches SET created='2020-01-01 10:00' WHERE id=?", (mid_,)); cx.commit(); cx.close()
    assert call(f"/api/matches/{mid_}/mvp", "POST", {"player_id": None})[0] == 403 and call(f"/api/matches/{mid_}")[1]["mvp"]["number"] == 1   # giorno precedente: sola lettura
    mid_, a_, b_ = mk_match(1, "UNDER 10"); play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 1)])
    assert call(f"/api/matches/{mid_}/mvp", "POST", {"player_id": a_[0]})[0] == 200 and call(f"/api/matches/{mid_}/mvp", "POST", {"player_id": None})[1]["mvp"] is None
    # ===== v6.6: impostazioni partita modificabili =====
    setg = lambda m_, **kw: call(f"/api/matches/{m_}/settings", "POST", kw)
    mid_, a_, b_ = mk_match(2, "UNDER 10")
    play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2)]); s = play(mid_, 2, L4, L4, a_, b_, [("A", 0, "points", 2)])[1]; assert s["phase"] == "finished"
    assert setg(mid_, n_tempi=13)[0] == 400 and setg(mid_, n_tempi=1)[0] == 400                      # sotto i periodi con dati: bloccato
    st, s = setg(mid_, n_tempi=3, category="u11", arbitri="rossi / bianchi"); assert st == 200 and s["reopened"] and s["phase"] == "lineup" and s["tempo"] == 3 and s["n_tempi"] == 3
    assert s["header"]["category"] == "U11" and s["header"]["arbitri"] == "ROSSI / BIANCHI" and s["result"]["provisional"]
    s = play(mid_, 3, L4, L4, a_, b_, [("B", 0, "points", 3)])[1]; assert s["phase"] == "finished" and s["periods"] == 3 and s["teams"]["A"]["awarded"] == [3, 3, 1]
    assert s["result"]["final"] == {"A": 7, "B": 5} and pdfcsi.n_pages(s) == 1
    # fino a 7 periodi: secondo foglio PDF; supplementare gia' giocato -> diventa periodo regolare
    mid_, a_, b_ = mk_match(1, "UNDER 10"); s = play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2), ("B", 0, "points", 2)])[1]; assert s["phase"] == "ask_ot"
    call(f"/api/matches/{mid_}/overtime", "POST", {"play": True}); s = play(mid_, 2, L4, L4, a_, b_, [("A", 0, "points", 1)])[1]; assert s["has_ot"] and s["phase"] == "finished"
    st, s = setg(mid_, n_tempi=2); assert st == 200 and not s["reopened"] and not s["has_ot"] and s["periods"] == 2 and s["phase"] == "finished" and s["teams"]["A"]["awarded"] == [2, 3]
    assert setg(mid_, n_tempi=1)[0] == 400
    st, s = setg(mid_, n_tempi=7); assert s["reopened"] and s["tempo"] == 3 and s["phase"] == "lineup"
    for k in range(3, 8): s = play(mid_, k, L4, L4, a_, b_, [("A", 1, "points", 2)])[1]
    assert s["phase"] == "finished" and s["periods"] == 7 and pdfcsi.n_pages(s) == 2 and "7° Periodo" in pdfcsi.build_page(s, 1)
    call(f"/api/matches/{mid_}/mvp", "POST", {"player_id": a_[0]}); st, s = setg(mid_, n_tempi=8); assert s["mvp"]["number"] == 1 and s["phase"] == "lineup"   # MVP resta
    # attesa supplementare, riduzione a periodi vuoti, ot on/off, in corso
    mid_, a_, b_ = mk_match(2, "UNDER 10"); play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2)])
    st, s = setg(mid_, n_tempi=1); assert st == 200 and s["phase"] == "finished" and s["tempo"] == 1       # 2° periodo non ancora iniziato: riducendo la partita finisce
    s = setg(mid_, n_tempi=2)[1]; assert s["phase"] == "lineup" and s["reopened"] and s["tempo"] == 2   # concluso al 1° di 1: aggiungendo un periodo si riapre
    s = call(f"/api/matches/{mid_}/finish", "POST", {})[1]; assert s["phase"] == "finished" and s["tempo"] == 1       # terminata dopo il 1° di 2
    st, s = setg(mid_, n_tempi=4); assert st == 200 and not s["reopened"] and s["phase"] == "finished"                  # chiusa in anticipo: non si riapre da sola
    st, s = setg(mid_, n_tempi=1); assert st == 200 and s["phase"] == "finished" and s["n_tempi"] == 1
    mid_, a_, b_ = mk_match(1, "UNDER 10"); s = play(mid_, 1, L4, L4, a_, b_, [("A", 0, "points", 2), ("B", 0, "points", 2)])[1]; assert s["phase"] == "ask_ot"
    assert setg(mid_, ot_enabled=False)[1]["phase"] == "finished" and setg(mid_, ot_enabled=True)[1]["phase"] == "ask_ot"
    s = setg(mid_, n_tempi=2)[1]; assert s["phase"] == "lineup" and s["tempo"] == 2 and s["reopened"]
    mid_, a_, b_ = mk_match(3, "UNDER 10"); call(f"/api/matches/{mid_}/start_tempo", "POST", {"A": a_[:4], "B": b_[:4]})
    st, s = setg(mid_, n_tempi=5); assert st == 200 and s["phase"] == "playing" and s["n_tempi"] == 5 and not s["reopened"]
    assert setg(mid_, n_tempi=0)[0] == 400
    cx = sqlite3.connect(db); cx.execute("UPDATE matches SET created='2020-01-01 10:00' WHERE id=?", (mid_,)); cx.commit(); cx.close()
    assert setg(mid_, n_tempi=6)[0] == 403
    # ===== v6.7: squadre salvate =====
    pl_ = lambda nums, **kw: [dict({"number": n, "first_name": f"n{n}", "last_name": f"c{n}", "birth_year": 2013}, **kw) for n in nums]
    st, tm = call("/api/teams", "POST", {"name": "olimpia", "coach": "rossi", "players": pl_([9, 3, 12, 1]) + [dict(pl_([5])[0], captain=True)]}); assert st == 200
    assert tm["name"] == "OLIMPIA" and tm["coach"] == "ROSSI" and [p["number"] for p in tm["players"]] == [1, 3, 5, 9, 12] and tm["players"][0]["first_name"] == "N1" and [p["captain"] for p in tm["players"]] == [False, False, True, False, False]
    assert call("/api/teams", "POST", {"name": "Olimpia", "players": pl_([1])})[0] == 409                               # nome unico
    assert call("/api/teams", "POST", {"name": "X", "players": pl_([1, 1])})[0] == 400                                  # maglia duplicata
    assert call("/api/teams", "POST", {"name": "X", "players": [dict(pl_([1])[0], birth_year=2022)]})[0] == 400         # < 5 anni
    assert call("/api/teams", "POST", {"name": "X", "players": pl_(range(25))})[0] == 400 and call("/api/teams", "POST", {"name": "", "players": pl_([1])})[0] == 400 and call("/api/teams", "POST", {"name": "X", "players": []})[0] == 400
    assert call("/api/teams", "POST", {"name": "X", "players": pl_(range(24))})[0] == 200
    st, tm2 = call(f"/api/teams/{tm['id']}", "POST", {"name": "Olimpia Milano", "players": pl_([7, 2, 4, 6])}); assert st == 200 and tm2["name"] == "OLIMPIA MILANO" and [p["number"] for p in tm2["players"]] == [2, 4, 6, 7]
    assert [x["name"] for x in call("/api/teams")[1]] == ["OLIMPIA MILANO", "X"] and call("/api/teams/9999", "POST", {"name": "Q", "players": pl_([1])})[0] == 404
    # richiamo: i dati vengono copiati nella partita; eliminare la squadra non tocca la partita
    mm = call("/api/matches", "POST", {"A": {k: tm2[k] for k in ("name", "coach", "players")}, "B": team("Bisonti", 5), "n_tempi": 2})[1]
    assert [p["number"] for p in mm["teams"]["A"]["players"]] == [2, 4, 6, 7]
    assert call(f"/api/teams/{tm2['id']}/delete", "POST", {})[0] == 200 and call(f"/api/teams/{tm2['id']}/delete", "POST", {})[0] == 404
    assert call(f"/api/matches/{mm['id']}")[1]["teams"]["A"]["name"] == "OLIMPIA MILANO" and len(call(f"/api/matches/{mm['id']}")[1]["teams"]["A"]["players"]) == 4
    assert [x["name"] for x in call("/api/teams")[1]] == ["X"]
    # ===== v6.8: HOOPLY (icone, manifest, titolo) =====
    for f_, ct_ in (("favicon-32.png", b"\x89PNG"), ("apple-touch-icon.png", b"\x89PNG"), ("icon-192.png", b"\x89PNG"), ("icon-512.png", b"\x89PNG")):
        st, d = call(f"/static/{f_}", "GET", None, True); assert st == 200 and d[:4] == ct_, f_
    mf = json.loads(urllib.request.urlopen(B + "/static/manifest.json").read()); assert mf["name"] == "HOOPLY \u2013 Every game, a report" and mf["short_name"] == "HOOPLY" and len(mf["icons"]) >= 2
    assert urllib.request.urlopen(B + "/static/favicon.ico").status == 200
    try: urllib.request.urlopen(B + "/static/../app.py"); raise SystemExit("traversal")
    except urllib.error.HTTPError as e_: assert e_.code == 404
    html = open(os.path.join(HERE, "index.html"), encoding="utf-8").read(); assert "<title>HOOPLY \u2013 Every game, a report</title>" in html and "apple-touch-icon" in html and "manifest.json" in html and "Every game, a report" in html
    assert len(call("/api/matches")[1]) == 18 + 9 + 18
    print("TUTTO OK  A", A["progressivo"], "B", Bt["progressivo"])
finally:
    srv.terminate(); os.path.exists(db) and os.remove(db)
