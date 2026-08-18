from __future__ import annotations

import hashlib

import base64
import html
import mimetypes
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from .models import DocumentContent
from .creative_web import enhance_ai_original


def _number(value: Any, default: float, percent_base: float | None = None) -> float:
    """Accept model values such as 15, 15px, 1.8 and 180%."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().lower()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return default
    number = float(match.group())
    if "%" in text:
        return number / 100.0 if percent_base is None else percent_base * number / 100.0
    return number


def _image_uri(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


def _image_digest(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _component(source: str, **values: str) -> str:
    result = source
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", value)
    if "{{LABEL}}" in result:
        result = result.replace("{{LABEL}}", values.get("TEXT", values.get("TITLE", "")))
    return result


def _resolve_style_placeholders(components: dict[str, Any], tokens: dict[str, Any]) -> dict[str, str]:
    """Resolve model-invented CSS placeholders to safe inline CSS."""
    primary = str(tokens.get("primaryColor", "#333333"))
    text = str(tokens.get("textColor", "#333333"))
    muted = str(tokens.get("mutedColor", "#888888"))
    size = max(13, min(20, int(_number(tokens.get("fontSize", 16), 16))))
    line = max(1.4, min(2.2, _number(tokens.get("lineHeight", 1.8), 1.8)))
    gap = max(8, min(32, int(_number(tokens.get("paragraphSpacing", 18), 18))))
    radius = max(0, min(24, int(_number(tokens.get("imageRadius", 0), 0))))
    replacements = {
        "{{TITLE_STYLE}}": f"margin:28px 0 24px;color:{primary};font-size:28px;line-height:1.4;text-align:center;font-weight:700",
        "{{HEADING_STYLE}}": f"margin:30px 0 16px;color:{primary};font-size:21px;line-height:1.5;font-weight:700",
        "{{PARAGRAPH_STYLE}}": f"margin:0 0 {gap}px;color:{text};font-size:{size}px;line-height:{line};text-align:justify",
        "{{MUTED_STYLE}}": f"color:{muted};font-size:13px;line-height:1.7",
        "{{IMAGE_MARGIN}}": "margin:24px 0;text-align:center",
        "{{IMAGE_RADIUS}}": f"{radius}px",
    }
    result: dict[str, str] = {}
    for key, raw in components.items():
        value = str(raw or "")
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        value = re.sub(r"\{\{[A-Z_]+_STYLE\}\}", "", value)
        value = re.sub(r"writing-mode\s*:\s*(?:vertical|sideways)[^;\"']*;?", "", value, flags=re.I)
        value = re.sub(r"text-orientation\s*:[^;\"']*;?", "", value, flags=re.I)
        result[str(key)] = value
    return result

def _styled_content(source: str, value: str, markers: tuple[str, ...] = ("{{TEXT}}", "{{TITLE}}", "{{LABEL}}"), fallback_tag: str = "p") -> str:
    """Keep only the styled ancestor path around a placeholder; drop copied source text."""
    soup = BeautifulSoup(source or "", "html.parser")
    target = None
    for text_node in soup.find_all(string=True):
        if any(marker in str(text_node) for marker in markers):
            target = text_node
            break
    if target is None or not isinstance(target.parent, Tag):
        return f"<{fallback_tag}>{html.escape(value)}</{fallback_tag}>"
    path: list[Tag] = []
    current: Any = target.parent
    while isinstance(current, Tag) and current.name not in {"[document]", "html", "body"}:
        path.append(current)
        current = current.parent
    built: Any = NavigableString(value)
    maker = BeautifulSoup("", "html.parser")
    for original in path:
        wrapper = maker.new_tag(original.name, attrs=dict(original.attrs))
        wrapper.append(built)
        built = wrapper
    return str(built)

def _section_name(value: str) -> str:
    return re.sub(r"[\s【】\[\]]", "", value)

def _replace_slot_text(node: Tag, value: str) -> None:
    meaningful = [item for item in node.descendants if isinstance(item, NavigableString) and str(item).strip()]
    if meaningful:
        meaningful[0].replace_with(value)
        for item in meaningful[1:]:
            item.replace_with("")
    else:
        node.append(value)


def _render_dom_skeleton(document: DocumentContent, template: dict[str, Any], title: str,
                         width: int, paper: str, text_color: str) -> str | None:
    exact = template.get("exactFragments", {})
    skeleton = exact.get("skeletonHtml", "") if isinstance(exact, dict) else ""
    slots = exact.get("contentSlots", []) if isinstance(exact, dict) else []
    if not skeleton or not slots:
        return None
    soup = BeautifulSoup(str(skeleton), "html.parser")
    text_blocks = [(index, block) for index, block in enumerate(document.blocks)
                   if block.type in {"heading", "paragraph", "quote"} and block.text.strip() and block.text.strip() != title]
    plan_items = template.get("documentPlan", {}).get("assignments", [])
    mapping: dict[int, int] = {}
    used_slots: set[int] = set()
    valid_blocks = {index for index, _ in text_blocks}
    for item in plan_items if isinstance(plan_items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            block_index, slot_index = int(item.get("blockIndex")), int(item.get("slotIndex"))
        except (TypeError, ValueError):
            continue
        if block_index in valid_blocks and 0 <= slot_index < len(slots) and slot_index not in used_slots:
            mapping[block_index] = slot_index
            used_slots.add(slot_index)
    # Exact/same-name anchors always beat a probabilistic model decision.
    for block_index, block in text_blocks:
        block_name = _section_name(block.text)
        if len(block_name) > 16:
            continue
        match = next((int(slot["slotIndex"]) for slot in slots
                      if _section_name(str(slot.get("sourceText", ""))) == block_name), None)
        if match is not None:
            previous = next((key for key, value in mapping.items() if value == match), None)
            if previous is not None:
                mapping.pop(previous, None)
            mapping[block_index] = match
            used_slots.add(match)
    remaining_slots = [int(slot["slotIndex"]) for slot in slots if int(slot["slotIndex"]) not in used_slots]
    for block_index, _block in text_blocks:
        if block_index not in mapping and remaining_slots:
            mapping[block_index] = remaining_slots.pop(0)
    reverse = {slot_index: block_index for block_index, slot_index in mapping.items()}
    block_lookup = dict(text_blocks)
    for slot in slots:
        slot_index = int(slot["slotIndex"])
        node = soup.find(attrs={"data-wenying-text-slot": str(slot.get("slotId"))})
        if not isinstance(node, Tag):
            continue
        if slot_index in reverse:
            _replace_slot_text(node, block_lookup[reverse[slot_index]].text)
        else:
            _replace_slot_text(node, "")
            node["style"] = str(node.get("style", "")) + ";display:none!important"
    image_paths: list[str] = []
    seen_digests: set[str] = set()
    for block in document.blocks:
        if block.type != "image" or block.image_id not in document.images:
            continue
        path = document.images[block.image_id]
        digest = _image_digest(path)
        if digest not in seen_digests:
            image_paths.append(path)
            seen_digests.add(digest)
    for image_index, slot_id in enumerate(exact.get("imageSlots", [])):
        image = soup.find("img", attrs={"data-wenying-image-slot": str(slot_id)})
        if not isinstance(image, Tag):
            continue
        if image_index < len(image_paths):
            image["src"] = _image_uri(image_paths[image_index])
            image.attrs.pop("data-src", None)
            image.attrs.pop("data-backsrc", None)
        else:
            image["style"] = str(image.get("style", "")) + ";display:none!important"
            image.attrs.pop("src", None)
            image.attrs.pop("data-src", None)
            image.attrs.pop("data-backsrc", None)
    mapped_blocks = set(mapping)
    extras = [block for index, block in text_blocks if index not in mapped_blocks]
    if extras:
        root = soup.find(id="js_content") or soup.find("article") or soup.find("body") or soup
        credit_text = next((node for node in root.find_all(string=True) if "供稿" in str(node)), None)
        anchor = credit_text.parent if credit_text is not None and isinstance(credit_text.parent, Tag) else None
        while isinstance(anchor, Tag) and anchor.parent is not root:
            anchor = anchor.parent
        for block in extras:
            fragment = BeautifulSoup(f'<p style="margin:0 0 16px;line-height:1.9;text-align:justify">{html.escape(block.text)}</p>', "html.parser").find()
            if isinstance(anchor, Tag):
                anchor.insert_before(fragment)
            else:
                root.append(fragment)
    code_blocks = [block for block in document.blocks if block.type == "code" and block.text.strip()]
    if code_blocks:
        root = soup.find(id="js_content") or soup.find("article") or soup.find("body") or soup
        for block in code_blocks:
            root.append(BeautifulSoup(_code_block_html(block.text), "html.parser"))
    title_source = template.get("components", {}).get("titleHtml", "")
    title_html = _styled_content(title_source, title, fallback_tag="h1") if title_source else f'<h1 style="margin:28px 10px 22px;font-size:28px;line-height:1.45;text-align:center;font-weight:700">{html.escape(title)}</h1>'
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title></head><body style="margin:0;background:#eeeeee;padding:24px 10px"><article style="box-sizing:border-box;max-width:{width}px;margin:auto;padding:0 20px 42px;background:{paper};color:{text_color};font-family:'Microsoft YaHei','PingFang SC',sans-serif">{title_html}{str(soup)}</article></body></html>'''

def _render_component_value(source: str, value: str, template: dict[str, Any], fallback_tag: str) -> str:
    """AI-original components contain placeholders only, so preserve their full decorative DOM."""
    if template.get("sourceType") == "ai_original" and source:
        escaped = html.escape(value)
        return _component(source, TEXT=escaped, TITLE=escaped, LABEL=escaped, NUMBER="")
    return _styled_content(source, value, fallback_tag=fallback_tag)

_NUMBERED_ITEM = re.compile(r"^\s*((?:[一二三四五六七八九十百]+|\d+)[、.．])\s*(.*)$", re.S)
_BRACKET_HEADING = re.compile(r"^\s*[【\[].{1,28}[】\]]\s*$")


def _semantic_roles(document: DocumentContent, assigned: dict[int, str]) -> dict[int, str]:
    """Repair batch-boundary inconsistencies with deterministic document semantics."""
    roles = dict(assigned)
    numbered_indices: list[int] = []
    for index, block in enumerate(document.blocks):
        value = block.text.strip()
        if not value:
            continue
        if block.type == "heading" or _BRACKET_HEADING.match(value):
            roles[index] = "heading"
        if block.type in {"paragraph", "quote"} and _NUMBERED_ITEM.match(value):
            numbered_indices.append(index)
    # A numbered series is one visual system, even when model batching split it.
    for index in numbered_indices:
        roles[index] = "numbered_item"
    for index, role in list(roles.items()):
        if role == "info_card":
            roles[index] = "info_row"
    return roles


def _numbered_item_html(value: str, primary: str, accent: str, order: int) -> str:
    match = _NUMBERED_ITEM.match(value.strip())
    marker, content = (match.group(1), match.group(2)) if match else (str(order), value)
    tint = "#fff8f2" if order % 2 else "#f6f8fb"
    return (
        f'<section style="display:flex;align-items:flex-start;gap:14px;margin:10px 0;padding:17px 18px;'
        f'background:linear-gradient(135deg,{tint} 0%,#ffffff 100%);border:1px solid {accent}38;'
        f'border-left:4px solid {accent};border-radius:12px;box-shadow:0 4px 14px rgba(35,45,55,.055)">'
        f'<span style="display:inline-flex;align-items:center;justify-content:center;min-width:34px;height:34px;'
        f'padding:0 7px;box-sizing:border-box;border-radius:10px;background:linear-gradient(135deg,{primary},{accent});'
        f'color:#fff;font-size:14px;font-weight:700;line-height:1">{html.escape(marker.rstrip("、.．"))}</span>'
        f'<p style="flex:1;margin:2px 0 0;color:#2d2d2d;font-size:16px;line-height:1.85;text-align:justify">'
        f'{html.escape(content)}</p></section>'
    )


def _info_row_html(value: str, primary: str, accent: str) -> str:
    parts = re.split(r"([：:])", value, maxsplit=1)
    if len(parts) >= 3:
        label, content = parts[0] + parts[1], parts[2]
    else:
        label, content = "信息", value
    return (
        f'<section style="display:flex;align-items:flex-start;gap:12px;margin:8px 0;padding:14px 16px;'
        f'background:#fff;border:1px solid {primary}20;border-radius:11px;box-shadow:0 3px 12px rgba(35,45,55,.045)">'
        f'<strong style="min-width:92px;color:{primary};font-size:15px;line-height:1.8">{html.escape(label)}</strong>'
        f'<span style="flex:1;color:#41464b;font-size:15px;line-height:1.8">{html.escape(content)}</span>'
        f'<i style="width:6px;height:6px;margin-top:11px;border-radius:50%;background:{accent}"></i></section>'
    )


def _code_block_html(value: str) -> str:
    return (
        '<section style="margin:22px 0;border:1px solid #283548;border-radius:10px;overflow:hidden;'
        'background:#0f172a;box-shadow:0 5px 18px rgba(15,23,42,.14)">'
        '<p style="margin:0;padding:8px 14px;border-bottom:1px solid #334155;color:#94a3b8;'
        'font-size:12px;line-height:1.5;letter-spacing:.08em">CODE</p>'
        '<pre style="box-sizing:border-box;margin:0;padding:16px;white-space:pre-wrap;word-break:break-word;'
        'overflow-x:auto;color:#e2e8f0;background:#0f172a;font-size:14px;line-height:1.7;'
        'font-family:Consolas,Menlo,Monaco,monospace"><code>'
        f'{html.escape(value)}</code></pre></section>'
    )

def render_html(document: DocumentContent, template: dict[str, Any]) -> str:
    title = document.title.strip()
    if not title or title == "未命名文章":
        title = next((block.text.strip() for block in document.blocks if block.type == "heading" and block.text.strip()), "未命名文章")
    tokens = template.get("styleTokens", {})
    components = _resolve_style_placeholders(template.get("components", {}), tokens)
    primary = tokens.get("primaryColor", "#333333")
    accent = tokens.get("accentColor", primary)
    text = tokens.get("textColor", "#333333")
    paper = tokens.get("paperColor", "#ffffff")
    muted = tokens.get("mutedColor", "#888888")
    size = max(13, min(20, int(_number(tokens.get("fontSize", 16), 16))))
    line = max(1.4, min(2.2, _number(tokens.get("lineHeight", 1.8), 1.8)))
    gap = max(8, min(32, int(_number(tokens.get("paragraphSpacing", 18), 18))))
    width_value = str(tokens.get("contentWidth", 677)).strip()
    width = 677 if "%" in width_value else int(_number(width_value, 677))
    width = max(320, min(900, width))
    radius = max(0, min(24, int(_number(tokens.get("imageRadius", 0), 0))))
    exact = template.get("exactFragments", {})
    skeleton_result = _render_dom_skeleton(document, template, title, width, paper, text)
    if skeleton_result is not None:
        return skeleton_result
    body: list[str] = []
    lead_index = next((index for index, block in enumerate(document.blocks) if block.type == "paragraph" and block.text.strip() and block.text.strip() != title), None)
    if isinstance(exact, dict) and exact.get("prefixHtml"):
        title_source = components.get("titleHtml", "")
        body.append(_styled_content(title_source, title, fallback_tag="h1") if title_source else f'<h1 style="margin:28px 10px 22px;font-size:28px;line-height:1.45;color:{primary};text-align:center;font-weight:700">{html.escape(title)}</h1>')
        body.append(str(exact["prefixHtml"]))
    else:
        body.extend([components.get("headerHtml", ""), components.get("coverHtml", "")])
        title_html = components.get("titleHtml", "")
        if title_html:
            body.append(_component(title_html, TITLE=html.escape(title)))
        else:
            body.append(f'<h1 style="margin:0 0 36px;font-size:30px;line-height:1.45;color:{primary};text-align:center">{html.escape(title)}</h1>')
    if components.get("leadHtml") and lead_index is not None:
        lead_source = exact.get("leadHtml", "") if isinstance(exact, dict) else ""
        body.append(_render_component_value(lead_source or components["leadHtml"], document.blocks[lead_index].text, template, "p"))

    plan = template.get("documentPlan", {})
    assignments = {int(item.get("blockIndex")): str(item.get("role", "")) for item in plan.get("assignments", []) if isinstance(item, dict) and str(item.get("blockIndex", "")).isdigit()}
    assignments = _semantic_roles(document, assignments)
    style_slots = exact.get("styleSlots", {}) if isinstance(exact, dict) else {}
    named_sections = exact.get("namedSections", {}) if isinstance(exact, dict) else {}
    named_starts: dict[int, tuple[str, int]] = {}
    named_skip: set[int] = set()
    for start, block in enumerate(document.blocks):
        matched = next((name for name in named_sections if _section_name(block.text) == _section_name(name)), None)
        if not matched:
            continue
        end = start + 1
        while end < len(document.blocks):
            following = document.blocks[end]
            if following.type == "heading" or any(_section_name(following.text) == _section_name(name) for name in named_sections):
                break
            end += 1
        named_starts[start] = (matched, end)
        named_skip.update(range(start + 1, end))
    heading_number = 0
    rendered_images: set[str] = set()
    rendered_image_digests: set[str] = set()
    for block_index, block in enumerate(document.blocks):
        if block_index in named_skip:
            continue
        if block_index in named_starts:
            section_name, section_end = named_starts[block_index]
            paragraphs = []
            for child in document.blocks[block_index + 1:section_end]:
                if child.type in {"paragraph", "quote"} and child.text.strip():
                    paragraphs.append(f'<p style="margin:0 0 12px;line-height:1.9;text-align:justify">{html.escape(child.text)}</p>')
                elif child.type == "code" and child.text.strip():
                    paragraphs.append(_code_block_html(child.text))
                elif child.type == "image" and child.image_id in document.images:
                    paragraphs.append(f'<img src="{_image_uri(document.images[child.image_id])}" style="display:block;width:100%;height:auto;margin:16px 0">')
                    rendered_images.add(child.image_id)
            skeleton = str(named_sections[section_name]).replace("{{TITLE}}", html.escape(block.text)).replace("{{CONTENT}}", "".join(paragraphs))
            body.append(skeleton)
            continue
        if block_index == lead_index and components.get("leadHtml"):
            continue
        if block.text.strip() == title:
            continue
        if block.type == "heading":
            heading_number += 1
            source = style_slots.get("heading", "") or components.get("headingHtml", "")
            if source:
                body.append(_render_component_value(source, block.text, template, "h2"))
            else:
                body.append(f'<h2 style="margin:34px 0 18px;font-size:{22 if block.level <= 1 else 19}px;line-height:1.5;color:{primary}">{html.escape(block.text)}</h2>')
        elif block.type == "paragraph":
            role = assignments.get(block_index, "paragraph")
            if role == "heading":
                heading_number += 1
                source = style_slots.get("heading", "") or components.get("headingHtml", "")
                body.append(_render_component_value(source, block.text, template, "h2") if source else f'<h2 style="margin:34px 0 18px;font-size:21px;line-height:1.5;color:{primary}">{html.escape(block.text)}</h2>')
            elif role == "numbered_item":
                body.append(_numbered_item_html(block.text, primary, accent, block_index))
            elif role == "info_row":
                body.append(_info_row_html(block.text, primary, accent))
            else:
                role_keys = {"lead": "leadHtml", "emphasis": "quoteHtml", "quote": "quoteHtml", "notice": "noticeHtml", "card": "infoCardHtml"}
                source = style_slots.get(role, "") or components.get(role_keys.get(role, "paragraphHtml"), "")
                source = source or style_slots.get("paragraph", "") or components.get("paragraphHtml", "")
                body.append(_render_component_value(source, block.text, template, "p") if source else f'<p style="margin:0 0 {gap}px;font-size:{size}px;line-height:{line};color:{text};text-align:justify">{html.escape(block.text)}</p>')
        elif block.type == "quote":
            source = components.get("quoteHtml", "")
            body.append(_render_component_value(source, block.text, template, "section") if source else f'<section style="margin:24px 0;padding:16px;border-left:3px solid {accent};background:{accent}12;line-height:{line}">{html.escape(block.text)}</section>')
        elif block.type == "code":
            body.append(_code_block_html(block.text))
        elif block.type == "image" and block.image_id in document.images:
            rendered_images.add(block.image_id)
            image_path = document.images[block.image_id]
            digest = _image_digest(image_path)
            if digest in rendered_image_digests:
                continue
            rendered_image_digests.add(digest)
            src, caption = _image_uri(image_path), html.escape(block.text)
            source = components.get("imageHtml", "")
            body.append(_component(source, IMAGE_SRC=src, CAPTION=caption) if source else f'<section style="margin:26px 0;text-align:center"><img src="{src}" style="display:block;width:100%;height:auto;border-radius:{radius}px"><p style="margin:8px 0;color:{muted};font-size:12px">{caption}</p></section>')
        elif block.type == "table":
            rows = ''.join('<tr>'+''.join(f'<td style="border:1px solid #ddd;padding:8px">{html.escape(cell)}</td>' for cell in row)+'</tr>' for row in block.rows)
            body.append(f'<table style="width:100%;border-collapse:collapse;margin:24px 0">{rows}</table>')

    # Hard guarantee: no source image may silently disappear from the output.
    for image_id, path in document.images.items():
        if image_id in rendered_images:
            continue
        digest = _image_digest(path)
        if digest in rendered_image_digests:
            continue
        rendered_image_digests.add(digest)
        src = _image_uri(path)
        source = components.get("imageHtml", "")
        body.append(_component(source, IMAGE_SRC=src, CAPTION="") if source else f'<section style="margin:26px 0"><img src="{src}" style="display:block;width:100%;height:auto;border-radius:{radius}px"></section>')
    if isinstance(exact, dict) and exact.get("suffixHtml"):
        body.append(str(exact["suffixHtml"]))
    else:
        if template.get("sourceType") != "ai_original":
            body.append(components.get("endingHtml", ""))
            body.append(components.get("footerHtml", ""))
    custom_css = template.get("customCss", "")
    rendered_body, enhancement_css = enhance_ai_original("".join(body), title, template, width)
    page_class = "wy-free-page" if template.get("sourceType") == "ai_original" else ""
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{custom_css}\n{enhancement_css}</style></head><body style="margin:0;background:#eeeeee;padding:24px 10px"><article class="{page_class}" style="box-sizing:border-box;max-width:{width}px;margin:auto;padding:0 20px 42px;background:{paper};color:{text};font-family:'Microsoft YaHei','PingFang SC',sans-serif">{rendered_body}</article></body></html>'''







