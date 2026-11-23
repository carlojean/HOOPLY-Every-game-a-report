"""Genera le icone HOOPLY da un PNG sorgente: python tools/make_icons.py percorso/icona.png  (richiede Pillow)
Senza argomento crea un'icona segnaposto (quadrato blu con 'H')."""
import os, sys
from PIL import Image, ImageDraw, ImageFont
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
os.makedirs(OUT, exist_ok=True)
if len(sys.argv) > 1: src = Image.open(sys.argv[1]).convert("RGBA")
else:
    src = Image.new("RGBA", (1024, 1024), (27, 35, 64, 255)); d = ImageDraw.Draw(src)
    d.ellipse((152, 152, 872, 872), fill=(245, 150, 30, 255)); d.arc((152, 152, 872, 872), 0, 360, fill=(30, 20, 10, 255), width=22)
    d.line((512, 152, 512, 872), fill=(30, 20, 10, 255), width=22); d.line((152, 512, 872, 512), fill=(30, 20, 10, 255), width=22)
w, h = src.size; side = min(w, h); src = src.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))   # quadrata al centro
src.save(os.path.join(OUT, "hooply-original.png"), optimize=True)
for name, px in (("favicon-32.png", 32), ("favicon-64.png", 64), ("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512), ("logo-48.png", 96)):
    src.resize((px, px), Image.LANCZOS).save(os.path.join(OUT, name), optimize=True)
src.resize((64, 64), Image.LANCZOS).save(os.path.join(OUT, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
print("icone create in", os.path.abspath(OUT))
