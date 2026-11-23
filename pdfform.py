"""Compila il referto PDF partendo dal PDF di riferimento (l'Excel originale convertito in PDF, cella per cella)
aggiungendo i dati con un aggiornamento incrementale del PDF. Solo libreria standard Python."""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template", "referto_template.pdf")
LAYOUT = json.load(open(os.path.join(HERE, "template", "layout.json")))
X, Y = LAYOUT["X"], LAYOUT["Y"]
PERIOD_COLORS = [(1, 0.88, 0.25), (1, 0.64, 0.3), (0.55, 0.85, 0.5), (0.55, 0.75, 1), (0.9, 0.6, 0.9)]
GREY, BLUEOT = (0.82, 0.82, 0.82), (0.72, 0.9, 1)
BLOCK_CELLS = 12

def rect(r0, r1, c0, c1):
    """Cella (o cella unita) dell'Excel -> (x0, y0, x1, y1) in pt. r1/c1 esclusi."""
    return X[c0], Y[r1], X[c1], Y[r0]

class Ov:
    def __init__(self): self.o = []
    @staticmethod
    def esc(s): return "(" + s.encode("cp1252", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"
    @staticmethod
    def tw(s, size, bold=False): return sum((0.556 if ch.isdigit() else 0.5) for ch in s) * size * (1.08 if bold else 1)
    def fill(self, box, rgb):
        x0, y0, x1, y1 = box; self.o.append("%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f 0 g" % (*rgb, x0, y0, x1 - x0, y1 - y0))
    def line(self, x0, y0, x1, y1, w=0.5, rgb=(0, 0, 0)):
        self.o.append("%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S 0 G" % (*rgb, w, x0, y0, x1, y1))
    def box(self, b, w=0.5, rgb=(0, 0, 0)):
        self.o.append("%.3f %.3f %.3f RG %.2f w %.2f %.2f %.2f %.2f re S 0 G" % (*rgb, w, b[0], b[1], b[2] - b[0], b[3] - b[1]))
    def ellipse(self, b, w=0.8, rgb=(0.8, 0, 0)):
        cx, cy, rx, ry = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, (b[2] - b[0]) / 2, (b[3] - b[1]) / 2; k = 0.5523
        self.o.append("%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f %.2f %.2f %.2f %.2f c S 0 G" % (
            *rgb, w, cx + rx, cy, cx + rx, cy + k*ry, cx + k*rx, cy + ry, cx, cy + ry, cx - k*rx, cy + ry, cx - rx, cy + k*ry, cx - rx, cy,
            cx - rx, cy - k*ry, cx - k*rx, cy - ry, cx, cy - ry, cx + k*rx, cy - ry, cx + rx, cy - k*ry, cx + rx, cy))
    def text(self, x, y, s, size=6, font="RF1", rgb=(0, 0, 0)):
        if s != "": self.o.append("BT %.3f %.3f %.3f rg /%s %.2f Tf %.2f %.2f Td %s Tj ET 0 g" % (*rgb, font, size, x, y, self.esc(s)))
    def ctext(self, box, s, size=6, font="RF1", rgb=(0, 0, 0), dy=0):
        w = self.tw(s, size, font == "RF2"); self.text((box[0] + box[2]) / 2 - w / 2, (box[1] + box[3]) / 2 - size * 0.35 + dy, s, size, font, rgb)
    def ltext(self, box, s, size=7, font="RF1", pad=1.5, bottom=1.2):
        """Testo allineato a sinistra e in basso (sulla riga di sottolineatura), ridotto per stare nella cella."""
        while size > 3.5 and self.tw(s, size) > box[2] - box[0] - pad * 2: size -= 0.25
        self.text(box[0] + pad, box[1] + bottom, s, size, font)

def fit_text(s, w, size):
    while s and Ov.tw(s, size) > w: s = s[:-1]
    return s

# ---------- distribuzione dei canestri nelle 12 celle di ogni tempo ----------
def blocks_for_excel(seq, n_reg):
    """seq: lista di liste (un elemento per periodo, l'ultimo e' il supplementare se presente).
    Ritorna 4 blocchi: ogni blocco = (token [(testo, tipo)], compatto?). Tipi: own / carry (dal tempo prima) / ot.
    Canestri oltre le 12 celle -> proseguono nel tempo successivo (carry). Ultimo blocco: modalita' compatta, nessuna perdita."""
    nb = max(1, min(n_reg, 4)); blocks = [([], False) for _ in range(4)]; carry = []
    for k in range(nb):
        toks = list(carry) + [(str(v), "own") for v in (seq[k] if k < len(seq) else [])]
        if k == nb - 1:
            if len(seq) > n_reg: toks += [(str(v), "ot") for q in seq[n_reg:] for v in q]
            blocks[k] = (toks, len(toks) > BLOCK_CELLS)
        else:
            blocks[k] = (toks[:BLOCK_CELLS], False); carry = [(t, "carry") for t, _ in toks[BLOCK_CELLS:]]
    return blocks

def draw_block(ov, r, k, toks, compact):
    c0 = 29 + 12 * k
    if not compact:
        for i, (t, kind) in enumerate(toks):
            b = rect(r, r + 1, c0 + i, c0 + i + 1)
            if kind == "carry": ov.fill(b, GREY)
            elif kind == "ot": ov.fill(b, BLUEOT)
            ov.ctext(b, t, 7, "RF3" if kind == "carry" else "RF2")
    else:
        b = rect(r, r + 1, c0, c0 + BLOCK_CELLS)
        size = 7.0
        while size > 3.2 and sum(Ov.tw(t, size) + size * 0.35 for t, _ in toks) > b[2] - b[0] - 2: size -= 0.2
        x = b[0] + 1; y = (b[1] + b[3]) / 2 - size * 0.35
        for t, kind in toks:
            w = Ov.tw(t, size)
            if kind == "carry": ov.fill((x - 0.3, b[1] + 0.5, x + w + 0.3, b[3] - 0.5), GREY)
            elif kind == "ot": ov.fill((x - 0.3, b[1] + 0.5, x + w + 0.3, b[3] - 0.5), BLUEOT)
            ov.text(x, y, t, size, "RF3" if kind == "carry" else "RF2"); x += w + size * 0.35

def highlights(prog):
    """Totali da evidenziare nel progressivo: il cumulato a fine di ogni tempo (es. 2,6,9,14)."""
    return [v for v in prog]

def progressive_cell(n):
    if n <= 20: return 35, 37 + 2 * (n - 1)
    r = 36 + (n - 21) // 24; return r, 29 + 2 * ((n - 21) % 24)

def draw_progressive(ov, off, prog, labels):
    """Griglia del punteggio progressivo: i numeri raggiunti sono barrati, il totale a fine di ogni tempo e' evidenziato."""
    score = prog[-1] if prog else 0
    ends = {}
    for k, v in enumerate(prog):
        if v > 0: ends.setdefault(v, []).append(k)
    for n in range(1, min(score, 92) + 1):
        r, c = progressive_cell(n); b = rect(r + off, r + off + 1, c, c + 2)
        if n in ends:
            ks = ends[n]; w = (b[2] - b[0]) / len(ks)
            for i, k in enumerate(ks): ov.fill((b[0] + i * w, b[1], b[0] + (i + 1) * w, b[3]), PERIOD_COLORS[min(k, 4)])
            ov.ctext(b, str(n), 6.5, "RF2"); ov.box(b, 0.7, (0, 0, 0))
        else:
            ov.line(b[0] + 1, b[1] + 1, b[2] - 1, b[3] - 1, 0.45, (0.55, 0.1, 0.1))

def draw_team(ov, t, side, off, n_reg, coach, page=0):
    ov.ltext(rect(21 + off, 22 + off, 6, 18), t["name"], 6.5, "RF2", bottom=0.6)
    blocks_left = None
    for i, p in enumerate(t["players"][12 * page:12 * page + 12]):
        r = 23 + off + i
        ov.ctext(rect(r, r + 1, 18, 20), str(p["number"]), 7, "RF2")
        ov.ltext(rect(r, r + 1, 2, 18), f'{p["last_name"]} {p["first_name"]} ({p["birth_year"]})', 6.5, "RF1", bottom=2.2)
        for k in range(4):
            if (k + 1) in p.get("entries", []): ov.ctext(rect(r, r + 1, 20 + k, 21 + k), "X", 7, "RF2")
        for j, ft in enumerate(p.get("foul_tempi", [])[:5]):
            b = rect(r, r + 1, 24 + j, 25 + j)
            if j == 4: ov.fill(b, (1, 0.6, 0.6))
            ov.ctext(b, ("S" if ft > n_reg else str(ft)), 6.5, "RF2")
        for k, (toks, compact) in enumerate(blocks_for_excel(p["seq"], n_reg)): draw_block(ov, r, k, toks, compact)
    for k in range(min(n_reg, 4)):
        for j in range(min(t["team_fouls"][k], 5)):
            b = rect(21 + off, 22 + off, 36 + 12 * k + j, 37 + 12 * k + j)
            ov.line(b[0] + 0.8, b[1] + 0.8, b[2] - 0.8, b[3] - 0.8, 0.7, (0.75, 0, 0)); ov.line(b[0] + 0.8, b[3] - 0.8, b[2] - 0.8, b[1] + 0.8, 0.7, (0.75, 0, 0))
    if coach: ov.ltext(rect(35 + off, 36 + off, 7, 20), coach, 6.5, "RF1")
    draw_progressive(ov, off, t["progressivo"], None)

def draw_awards(ov, s):
    n = s["n_tempi"]
    for side, c0 in (("A", 11), ("B", 16)):
        aw = s["teams"][side]["awarded"]
        for k, v in enumerate(aw):
            if v is None: continue
            row = 60 + k if k < n else 64     # il supplementare usa la riga "Gioco spareggio"
            b = rect(row, row + 1, c0 + v, c0 + v + 1)
            ov.fill(b, PERIOD_COLORS[min(k, 4)]); ov.ellipse(b, 0.8, (0.7, 0, 0)); ov.ctext(b, str(v), 6.5, "RF2")

def n_pages(s):
    return 2 if max(len(s["teams"]["A"]["players"]), len(s["teams"]["B"]["players"])) > 12 else 1

def build_overlay_excel(s, page=0):
    ov = Ov(); h = s.get("header", {}); n = s["n_tempi"]
    A, B = s["teams"]["A"], s["teams"]["B"]
    ov.ltext(rect(8, 9, 7, 19), h.get("category", ""), 7)
    ov.ltext(rect(8, 9, 24, 28), h.get("girone", ""), 7)
    ov.ltext(rect(8, 9, 33, 39), str(h.get("gara_n") or s["id"]), 7)
    d = s["created"].split(" ")
    ov.ltext(rect(8, 9, 41, 51), "/".join(reversed(d[0].split("-"))), 7)
    ov.ltext(rect(8, 9, 53, 58), d[1] if len(d) > 1 else "", 7)
    ov.ltext(rect(8, 9, 64, 77), h.get("venue", ""), 7)
    ov.ltext(rect(13, 14, 8, 45), A["name"], 7.5, "RF2"); ov.ltext(rect(13, 14, 50, 77), B["name"], 7.5, "RF2")
    ov.ltext(rect(18, 19, 5, 39), h.get("arbitri", ""), 7); ov.ltext(rect(18, 19, 44, 58), h.get("segnapunti", ""), 7)
    ov.ltext(rect(18, 19, 67, 77), h.get("cronometrista", ""), 7)
    draw_team(ov, A, "A", 0, n, A.get("coach", ""), page); draw_team(ov, B, "B", 18, n, B.get("coach", ""), page)
    if n_pages(s) > 1:   # foglio 1: primi 12 giocatori per squadra; foglio 2: i restanti; intestazione, falli, progressivo e punteggio uguali
        lab = f"Foglio {page + 1} di 2 - giocatori " + ("1-12" if page == 0 else "dal 13") + " di ogni squadra"
        ov.text(X[77] - Ov.tw(lab, 6.2, True) - 2, 547.3, lab, 6.2, "RF2", (0.7, 0, 0))
    if s.get("forfeit"):   # partita terminata per forfait: nota in testata (rosso, grassetto)
        ov.text(X[11] + 4, 547.3, fit_text(s["forfeit"]["text"].upper(), X[77] - X[11] - 200, 5.6), 5.6, "RF2", (0.8, 0, 0))
    draw_awards(ov, s)
    # punteggio finale (sulle righe tratteggiate "A ......" e "B ......")
    for side, base in (("A", 36.8), ("B", 14.6)):
        t = s["teams"][side]
        ov.text(X[20] + 9, base, fit_text(t["name"], X[32] - X[20] - 12, 7), 7, "RF1")
        ov.ctext((X[31], base - 2.5, X[33], base + 9), str(t["score"]), 10, "RF2")
    # legenda (spazio libero sotto "PUNTEGGIO FINALE")
    x = X[20] + 2; yb = 60.2
    for k in range(min(n, 4) + (1 if s["has_ot"] else 0)):
        b = (x, yb - 0.3, x + 6, yb + 4.4); ov.fill(b, PERIOD_COLORS[min(k, 4)]); ov.box(b, 0.3)
        lab = f"T{k+1}" if k < n else "Suppl."; ov.text(x + 7, yb + 0.6, lab, 4.6, "RF1"); x += 8 + Ov.tw(lab, 4.6) + 3
    for i, line in enumerate(("Progressivo: evidenziato il totale a fine tempo, barrati i punti raggiunti.",
                              "Celle punti: grigio/corsivo = canestri del tempo prec. oltre le 12 celle;",
                              "azzurro = supplementare (punti assegnati su 'Gioco spareggio').")):
        ov.text(X[20] + 2, 55.5 - i * 4.7, line, 4.2, "RF1")
    return "\n".join(ov.o)

# ---------- aggiornamento incrementale del PDF di riferimento ----------
PAGE_OBJ, FONT_DICT_OBJ, PAGES_OBJ = 1, 5515, 5486

def make_pdf_excel(s):
    base = open(TEMPLATE, "rb").read()
    m = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", base); prev = int(m.group(1))
    size = int(re.search(rb"/Size (\d+)", base[base.rindex(b"trailer"):]).group(1))
    pages = n_pages(s)
    nxt = size
    f1, f2, f3 = nxt, nxt + 1, nxt + 2; nxt += 3
    pg = re.search(rb"\n1 0 obj\n(<<.*?>>)\nendobj", base, re.S).group(1)
    objs = {FONT_DICT_OBJ: b"<</F1 5494 0 R/F2 5491 0 R/RF1 %d 0 R/RF2 %d 0 R/RF3 %d 0 R>>" % (f1, f2, f3),
        f1: b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>",
        f2: b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>",
        f3: b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Oblique/Encoding/WinAnsiEncoding>>"}
    kids = [b"1 0 R"]
    for p in range(pages):
        content = build_overlay(s, p).encode("latin-1"); cnum = nxt; nxt += 1
        objs[cnum] = b"<</Length %d>>\nstream\n" % len(content) + content + b"\nendstream"
        if p == 0:
            objs[PAGE_OBJ] = pg.replace(b"/Contents 2 0 R", b"/Contents [2 0 R %d 0 R]" % cnum)
        else:   # altri fogli: stessa pagina del modello (stesso contenuto di base) + i dati del foglio
            pnum = nxt; nxt += 1
            objs[pnum] = pg.replace(b"/Contents 2 0 R", b"/Contents [2 0 R %d 0 R]" % cnum).replace(b"/StructParents 0", b"")
            kids.append(b"%d 0 R" % pnum)
    if pages > 1:
        objs[PAGES_OBJ] = b"<</Type/Pages/Resources 5516 0 R/Kids[ " + b" ".join(kids) + b" ]/Count %d>>" % pages
    out = bytearray(base)
    if not out.endswith(b"\n"): out += b"\n"
    offs = {}
    for num in sorted(objs):
        offs[num] = len(out); out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xr = len(out); out += b"xref\n"
    for num in sorted(offs): out += b"%d 1\n%010d 00000 n \n" % (num, offs[num])
    out += b"trailer\n<</Size %d/Root 5522 0 R/Info 5523 0 R/Prev %d>>\nstartxref\n%d\n%%%%EOF\n" % (nxt, prev, xr)
    return bytes(out)


# ---- generatore predefinito: referto CSI "Under 9-10-11" (pdfcsi.py); il vecchio modello Excel resta in *_excel ----
def blocks_for(seq, n_reg):
    import pdfcsi; return pdfcsi.blocks_for(seq, n_reg)
def build_overlay(s, page=0):
    import pdfcsi; return pdfcsi.build_page(s, page)
def make_pdf(s):
    import pdfcsi; return pdfcsi.make_pdf(s)
