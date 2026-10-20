"""Builds assets/icon.ico + assets/icon.png from the user's artwork assets/icon_source.jpg (full square, no crop),
and assets/logo.png (in-game title logo, procedural). Never regenerates the icon from procedural art."""
import os
from PIL import Image
import dv_art
os.makedirs("assets", exist_ok=True)
src = Image.open("assets/icon_source.jpg").convert("RGBA")
if src.size[0] != src.size[1]:          # pad (never crop) to square
    s = max(src.size); bg = Image.new("RGBA", (s, s), (0, 0, 0, 0)); bg.paste(src, ((s - src.size[0]) // 2, (s - src.size[1]) // 2)); src = bg
ic = src.resize((256, 256), Image.LANCZOS)
ic.save("assets/icon.png")
ic.save("assets/icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
Image.fromarray(dv_art.logo(12), "RGBA").save("assets/logo.png")
print("ok")
