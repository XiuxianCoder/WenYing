from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path
from typing import Any

from .models import DocumentContent


def _image_uri(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


def render_html(document: DocumentContent, template: dict[str, Any]) -> str:
    t = template.get("styleTokens", {})
    primary, accent = t.get("primaryColor", "#24463f"), t.get("accentColor", "#a44b38")
    text, muted, paper = t.get("textColor", "#292b29"), t.get("mutedColor", "#77746d"), t.get("paperColor", "#f7f3e9")
    size, line, gap = int(t.get("fontSize", 16)), float(t.get("lineHeight", 1.9)), int(t.get("paragraphSpacing", 18))
    width, radius = int(t.get("contentWidth", 677)), int(t.get("imageRadius", 4))
    out = [f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(document.title)}</title></head>
<body style="margin:0;background:#e9e6df;padding:32px 12px"><section style="box-sizing:border-box;max-width:{width}px;margin:auto;padding:42px 28px 56px;background:{paper};color:{text};font-family:'Microsoft YaHei','PingFang SC',sans-serif;box-shadow:0 12px 40px rgba(32,38,34,.10)">
<section style="text-align:center;margin:0 0 42px"><span style="display:inline-block;width:32px;border-top:2px solid {accent};margin-bottom:14px"></span><h1 style="margin:0;font-family:'STSong','SimSun',serif;font-size:30px;line-height:1.45;letter-spacing:3px;color:{primary}">{html.escape(document.title)}</h1></section>''']
    number = 0
    for block in document.blocks:
        if block.type == "heading":
            number += 1
            out.append(f'<section style="margin:38px 0 20px"><span style="font-size:12px;color:{accent};letter-spacing:2px">{number:02d}</span><h2 style="display:inline;margin-left:10px;font-family:\'STSong\',serif;font-size:{22 if block.level <= 1 else 19}px;color:{primary}">{html.escape(block.text)}</h2><div style="margin-top:10px;border-bottom:1px solid {primary}22"></div></section>')
        elif block.type == "paragraph":
            out.append(f'<p style="margin:0 0 {gap}px;font-size:{size}px;line-height:{line};letter-spacing:.5px;text-align:justify">{html.escape(block.text)}</p>')
        elif block.type == "quote":
            out.append(f'<section style="margin:24px 0;padding:16px 18px;border-left:3px solid {primary};background:{primary}0d;font-size:{size}px;line-height:{line}">{html.escape(block.text)}</section>')
        elif block.type == "image" and block.image_id in document.images:
            caption = f'<p style="margin:9px 0 0;color:{muted};font-size:12px">{html.escape(block.text)}</p>' if block.text else ""
            out.append(f'<section style="margin:26px 0;text-align:center"><img src="{_image_uri(document.images[block.image_id])}" style="display:block;width:100%;height:auto;border-radius:{radius}px">{caption}</section>')
        elif block.type == "table":
            rows = ''.join('<tr>'+''.join(f'<td style="border:1px solid {primary}33;padding:8px">{html.escape(c)}</td>' for c in row)+'</tr>' for row in block.rows)
            out.append(f'<table style="width:100%;border-collapse:collapse;margin:24px 0;font-size:14px;line-height:1.6">{rows}</table>')
    out.append('</section></body></html>')
    return ''.join(out)
