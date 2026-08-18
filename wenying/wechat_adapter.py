from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment, Tag


@dataclass(frozen=True)
class AdaptedHtml:
    html: str
    report: tuple[str, ...]


TARGETS = ("自由网页 HTML", "135 编辑器代码", "秀米兼容代码", "微信公众号正文")


def _clean_style(style: str, strict: bool) -> tuple[str, int]:
    removed = 0
    forbidden = {
        "position", "left", "right", "top", "bottom", "z-index",
        "animation", "animation-name", "animation-duration", "transition",
        "transform", "writing-mode", "text-orientation",
    }
    if strict:
        forbidden.update({"float", "overflow", "clip-path", "filter"})
    kept: list[str] = []
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        name, value = declaration.split(":", 1)
        name, value = name.strip().lower(), value.strip()
        if (
            name in forbidden or "javascript:" in value.lower()
            or "expression(" in value.lower() or name.startswith("--")
        ):
            removed += 1
            continue
        kept.append(f"{name}:{value}")
    return ";".join(kept), removed


def adapt_html(source: str, target: str) -> AdaptedHtml:
    """Convert a browser document to an editor-friendly article fragment."""
    if target == TARGETS[0]:
        return AdaptedHtml(source, ("保留完整网页结构和视觉效果。",))

    soup = BeautifulSoup(source, "html.parser")
    report: list[str] = []
    removable = soup.find_all(["script", "iframe", "form", "input", "button", "noscript"])
    removed_scripts = len(removable)
    for node in removable:
        node.decompose()
    if removed_scripts:
        report.append(f"已移除 {removed_scripts} 个脚本或交互控件")
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    root = soup.find("article") or soup.find(id="js_content") or soup.body or soup
    strict = target == TARGETS[3]
    browser_decorations = root.select(".wy-web-hero, .wy-web-ending")
    for node in browser_decorations:
        node.decompose()
    if browser_decorations:
        report.append(f"已将 {len(browser_decorations)} 个浏览器动态装饰安全降级")
    removed_css = 0
    removed_attrs = 0
    for node in root.find_all(True):
        for attr in list(node.attrs):
            if attr.lower().startswith("on") or attr.lower() in {
                "class", "id", "contenteditable", "draggable", "tabindex",
                "data-wenying-text-slot", "data-wenying-image-slot",
            }:
                del node.attrs[attr]
                removed_attrs += 1
        style, count = _clean_style(str(node.get("style", "")), strict)
        removed_css += count
        if style:
            node["style"] = style
        else:
            node.attrs.pop("style", None)
        if node.name == "img":
            node["style"] = (
                str(node.get("style", "")).rstrip(";")
                + ";display:block;width:100%;max-width:100%;height:auto;margin-left:auto;margin-right:auto"
            ).lstrip(";")
            node.attrs.pop("srcset", None)
            node.attrs.pop("loading", None)
        if node.name in {"article", "main"}:
            node.name = "section"

    if isinstance(root, Tag):
        root_style, count = _clean_style(str(root.get("style", "")), strict)
        removed_css += count
        root_style = re.sub(r"(?:^|;)max-width:[^;]*", "", root_style, flags=re.I)
        root_style = re.sub(r"(?:^|;)margin:auto", "", root_style, flags=re.I)
        root["style"] = root_style.strip(";")
        root.name = "section"

    if removed_css:
        report.append(f"已清理 {removed_css} 项不兼容 CSS")
    if removed_attrs:
        report.append(f"已清理 {removed_attrs} 个网页专用属性")
    report.append("已转换为可粘贴的正文片段（行内样式）")
    if target == TARGETS[1]:
        report.append("建议通过 135 插件的“导入文章代码”导入")
    elif target == TARGETS[2]:
        report.append("秀米若无 HTML 导入入口，可先导入 135 再复制")
    else:
        report.append("已使用最严格的微信公众号兼容规则")
    return AdaptedHtml(str(root), tuple(report))
