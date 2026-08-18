from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .models import DocumentContent


def render_html(document: DocumentContent, template: dict[str, Any]) -> str:
    token = template.get("styleTokens", {})
    primary = token.get("primaryColor", "#24463f")
    accent = token.get("accentColor", "#a44b38")
    text = token.get("textColor", "#292b29")
    muted = token.get("mutedColor", "#77746d")
    paper = token.get("paperColor", "#f7f3e9")
    size = int(token.get("fontSize", 16))
    line = float(token.get("lineHeight", 1.9))
    spacing = int(token.get("paragraphSpacing", 18))
    parts = [f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#e9e6df;padding:32px 12px;"><section style="box-sizing:border-box;max-width:677px;margin:auto;padding:42px 28px 56px;background:{paper};color:{text};font-family:'Microsoft YaHei','PingFang SC',sans-serif;box-shadow:0 12px 40px rgba(32,38,34,.10);">
<section style="text-align:center;margin:0 0 42px;"><span style="display:inline-block;width:32px;border-top:2px solid {accent};margin-bottom:14px;"></span><h1 style="margin:0;font-family:'STSong','SimSun',serif;font-size:30px;line-height:1.45;letter-spacing:3px;color:{primary};">{html.escape(document.title)}</h1><p style="margin:12px 0 0;font-size:11px;letter-spacing:6px;color:{muted};">文 · 映</p></section>''']
    heading_index = 0
    for block in document.blocks:
        if block.type == "heading":
            heading_index += 1
            parts.append(f'<section style="margin:38px 0 20px;"><span style="font-size:12px;color:{accent};letter-spacing:2px;">{heading_index:02d}</span><h2 style="display:inline;margin:0 0 0 10px;font-family:\'STSong\',\'SimSun\',serif;font-size:{22 if block.level <= 1 else 19}px;letter-spacing:1px;color:{primary};">{html.escape(block.text)}</h2><div style="width:100%;margin-top:10px;border-bottom:1px solid {primary}22;"></div></section>')
        elif block.type == "paragraph":
            parts.append(f'<p style="margin:0 0 {spacing}px;font-size:{size}px;line-height:{line};letter-spacing:.5px;text-align:justify;">{html.escape(block.text)}</p>')
        elif block.type == "quote":
            parts.append(f'<section style="margin:24px 0;padding:16px 18px;border-left:3px solid {primary};background:{primary}0d;font-size:{size}px;line-height:{line};">{html.escape(block.text)}</section>')
        elif block.type == "image" and block.image_id in document.images:
            uri = Path(document.images[block.image_id]).resolve().as_uri()
            parts.append(f'<section style="margin:26px 0;text-align:center;"><img src="{uri}" style="display:block;width:100%;height:auto;border-radius:4px;" /></section>')
        elif block.type == "table":
            rows = []
            for row in block.rows:
                cells = ''.join(f'<td style="border:1px solid {primary}33;padding:8px;">{html.escape(cell)}</td>' for cell in row)
                rows.append(f'<tr>{cells}</tr>')
            parts.append(f'<table style="width:100%;border-collapse:collapse;margin:24px 0;font-size:14px;line-height:1.6;">{"".join(rows)}</table>')
    parts.append(f'<section style="text-align:center;margin-top:48px;color:{muted};font-size:12px;letter-spacing:3px;"><span style="display:inline-block;width:22px;border-top:1px solid {accent};vertical-align:middle;margin-right:10px;"></span>余韵未尽<span style="display:inline-block;width:22px;border-top:1px solid {accent};vertical-align:middle;margin-left:10px;"></span></section></section></body></html>')
    return "".join(parts)
