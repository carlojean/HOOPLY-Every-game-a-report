"""Eseguito UNA volta: estrae dall'Excel originale la geometria (larghezze colonne / altezze righe)
e la mappa sul PDF di riferimento (convertito con LibreOffice) -> template/layout.json.
Calibrazione: la cornice del foglio nel PDF va da x=62.153..779.305 e y=586.523..8.808 (pt)."""
import json, xlrd, sys, os
xls = sys.argv[1] if len(sys.argv) > 1 else "template/referto_originale.xls"
s = xlrd.open_workbook(xls, formatting_info=True).sheet_by_index(0)
cw = [s.colinfo_map[c].width for c in range(77)]
rh = [s.rowinfo_map[r].height for r in range(65)]
kx = (779.305 - 62.153) / sum(cw); ky = (586.523 - 8.808) / sum(rh)
X, acc = [], 0
for w in cw + [0]: X.append(round(62.153 + acc * kx, 3)); acc += w
Y, acc = [], 0
for h in rh + [0]: Y.append(round(586.523 - acc * ky, 3)); acc += h
json.dump({"X": X, "Y": Y}, open(os.path.join(os.path.dirname(__file__), "..", "template", "layout.json"), "w"))
print(len(X), len(Y), X[20], Y[6])
