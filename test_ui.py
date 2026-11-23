"""Controllo UI in Chrome headless (richiede playwright + chrome): statistiche dall'elenco partite senza errori in console,
tooltip con numero e nome, etichette 'punti nel tempo / totale', link del titolo. Uso: python test_ui.py"""
import json, os, sqlite3, subprocess, sys, tempfile, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); db = tempfile.mktemp(suffix=".db")
env = dict(os.environ, REFERTO_DB=db, PORT="8777", NO_BROWSER="1"); B = "http://127.0.0.1:8777"
srv = subprocess.Popen([sys.executable, os.path.join(HERE, "app.py")], env=env, stdout=subprocess.DEVNULL); time.sleep(1)
def call(p, m="GET", b=None):
    return json.loads(urllib.request.urlopen(urllib.request.Request(B + p, method=m, data=json.dumps(b).encode() if b is not None else None, headers={"Content-Type": "application/json"})).read())
def mk(n, tag, cat="UNDER 10", **kw):
    t = lambda s: {"name": s, "players": [{"number": i + 1, "first_name": f"N{i}", "last_name": f"{s}{i}", "birth_year": 2013} for i in range(5)]}
    s = call("/api/matches", "POST", dict({"A": t("AQ"), "B": t("BI"), "n_tempi": n, "category": cat}, **kw)); return s["id"], [p["id"] for p in s["teams"]["A"]["players"]], [p["id"] for p in s["teams"]["B"]["players"]]
def tempo(m, a, b, evs, end=True):
    call(f"/api/matches/{m}/start_tempo", "POST", {"A": a[:4], "B": b[:4]})
    for side, i, k, v in evs: call(f"/api/matches/{m}/event", "POST", {"player_id": (a if side == "A" else b)[i], "kind": k, "value": v})
    if end: call(f"/api/matches/{m}/end_tempo", "POST", {})
errors = []; dialogs = []
try:
    old, oa, ob = mk(1, "x"); tempo(old, oa, ob, [("A", 0, "points", 2)])                               # partita conclusa, poi spostata a un giorno precedente
    c = sqlite3.connect(db); c.execute("UPDATE matches SET created='2020-01-15 18:30' WHERE id=?", (old,)); c.commit(); c.close()
    fin, fa, fb = mk(2, "f"); tempo(fin, fa, fb, [("A", 0, "points", 3), ("A", 1, "points", 1), ("B", 0, "points", 2), ("A", 0, "foul", 1)]); tempo(fin, fa, fb, [("A", 0, "points", 2), ("B", 1, "points", 2)])
    prog, pa, pb = mk(3, "p"); tempo(prog, pa, pb, [("A", 0, "points", 2), ("B", 0, "points", 1)], end=False)   # in corso
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"]); pg = br.new_page(viewport={"width": 1280, "height": 900})
        pg.on("console", lambda m: m.type == "error" and errors.append(m.text)); pg.on("response", lambda r: r.status == 404 and print("404", r.url)); pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(B); time.sleep(.6)
        n = pg.locator("tr:has(button:text('Statistiche'))").count(); assert n == 3, n
        for i in range(n):   # Statistiche da ogni riga: conclusa, in corso, giorno precedente
            pg.goto(B); time.sleep(.4); pg.locator("td.rowbtn button:text('Statistiche')").nth(i).click(); time.sleep(.4)
            assert pg.locator("#modal .modal.fs").count() == 1, i; assert "Statistiche –" in pg.inner_text("#modal"); pg.keyboard.press("Escape")
        # partita mai iniziata (fase scelta giocatori, nessun evento)
        call(f"/api/matches/{prog}/finish", "POST", {}); nev, _, _ = mk(2, "n"); pg.goto(B); time.sleep(.5)
        pg.locator("tr:has-text('AQ') >> nth=0").locator("button:text('Statistiche')").click(); time.sleep(.4); assert pg.locator("#modal .modal.fs").count() == 1; assert pg.locator("#modal .nopts").count() > 0 and "nessun punto segnato" in pg.inner_text("#modal"); pg.keyboard.press("Escape")
        # selezione giocatori: input numerico + ordine per maglia
        pg.evaluate(f"openMatch({nev})"); time.sleep(.5)
        def err(side): return pg.inner_text(f"#nerr_{side}") if pg.locator(f"#nerr_{side}").count() else ""
        pg.fill("#num_A", "4"); pg.keyboard.press("Enter"); time.sleep(.2); pg.fill("#num_A", "2"); pg.click("button:text('Aggiungi') >> nth=0"); time.sleep(.2)
        pg.fill("#num_A", "1"); pg.keyboard.press("Enter"); time.sleep(.2)
        assert pg.locator("#main .lineup").first.locator(".lrow.sel .nbadge").all_text_contents() == ["1", "2", "4"]    # ordinati per maglia
        pg.fill("#num_A", "4"); pg.keyboard.press("Enter"); time.sleep(.2); assert "già selezionato" in err("A"), err("A")
        pg.fill("#num_A", "77"); pg.keyboard.press("Enter"); time.sleep(.2); assert "non presente" in err("A"), err("A")
        pg.fill("#num_A", ""); pg.keyboard.press("Enter"); time.sleep(.2); assert "Inserisci" in err("A")
        pg.fill("#num_A", "3"); pg.keyboard.press("Enter"); time.sleep(.2); pg.fill("#num_A", "5"); pg.keyboard.press("Enter"); time.sleep(.2); assert "già scelto" in err("A"), err("A")
        pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_selezione_numero.png"))
        call(f"/api/matches/{nev}/finish", "POST", {})
        # modifica periodo precedente su partita conclusa
        pg.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
        pg.evaluate(f"openMatch({fin})"); time.sleep(.5); pg.click("button:text('Modifica periodo')"); time.sleep(.3)
        pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_modifica_periodo_scelta.png")); pg.click("#modal button:text-matches('1° tempo')"); time.sleep(.6)
        assert any("ELIMINATI" in d for d in dialogs), dialogs
        assert "Modifica del 1° tempo" in pg.inner_text("#main") and pg.evaluate("M.editing.resume_phase") == "finished"
        pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_modifica_periodo.png"))
        for i in (3, 1, 2, 4): pg.fill("#num_A", str(i)); pg.keyboard.press("Enter"); time.sleep(.1)
        for i in (1, 2, 3, 4): pg.fill("#num_B", str(i)); pg.keyboard.press("Enter"); time.sleep(.1)
        pg.click("#goBtn"); time.sleep(.6); assert "(modifica)" in pg.inner_text("#main")
        pg.locator("button:text('+3')").first.click(); time.sleep(.3); pg.click("button:text-matches('Termina modifica')"); time.sleep(.6)
        assert "Partita conclusa" in pg.inner_text("#main") and pg.evaluate("M.editing") is None and pg.evaluate("M.teams.A.period[0]") == 3
        # tabella "Parziali e progressivo": deve stare nella modale (scroll orizzontale), con 6 e 12 periodi + supplementare
        for npd in (6, 12):
            lm, la, lb = mk(npd, "w" + str(npd), "UNDER 10")
            for k in range(1, npd + 1): tempo(lm, la, lb, [("A", 0, "points", 2), ("B", 0, "points", 2)])
            st = call(f"/api/matches/{lm}"); assert st["phase"] == "ask_ot", st["phase"]
            call(f"/api/matches/{lm}/overtime", "POST", {"play": True}); tempo(lm, la, lb, [("A", 0, "points", 2)])
            for w, h_ in ((1280, 800), (768, 1024)):
                pg.set_viewport_size({"width": w, "height": h_}); pg.goto(B); time.sleep(.3); pg.evaluate(f"openMatch({lm})"); time.sleep(.5); pg.evaluate("showSummary()"); time.sleep(.4)
                r = pg.evaluate("""()=>{var bx=document.querySelector('#modal .box').getBoundingClientRect(),res=[];document.querySelectorAll('#modal .tscroll').forEach(function(s){var b=s.getBoundingClientRect();res.push({right:b.right,boxRight:bx.right,ov:getComputedStyle(s).overflowX,sw:s.scrollWidth,cw:s.clientWidth})});
                  var m=document.querySelector('#modal .box');return {tabs:res,boxOver:m.scrollWidth>m.clientWidth+1,doc:document.documentElement.scrollWidth>window.innerWidth+1}}""")
                assert len(r["tabs"]) == 3 and not r["boxOver"] and not r["doc"], r
                assert all(x["right"] <= x["boxRight"] + 1 and x["ov"] in ("auto", "scroll") for x in r["tabs"]), r
                if npd == 12 and w == 768: pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_parziali_12_periodi.png"))
                pg.evaluate("closeModal()")
        pg.set_viewport_size({"width": 1280, "height": 900})
        # MVP: scelta in "Partita conclusa", icona coppa nell'elenco, modale
        pg.evaluate(f"openMatch({fin})"); time.sleep(.4); assert "MVP della partita" in pg.inner_text("#main")
        pg.click("button:text('Assegna MVP')"); time.sleep(.2); assert "Scegli" in pg.inner_text("#mvpErr")
        pg.select_option("#mvpSel", index=2); pg.click("button:text('Assegna MVP')"); time.sleep(.5)
        assert pg.evaluate("M.mvp") is not None and "Cambia MVP" in pg.inner_text("#main")
        pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_mvp_scelta.png"))
        pg.goto(B); time.sleep(.5); assert pg.locator(".trophybtn").count() == 1
        pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_mvp_lista.png")); pg.click(".trophybtn"); time.sleep(.3)
        txt = pg.inner_text("#modal"); assert "MVP della partita" in txt and "#" in txt and "punti" in txt and pg.locator("#bigtrophy svg").count() == 1
        pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_mvp_modale.png")); pg.evaluate("closeModal()")
        # impostazioni partita: errore in riduzione, poi aggiungo un periodo a partita conclusa (riapertura con conferma)
        pg.evaluate(f"openMatch({fin})"); time.sleep(.4); assert pg.evaluate("M.phase") == "finished"; pg.click("#bSet"); time.sleep(.3)
        pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_impostazioni.png"))
        pg.select_option("#set_n", "1"); pg.click("button:text('Salva')"); time.sleep(.4); assert "contiene già dati" in pg.inner_text("#setErr")
        errors[:] = [e for e in errors if "400 (Bad Request)" not in e]      # il 400 della riduzione bloccata è atteso (Chrome lo logga come errore di rete)
        pg.select_option("#set_n", "3"); pg.fill("#set_category", "under 11"); n_d = len(dialogs); pg.click("button:text('Salva')"); time.sleep(.6)
        assert len(dialogs) == n_d + 1 and "RIAPERTA" in dialogs[-1] and "MVP" in dialogs[-1], dialogs[-1:]
        assert pg.evaluate("M.phase") == "lineup" and pg.evaluate("M.tempo") == 3 and pg.evaluate("M.n_tempi") == 3 and pg.evaluate("M.header.category") == "UNDER 11"
        assert "3° tempo" in pg.inner_text("#main"); pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_impostazioni_riaperta.png"))
        for i in (1, 2, 3, 4): pg.fill("#num_A", str(i)); pg.keyboard.press("Enter"); pg.fill("#num_B", str(i)); pg.keyboard.press("Enter")
        pg.click("#goBtn"); time.sleep(.5); pg.locator("button:text('+2')").first.click(); time.sleep(.3); pg.click("button:text('Termina tempo 3')"); time.sleep(.6)
        assert pg.evaluate("M.phase") == "finished" and pg.evaluate("M.periods") == 3 and "Partita conclusa" in pg.inner_text("#main")
        # squadre salvate: creazione/modifica/eliminazione e richiamo nella nuova partita
        pg.goto(B); time.sleep(.4); pg.click("#bTeams"); time.sleep(.4); assert "Nessuna squadra salvata" in pg.inner_text("#main")
        pg.click("button:text('+ Nuova squadra')"); time.sleep(.3); pg.fill("input[placeholder='Nome squadra A']", "falchi")
        def fill_row(i, num, fn, ln, yr):
            r_ = pg.locator(".prow:not(.head)").nth(i); r_.locator("input").nth(0).fill(str(num)); r_.locator("input").nth(1).fill(fn); r_.locator("input").nth(2).fill(ln); r_.locator("select").select_option(str(yr))
        fill_row(0, 7, "luca", "rossi", 2013); pg.click("button:text-matches('Aggiungi giocatore')"); fill_row(1, 7, "marco", "bianchi", 2014)
        pg.click("button:text('Salva squadra')"); time.sleep(.3); assert "già usata" in pg.inner_text("#main") and pg.locator(".bad").count() >= 1
        pg.locator(".prow:not(.head)").nth(1).locator("input").nth(0).fill("3"); pg.locator(".prow:not(.head)").nth(1).locator(".kbtn").click()
        pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_squadra_modifica.png")); pg.click("button:text('Salva squadra')"); time.sleep(.5)
        assert "FALCHI" in pg.inner_text("#teamsTbl") and "3 BIANCHI (K)" in pg.inner_text("#teamsTbl") and "7 ROSSI" in pg.inner_text("#teamsTbl")
        pg.click("#teamsTbl button:text('Modifica')"); time.sleep(.3); assert pg.locator(".prow:not(.head)").count() == 2; pg.fill("input[placeholder='Istruttore (facoltativo)']", "verdi"); pg.click("button:text('Salva squadra')"); time.sleep(.5)
        assert "VERDI" in pg.inner_text("#teamsTbl"); pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_squadre_elenco.png"))
        call("/api/teams", "POST", {"name": "Gufi", "players": [{"number": n, "first_name": f"g{n}", "last_name": f"u{n}", "birth_year": 2013} for n in (11, 4, 8, 2, 6)]})
        pg.goto(B); time.sleep(.4); pg.click("#bNew"); time.sleep(.5); pg.locator("#recall_A").select_option(label="FALCHI (2 giocatori)"); pg.click("button:text('Richiama') >> nth=0"); time.sleep(.3)
        assert pg.input_value("input[placeholder='Nome squadra A']") == "FALCHI" and pg.locator(".prow:not(.head)").count() == 2
        pg.locator("#recall_A").select_option(label="GUFI (5 giocatori)"); pg.click("button:text('Richiama') >> nth=0"); time.sleep(.3)   # conferma sostituzione (dialog accettato)
        assert pg.input_value("input[placeholder='Nome squadra A']") == "GUFI" and pg.locator(".prow:not(.head)").count() == 5
        assert [pg.locator(".prow:not(.head)").nth(i).locator("input").nth(0).input_value() for i in range(5)] == ["2", "4", "6", "8", "11"]   # maglie salvate
        pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_squadra_richiamo.png"))
        pg.locator(".prow:not(.head)").nth(0).locator("input").nth(1).fill("modificato")        # modifica solo per questa partita
        pg.click("button:text('Avanti')"); time.sleep(.3); pg.fill("input[placeholder='Nome squadra B']", "ospiti")
        for i in range(4): fill_row(i, i + 1, f"n{i}", f"b{i}", 2013)
        pg.click("button:text('Avanti')"); time.sleep(.3); pg.click("button:text('Crea partita e inizia')"); time.sleep(.6)
        assert pg.evaluate("M.teams.A.players[0].first_name") == "MODIFICATO" and pg.evaluate("M.teams.A.name") == "GUFI"
        call(f"/api/matches/{pg.evaluate('M.id')}/finish", "POST", {})
        saved = call("/api/teams"); assert [t["players"][0]["first_name"] for t in saved if t["name"] == "GUFI"] == ["G2"]       # squadra salvata invariata
        pg.click("#bTeams"); time.sleep(.4); n_d = len(dialogs); pg.locator("#teamsTbl tr:has-text('GUFI') button:text('Elimina')").click(); time.sleep(.5)
        assert len(dialogs) == n_d + 1 and "Le partite già create non vengono modificate" in dialogs[-1] and "GUFI" not in pg.inner_text("#teamsTbl")
        pg.goto(B); time.sleep(.4); assert "GUFI" in pg.inner_text("#main")                                # partita esistente intatta
        # dettaglio: tooltip e etichette sulla partita conclusa
        pg.goto(B); time.sleep(.4); pg.evaluate(f"statsOf({fin})"); time.sleep(.5)
        assert "falli" not in pg.inner_text("#modal").lower() and "fallo" not in pg.inner_text("#modal").lower(), "statistiche falli presenti"
        sl = pg.locator("#modal .sl").first; assert sl.count() == 1; sl.hover(force=True); time.sleep(.3)
        tip = pg.inner_text("#tip"); assert tip.startswith("#") and "AQ" in tip and " su " in tip and " nel T" in tip and "%" in tip and "totali" not in tip, tip
        assert any("%" in x for x in pg.locator("#modal svg text").all_text_contents())
        assert any(" / " in t or "/" in t for t in pg.locator("#modal svg text").all_text_contents())
        os.makedirs(os.path.join(HERE, "screenshot"), exist_ok=True); pg.screenshot(path=os.path.join(HERE, "screenshot", "shot_statistiche_tooltip.png"))
        # titolo = link alle partite
        pg.keyboard.press("Escape"); pg.evaluate("closeModal()"); pg.evaluate(f"openMatch({fin})"); time.sleep(.4); pg.click("#brand"); time.sleep(.5); assert "Partite" in pg.inner_text("#main") and pg.evaluate("view") == "home"
        br.close()
    assert not errors, errors
    print("UI OK (nessun errore in console)")
finally:
    srv.terminate(); os.path.exists(db) and os.remove(db)
