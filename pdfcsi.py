"""Referto 'Pallacanestro Under 9-10-11' (stile CSI): generato da zero, in vettoriale, solo libreria standard Python.
Pagina A4 orizzontale; 12 giocatori per squadra per foglio (oltre 12 -> secondo foglio); 6 periodi + supplementare."""
import datetime
from pdfform import Ov, fit_text

PW, PH = 841.89, 595.28
BLUE = (0.05, 0.18, 0.78)          # inchiostro dei dati (come la penna blu del referto a mano)
GREY, BLUEOT = (0.82, 0.82, 0.82), (0.8, 0.9, 1)
PCOL = [(1, 0.92, 0.55), (1, 0.8, 0.6), (0.7, 0.9, 0.65), (0.7, 0.82, 1), (0.9, 0.75, 0.9), (1, 0.75, 0.75), (0.75, 0.95, 0.95)]
CELLS = 8                          # canestri per casella-periodo (ogni canestro occupa 2 quadretti)
XL, XR = 22.0, 820.0
XS = [22, 46, 68, 196, 214, 284, 329]   # anno | tess | nominativo | n | entrate(7x10) | falli(5x9) | fine
BW = (XR - XS[-1]) / 7
RH = 13.0                          # altezza riga giocatore

def R(x0, t0, x1, t1): return (x0, PH - t1, x1, PH - t0)

def blocks_for(seq, n_reg):
    """7 blocchi: periodi 1..6 e supplementare (indice 6). seq = lista per periodo (l'ultimo e' il supplementare se presente).
    Ogni blocco = (token [(testo, tipo)], compatto?). Tipi: own / carry (dal periodo prima, oltre le caselle) / ot.
    Oltre CELLS canestri -> proseguono nel periodo successivo (carry); l'ultimo periodo regolare e il supplementare
    usano la modalita' compatta: nessun canestro viene perso."""
    per, ot = blocks_all(seq, n_reg)
    if n_reg <= 6: return per + [([], False)] * (6 - n_reg) + [ot]
    return per + [ot]

def blocks_all(seq, n_reg):
    """Come blocks_for ma senza limite di periodi: (blocchi dei periodi regolari 1..n_reg, blocco supplementare). I canestri che non
    entrano nelle caselle proseguono nel periodo successivo anche attraverso il cambio di foglio (6 -> 7)."""
    n_reg = max(1, n_reg); blocks = [([], False) for _ in range(n_reg)]; carry = []; ot_b = ([], False)
    for k in range(n_reg):
        toks = list(carry) + [(str(v), "own") for v in (seq[k] if k < len(seq) else [])]
        if k == n_reg - 1: blocks[k] = (toks, len(toks) > CELLS)
        else: blocks[k] = (toks[:CELLS], False); carry = [(t, "carry") for t, _ in toks[CELLS:]]
    if len(seq) > n_reg:
        toks = [(str(v), "ot") for q in seq[n_reg:] for v in q]; ot_b = (toks, len(toks) > CELLS)
    return blocks, ot_b

def draw_block(ov, x0, t0, toks, compact):
    cw = BW / CELLS; box = R(x0, t0, x0 + BW, t0 + RH)
    if not compact:
        for i, (t, kind) in enumerate(toks):
            b = (x0 + i * cw, box[1], x0 + (i + 1) * cw, box[3])
            if kind == "carry": ov.fill(b, GREY)
            ov.ctext(b, t, 7.5, "RF3" if kind == "carry" else "RF2", BLUE)
            if kind == "ot": ov.ellipse((b[0] + 0.3, b[1] + 1, b[2] - 0.3, b[3] - 1), 0.6, BLUE)
    else:
        size = 7.0
        while size > 3.2 and sum(Ov.tw(t, size) + size * 0.35 for t, _ in toks) > BW - 2: size -= 0.2
        x = x0 + 1; y = (box[1] + box[3]) / 2 - size * 0.35
        for t, kind in toks:
            w = Ov.tw(t, size)
            if kind == "carry": ov.fill((x - 0.3, box[1] + 0.5, x + w + 0.3, box[3] - 0.5), GREY)
            ov.text(x, y, t, size, "RF3" if kind == "carry" else "RF2", BLUE)
            if kind == "ot": ov.ellipse((x - 0.8, box[1] + 1, x + w + 0.8, box[3] - 1), 0.5, BLUE)
            x += w + size * 0.35

def label(ov, x, t, s, size=6.5, font="RF2"): ov.text(x, PH - t, s, size, font)
def hline(ov, x0, x1, t, w=0.5, rgb=(0, 0, 0)): ov.line(x0, PH - t, x1, PH - t, w, rgb)
def vline(ov, x, t0, t1, w=0.5, rgb=(0, 0, 0)): ov.line(x, PH - t0, x, PH - t1, w, rgb)
FINE = (0.72, 0.72, 0.72)

def field(ov, x0, x1, t, value="", size=7.5):
    """Riga di compilazione tratteggiata con eventuale valore (inchiostro blu)."""
    ov.line(x0, PH - t, x1, PH - t, 0.3, (0.55, 0.55, 0.55))
    if value: ov.text(x0 + 2, PH - t + 1.4, fit_text(value, x1 - x0 - 3, size), size, "RF2", BLUE)

def draw_header(ov, s, page, pages, q=0, pp=0, P=1):
    # titolo
    ov.box(R(XL, 12, XR, 42), 0.9)
    for lx in (XL + 6, XR - 56):
        ov.box(R(lx, 17, lx + 50, 37), 0.7); ov.ctext(R(lx, 17, lx + 50, 37), "C.S.I.", 12, "RF2", (0.1, 0.1, 0.5))
    ov.ctext(R(XL, 14, XR, 28), "REFERTO DI GARA", 11, "RF2"); ov.ctext(R(XL, 28, XR, 41), "PALLACANESTRO UNDER 9 - UNDER 10 - UNDER 11", 12, "RF2")
    if pages > 1:
        lab = f"Foglio {page + 1} di {pages}"; ov.text(XR - 60 - Ov.tw(lab, 6.5, True), PH - 24, lab, 6.5, "RF2", (0.75, 0, 0))
        sub = []
        if period_sheets(s) > 1: sub.append(f"periodi {6 * q + 1}-{min(6 * q + 6, s['n_tempi'])}" + (" + suppl." if q == 0 else ""))
        if P > 1: sub.append("giocatori 1-12" if pp == 0 else "giocatori 13+")
        sl = ", ".join(sub); ov.text(XR - 60 - Ov.tw(sl, 5.5, True), PH - 31, sl, 5.5, "RF3", (0.75, 0, 0))
    # intestazione
    ov.box(R(XL, 45, XR, 76), 0.9); h = s["header"]; A, B = s["teams"]["A"], s["teams"]["B"]
    d = s["created"].split(" "); data = "/".join(reversed(d[0].split("-"))) if d and d[0] else ""; ora = d[1] if len(d) > 1 else ""
    arb = [a.strip() for a in (h.get("arbitri") or "").split("/")] + ["", ""]
    cols = [(XL + 4, [("GARA N°", h.get("gara_n", "")), ("CATEGORIA", h.get("category", "")), ("LOCALITA'", "")], 60, 150),
            (XL + 170, [("SQUADRA A", A["name"]), ("GIRONE", h.get("girone", "")), ("CAMPO", h.get("venue", ""))], 54, 158),
            (XL + 338, [("", ""), ("DATA", data), ("ORA", ora)], 28, 110),
            (XL + 466, [("SQUADRA B", B["name"]), ("1° ARBITRO", arb[0]), ("2° ARBITRO", arb[1])], 56, 170),
            (XL + 650, [("", ""), ("N° TESS", ""), ("N° TESS", "")], 38, 122)]
    for x, rows, lw, fw in cols:
        for i, (lab, val) in enumerate(rows):
            t = 45 + 10.3 * (i + 1) - 1.3
            if lab: ov.text(x, PH - t + 0.4, lab, 6.8, "RF2"); field(ov, x + lw, x + lw + fw - 8, t, val, 7.5 if i else 8.5)

def draw_team(ov, s, side, t0, page, n_reg, has_ot, q=0):
    t = s["teams"][side]; ink = BLUE
    ov.box(R(XL, t0, XS[-1], t0 + 29), 0.9)
    label(ov, XL + 3, t0 + 8, f"SQUADRA {side}", 7.5)
    ov.text(XL + 56, PH - t0 - 8, fit_text(t["name"], XS[-1] - XL - 60, 8.5), 8.5, "RF2", ink)
    hline(ov, XL, XS[3], t0 + 10, 0.4); label(ov, XL + 3, t0 + 17, "COLORE MAGLIA", 5.5, "RF1")
    hline(ov, XL, XS[3], t0 + 18, 0.4)
    # intestazione colonne
    for x, txt in ((XS[0], "Anno"), (XS[1], "Tess"), (XS[2] + 40, "Nominativo"), (XS[3], "N°")):
        label(ov, x + 2, t0 + 26.5, txt, 6.2, "RF1")
    label(ov, XS[4] + 6, t0 + 16, "Entrate in gioco", 5.2, "RF1")
    for i, lab in enumerate([str(6 * q + j + 1) for j in range(6)] + ["S" if q == 0 else ""]): ov.ctext(R(XS[4] + 10 * i, t0 + 18, XS[4] + 10 * i + 10, t0 + 29), lab, 6, "RF1")
    ov.ctext(R(XS[5], t0, XS[6], t0 + 18), "Falli", 7, "RF1")
    for i in range(5): ov.ctext(R(XS[5] + 9 * i, t0 + 18, XS[5] + 9 * i + 9, t0 + 29), str(i + 1), 6, "RF1")
    # blocchi periodo
    ov.box(R(XS[6], t0, XR, t0 + 10), 0.9); ov.ctext(R(XS[6], t0, XR, t0 + 10), "PUNTI SEGNATI", 7.5, "RF1")
    for k in range(7):
        gk = 6 * q + k; x0 = XS[6] + k * BW; lab = f"{gk + 1}° Periodo" if k < 6 else ("Supplement." if q == 0 else "")
        used = (k < 6 and gk < n_reg) or (k == 6 and q == 0 and has_ot)
        ov.ctext(R(x0, t0 + 10, x0 + BW, t0 + 29), lab, 7, "RF1" if used else "RF3", (0, 0, 0) if used else (0.55, 0.55, 0.55))
    top = t0 + 29; bot = top + 12 * RH
    # griglie
    for i in range(13): hline(ov, XL, XR, top + i * RH, 0.45 if i not in (0, 12) else 0.9, (0.25, 0.25, 0.25) if i not in (0, 12) else (0, 0, 0))
    for x in XS[:6]: vline(ov, x, top, bot, 0.6)
    for i in range(1, 7): vline(ov, XS[4] + 10 * i, top, bot, 0.3, FINE)
    for i in range(1, 5): vline(ov, XS[5] + 9 * i, top, bot, 0.3, FINE)
    for i in range(1, 7): vline(ov, XS[4] + 10 * i, t0 + 18, t0 + 29, 0.3, FINE)
    for k in range(8):
        x = XS[6] + k * BW; vline(ov, x, t0 + 10, bot, 0.9)
        if k < 7:
            for j in range(1, 16): vline(ov, x + j * BW / 16, top, bot, 0.4 if j % 2 == 0 else 0.2, (0.45, 0.45, 0.45) if j % 2 == 0 else (0.7, 0.7, 0.7))
    # giocatori
    for i, p in enumerate(t["players"][12 * page:12 * page + 12]):
        tt = top + i * RH; bx = R(XL, tt, XS[1], tt + RH)
        ov.ctext(R(XS[0], tt, XS[1], tt + RH), str(p["birth_year"]), 6.5, "RF2", ink)
        ov.text(XS[2] + 3, PH - tt - RH + 3.2, fit_text(f'{p["last_name"]} {p["first_name"]}' + (" (K)" if p.get("captain") else ""), XS[3] - XS[2] - 5, 7.5), 7.5, "RF2", ink)
        ov.ctext(R(XS[3], tt, XS[4], tt + RH), str(p["number"]), 8, "RF2", ink)
        for k in p.get("entries", []):
            idx = (6 if q == 0 else -1) if k > n_reg else k - 1 - 6 * q
            if 0 <= idx <= 6: ov.ctext(R(XS[4] + 10 * idx, tt, XS[4] + 10 * idx + 10, tt + RH), "X", 8, "RF2", ink)
        for j in range(min(len(p.get("foul_tempi", [])), 5)):
            ov.ctext(R(XS[5] + 9 * j, tt, XS[5] + 9 * j + 9, tt + RH), "p", 8, "RF2", ink)
        per, otb = blocks_all(p["seq"], n_reg)
        for k, (toks, compact) in enumerate([per[6 * q + j] if 6 * q + j < n_reg else ([], False) for j in range(6)] + [otb if q == 0 else ([], False)]):
            if toks: draw_block(ov, XS[6] + k * BW, tt, toks, compact)
            if toks and toks[0][1] == "carry" and (k > 0 or q > 0):   # sforamento: segno di delimitazione a fine del periodo precedente
                xe = XS[6] + k * BW; ov.line(xe - 6, PH - tt - 1, xe - 1, PH - tt - RH + 1, 0.8, BLUE)
    # riga staff + progressivo
    st = bot + 0; hh = 9
    ov.box(R(XL, st, XS[6], st + 3 * hh), 0.7)
    for i, (lab, val) in enumerate((("Allenatore", t.get("coach", "")), ("Aiuto All.", ""), ("Dir. Acc.", ""))):
        tt = st + i * hh; hline(ov, XL, 232, tt, 0.3, (0.6, 0.6, 0.6)); label(ov, XL + 2, tt + 6.8, lab, 5.5, "RF1")
        if val: ov.text(XL + 40, PH - tt - 7, fit_text(val, 110, 6.5), 6.5, "RF2", ink)
        label(ov, 172, tt + 6.8, "Tess.", 5.5, "RF1")
    vline(ov, 232, st, st + 3 * hh, 0.5)
    label(ov, 262, st + 7, "Sospensioni", 5.5, "RF2")
    for i, lab in enumerate(["1", "2", "3", "4", "5", "6", "S"]):
        b = R(236 + 13 * i, st + 10, 236 + 13 * i + 13, st + 21); ov.box(b, 0.5); ov.ctext(b, lab, 5.5, "RF1")
    # progressivo (1..120, blocchi 3° periodo -> supplementare)
    ov.ctext(R(XS[6], st, XS[6] + 2 * BW, st + 3 * hh), "Punti Progressivi", 6, "RF1")
    cw = BW / 8; x0 = XS[6] + 2 * BW
    ov.box(R(x0, st, XR, st + 3 * hh), 0.8)
    ends = {}
    for k, v in enumerate(t["progressivo"]):
        if v > 0: ends.setdefault(v, []).append(k)
    for n in range(1, 121):
        r, c = (n - 1) // 40, (n - 1) % 40; b = R(x0 + c * cw, st + r * hh, x0 + (c + 1) * cw, st + (r + 1) * hh)
        ov.box(b, 0.25, (0.5, 0.5, 0.5))
        if n in ends:
            ks = ends[n]; w = cw / len(ks)
            for i, k in enumerate(ks): ov.fill((b[0] + i * w, b[1], b[0] + (i + 1) * w, b[3]), PCOL[k % 6 if k < n_reg else 6])
        ov.ctext(b, str(n), 4.6, "RF2" if n in ends else "RF1")
        if n <= t["progressivo"][-1] and n not in ends: ov.line(b[0] + 1, b[1] + 1, b[2] - 1, b[3] - 1, 0.5, BLUE)
        if n in ends:
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2; ov.ellipse((cx - 5, cy - 4.4, cx + 5, cy + 4.4), 0.9, BLUE)
    for r in range(1, 3): hline(ov, x0, XR, st + r * hh, 0.3, (0.5, 0.5, 0.5))
    return bot + 3 * hh

def circle_digit(ov, b, color=BLUE): ov.ellipse((b[0] + 0.7, b[1] + 0.7, b[2] - 0.7, b[3] - 0.7), 0.9, color)

def draw_bottom(ov, s, t0, n_reg, q=0):
    A, B = s["teams"]["A"], s["teams"]["B"]; n = len(A["awarded"])
    # tabella punti per periodo (3 2 1)
    label(ov, XL + 14, t0 + 38, "Punti", 8, "RF1")
    for r in range(7):
        tt = t0 + r * 10; ov.box(R(60, tt, 160, tt + 10), 0.5)
        ov.ctext(R(60, tt, 160, tt + 10), f"{6 * q + r + 1}° Periodo" if r < 6 else ("Supplementari" if q == 0 else ""), 7.5, "RF1")
        for side, x in (("A", 160), ("B", 222)):
            ov.ctext(R(x, tt, x + 12, tt + 10), side, 7, "RF2")
            for j, v in enumerate((3, 2, 1)):
                b = R(x + 12 + 12 * j, tt, x + 24 + 12 * j, tt + 10); ov.box(b, 0.5); ov.ctext(b, str(v), 7, "RF1")
                k = r if r < 6 else None
                got = None
                if r < 6 and 6 * q + r < n_reg and 6 * q + r < n: got = s["teams"][side]["awarded"][6 * q + r]
                if r == 6 and q == 0 and s["has_ot"] and n > n_reg: got = s["teams"][side]["awarded"][n_reg]
                if got == v: ov.ctext(b, "X", 8, "RF2", BLUE)
    # punteggio finale
    x0, x1 = 292, 566; ov.box(R(x0, t0, x1, t0 + 70), 0.9); ov.ctext(R(x0, t0, x1, t0 + 10), "PUNTEGGIO FINALE", 8, "RF2"); hline(ov, x0, x1, t0 + 10, 0.8)
    label(ov, x0 + 5, t0 + 25, "A", 8, "RF2"); ov.box(R(x0 + 16, t0 + 14, x0 + 70, t0 + 29), 0.6)
    ov.ctext(R(x0 + 16, t0 + 14, x0 + 70, t0 + 29), str(A["final"]), 11, "RF2", BLUE)
    label(ov, x0 + 82, t0 + 25, "B", 8, "RF2"); ov.box(R(x0 + 94, t0 + 14, x0 + 148, t0 + 29), 0.6)
    ov.ctext(R(x0 + 94, t0 + 14, x0 + 148, t0 + 29), str(B["final"]), 11, "RF2", BLUE)
    label(ov, x0 + 158, t0 + 25, "DTS", 7, "RF2")
    for lab, xx in (("NO", x0 + 184), ("SI", x0 + 218)):
        bb = R(xx, t0 + 15, xx + 22, t0 + 28); ov.ctext(bb, lab, 6.5, "RF1")
        if (lab == "SI") == bool(s["has_ot"]): ov.ellipse((bb[0], bb[1], bb[2], bb[3]), 0.9, BLUE)
    hline(ov, x0, x1, t0 + 31, 0.6)
    aa, bb_ = A["score"], B["score"]; res = s["result"]; tied = res["tie"]
    win = s["teams"][res["winner"]]["name"] if res["winner"] else ""
    label(ov, x0 + 5, t0 + 41, "SQUADRA", 7, "RF2"); label(ov, x0 + 5, t0 + 50, "VINCENTE", 7, "RF2")
    ov.text(x0 + 62, PH - t0 - 47, fit_text(win, 120, 8.5), 8.5, "RF2", BLUE)
    if res["reason"]: ov.text(x0 + 62, PH - t0 - 53, "(13-12 per " + res["reason"] + ")", 5.2, "RF3", BLUE)
    ov.box(R(x0 + 192, t0 + 33, x0 + 270, t0 + 50), 0.5); ov.ctext(R(x0 + 192, t0 + 33, x0 + 270, t0 + 40), "PROGRESSIVO", 5.2, "RF2")
    vline(ov, x0 + 231, t0 + 40, t0 + 50, 0.4); hline(ov, x0 + 192, x0 + 270, t0 + 40, 0.4)
    ov.ctext(R(x0 + 192, t0 + 40, x0 + 231, t0 + 50), "A  " + str(aa), 6.5, "RF2", BLUE); ov.ctext(R(x0 + 231, t0 + 40, x0 + 270, t0 + 50), "B  " + str(bb_), 6.5, "RF2", BLUE)
    hline(ov, x0, x1, t0 + 54, 0.6)
    label(ov, x0 + 5, t0 + 62, "PAREGGIO", 7, "RF2"); label(ov, x0 + 5, t0 + 69, "UNDER 9", 7, "RF2")
    bb = R(x0 + 76, t0 + 56, x0 + 100, t0 + 69); ov.ctext(bb, "SI", 6.5, "RF1")
    if tied and not s.get("forfeit"): ov.ellipse(bb, 0.9, BLUE)   # pareggio (ammesso in Under 9)
    # firme
    h = s["header"]
    for i, (lab, val, tess) in enumerate((("REFERTISTA", h.get("segnapunti", ""), True), ("CRONOMETRISTA", h.get("cronometrista", ""), True), ("FIRMA 1° ARBITRO", "", False), ("FIRMA 2° ARBITRO", "", False))):
        tt = t0 + 18 + i * 15; label(ov, 596, tt, lab, 7.5, "RF1" if False else "RF2"); field(ov, 680, 744 if tess else 818, tt + 1, val, 7)
        if tess: label(ov, 748, tt, "Tessera N°", 7, "RF1"); field(ov, 790, 818, tt + 1)

def build_page(s, page=0):
    ov = Ov(); pages = n_pages(s); n_reg = s["n_tempi"]; has_ot = bool(s["has_ot"])
    P = player_sheets(s); q, pp = divmod(page, P)     # ordine fogli: per ogni gruppo di 6 periodi, i fogli dei giocatori (1-12, 13-24)
    draw_header(ov, s, page, pages, q, pp, P)
    e = draw_team(ov, s, "A", 80, pp, n_reg, has_ot, q)
    e = draw_team(ov, s, "B", e + 4, pp, n_reg, has_ot, q)
    draw_bottom(ov, s, e + 6, n_reg, q)
    y = 586
    if s.get("forfeit"): ov.text(XL, PH - y + 2, s["forfeit"]["text"].upper(), 7.5, "RF2", (0.8, 0, 0)); y -= 0
    note = "p = fallo. Grigio/corsivo dopo il segno \\ : canestri che sforano dal periodo precedente. Cerchiati: canestri del supplementare. Progressivo: barrati i punti raggiunti, cerchiato il totale a fine periodo. Punteggio finale = punti per periodo (a parita': +1 alla squadra avanti nel progressivo, poi supplementari: 13-12)."
    ov.text(XL, 4.5, note, 4.8, "RF1", (0.4, 0.4, 0.4))
    return "\n".join(ov.o)

def player_sheets(s):
    return 2 if max(len(s["teams"]["A"]["players"]), len(s["teams"]["B"]["players"])) > 12 else 1

def period_sheets(s):
    return max(1, -(-s["n_tempi"] // 6))     # 1-6 + supplementare nel primo foglio, 7-12 nel secondo

def n_pages(s):
    return player_sheets(s) * period_sheets(s)

def make_pdf(s):
    pages = n_pages(s); objs = []
    def add(b): objs.append(b); return len(objs)
    add(b"<</Type/Catalog/Pages 2 0 R>>"); add(b"")   # 1, 2 (Pages riempito dopo)
    f1 = add(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    f2 = add(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>")
    f3 = add(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Oblique/Encoding/WinAnsiEncoding>>")
    kids = []
    for p in range(pages):
        content = build_page(s, p).encode("cp1252", "replace"); c = add(b"<</Length %d>>\nstream\n" % len(content) + content + b"\nendstream")
        kids.append(add(b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 %.2f %.2f]/Contents %d 0 R/Resources<</Font<</RF1 %d 0 R/RF2 %d 0 R/RF3 %d 0 R>>>>>>" % (PW, PH, c, f1, f2, f3)))
    objs[1] = b"<</Type/Pages/Count %d/Kids[%s]>>" % (pages, b" ".join(b"%d 0 R" % k for k in kids))
    out = bytearray(b"%PDF-1.4\n"); offs = []
    for i, o in enumerate(objs, 1): offs.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xr = len(out); out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs: out += b"%010d 00000 n \n" % o
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xr)
    return bytes(out)
