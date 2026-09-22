#!/usr/bin/env python3
"""Generates index.html from narayan-kwach.json (the structured content model)."""
import json
import html
import os

BASE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE, "narayan-kwach.json"), encoding="utf-8") as f:
    doc = json.load(f)


def esc(s):
    return html.escape(s, quote=False)


def render_blocks(blocks):
    out = []
    open_unit = False

    def close_unit():
        nonlocal open_unit
        if open_unit:
            out.append("  </div>")
            open_unit = False

    for b in blocks:
        t = b["type"]
        if t == "heading":
            close_unit()
            out.append(f'  <h2 class="heading">{esc(b["text"])}</h2>')
        elif t == "para":
            close_unit()
            out.append(f'  <p class="para">{esc(b["text"])}</p>')
        elif t == "verse":
            if not open_unit:
                out.append('  <div class="unit">')
                open_unit = True
            color_class = "verse-red" if b.get("color") == "red" else "verse-black"
            out.append(f'    <p class="verse {color_class}">{esc(b["text"])}</p>')
        elif t == "commentary":
            if not open_unit:
                out.append('  <div class="unit">')
                open_unit = True
            if b.get("accent"):
                out.append(
                    '    <p class="commentary"><span class="accent">'
                    f'{esc(b["accent"])}</span> {esc(b["text"])}</p>'
                )
            else:
                out.append(f'    <p class="commentary">{esc(b["text"])}</p>')
            close_unit()
        elif t == "divider":
            close_unit()
            out.append('  <hr class="divider">')
        elif t == "citation":
            close_unit()
            out.append(f'  <p class="citation">{esc(b["text"])}</p>')
    close_unit()
    return "\n".join(out)


body_html = render_blocks(doc["blocks"])
cover_title_html = "\n".join(
    f'      <p class="cover-line">{esc(line)}</p>' for line in doc["cover"]["titleLines"]
)

html_out = f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(doc['title'])}</title>
<meta name="description" content="Shri Narayan Kavach (Srimad Bhagavatam, Skandha 6, Adhyaya 8) with Hindi commentary, recompiled for Android by Vedpuran.net.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;700;900&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink: #1a1a1a;
    --verse-red: #b3261e;
    --paper: #ffffff;
    --paper-alt: #faf8f3;
    --rule: #d9cdb0;
    --accent-gold: #b8860b;
    --max-w: 640px;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --ink: #ece6d8;
      --verse-red: #ff8a80;
      --paper: #17140f;
      --paper-alt: #1f1b14;
      --rule: #4a4030;
      --accent-gold: #d9a441;
    }}
  }}
  :root[data-theme="dark"] {{
    --ink: #ece6d8;
    --verse-red: #ff8a80;
    --paper: #17140f;
    --paper-alt: #1f1b14;
    --rule: #4a4030;
    --accent-gold: #d9a441;
  }}

  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    background: var(--paper-alt);
    color: var(--ink);
    font-family: "Noto Sans Devanagari", "Noto Sans", sans-serif;
    -webkit-font-smoothing: antialiased;
  }}

  main {{
    max-width: var(--max-w);
    margin: 0 auto;
    background: var(--paper);
    padding: 0 20px 56px;
    min-height: 100vh;
  }}

  .cover {{
    padding-top: 18px;
    text-align: center;
  }}
  .cover-image-wrap {{
    width: 97%;
    margin: 0 auto;
    line-height: 0;
  }}
  .cover-image-wrap img {{
    width: 100%;
    height: auto;
    display: block;
    border-radius: 2px;
  }}
  .cover-title {{
    padding: 28px 6px 8px;
  }}
  .cover-line {{
    font-weight: 900;
    font-size: 1.45rem;
    margin: 0 0 22px;
    letter-spacing: 0.01em;
  }}
  .cover-line:last-child {{ margin-bottom: 0; }}

  h2.heading {{
    font-weight: 700;
    font-size: 1.15rem;
    text-align: center;
    color: var(--accent-gold);
    margin: 34px 0 14px;
    letter-spacing: 0.02em;
  }}
  main > h2.heading:first-of-type {{ margin-top: 30px; }}

  p.para {{
    font-weight: 700;
    text-align: center;
    line-height: 1.9;
    margin: 18px 0;
    font-size: 1.02rem;
  }}

  .unit {{
    margin: 22px 0;
  }}

  p.verse {{
    font-weight: 700;
    text-align: center;
    line-height: 1.85;
    margin: 0 0 10px;
    font-size: 1.02rem;
    padding: 2px 10px 2px 14px;
    border-left: 3px solid var(--rule);
  }}
  p.verse.verse-red {{
    color: var(--verse-red);
    border-left-color: var(--verse-red);
  }}
  p.verse.verse-black {{
    color: var(--ink);
  }}

  p.commentary {{
    font-weight: 700;
    text-align: center;
    line-height: 1.9;
    margin: 10px 0 0;
    font-size: 1.02rem;
    color: var(--ink);
  }}
  .accent {{
    color: var(--verse-red);
  }}

  hr.divider {{
    border: none;
    border-top: 2px solid var(--accent-gold);
    width: 60%;
    margin: 40px auto;
    opacity: 0.6;
  }}

  p.citation {{
    text-align: center;
    font-weight: 700;
    font-style: italic;
    color: var(--ink);
    opacity: 0.75;
    margin: 8px 0 0;
    font-size: 0.95rem;
  }}

  footer.source-note {{
    max-width: var(--max-w);
    margin: 0 auto;
    padding: 18px 20px 40px;
    text-align: center;
    font-size: 0.78rem;
    color: var(--ink);
    opacity: 0.55;
    font-family: system-ui, sans-serif;
    font-weight: 400;
    line-height: 1.6;
  }}

  @media (max-width: 420px) {{
    .cover-line {{ font-size: 1.25rem; }}
    p.verse, p.commentary, p.para {{ font-size: 0.98rem; }}
  }}
</style>
</head>
<body>
<main>
  <div class="cover">
    <div class="cover-image-wrap">
      <img src="{esc(doc['cover']['image'])}" alt="Bhagavan Narayan and Lakshmi seated on Sheshnag" width="400" height="335">
    </div>
    <div class="cover-title">
{cover_title_html}
    </div>
  </div>

{body_html}
</main>
<footer class="source-note">
  Transcribed from <em>narayan-kwach.pdf</em> (recompiled for Android by Vedpuran.net) via vision-OCR, since the source PDF's embedded text layer uses a non-Unicode custom Devanagari font encoding. Sanskrit verses 12&ndash;34 (the core protective mantras) are shown in red as in the source; the narrative frame and all Hindi commentary are shown in black.
</footer>
</body>
</html>
"""

out_path = os.path.join(BASE, "index.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html_out)
print("wrote", out_path, len(html_out), "bytes")
