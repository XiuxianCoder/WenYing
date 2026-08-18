from __future__ import annotations

from copy import copy
from typing import Any

from bs4 import BeautifulSoup, Tag


def _meaningful_paragraphs(root: Tag) -> list[Tag]:
    result = []
    for node in root.find_all(["p", "div", "section"]):
        text = node.get_text(" ", strip=True)
        # Prefer leaf-like text containers so a large wrapper is never selected.
        child_text_blocks = node.find_all(["p", "div", "section"], recursive=False)
        if len(text) >= 25 and not any(len(child.get_text(" ", strip=True)) >= 20 for child in child_text_blocks):
            result.append(node)
    return result


def _ancestors(node: Tag) -> list[Tag]:
    values: list[Tag] = []
    current: Any = node
    while isinstance(current, Tag):
        values.append(current)
        current = current.parent
    return values


def build_exact_skeleton(captured_html: str) -> dict[str, Any]:
    """Turn captured WeChat HTML into prefix + body slot + exact suffix."""
    soup = BeautifulSoup(captured_html, "html.parser")
    root = soup.find(id="js_content") or soup.find("article") or soup.find("body") or soup
    paragraphs = _meaningful_paragraphs(root)
    if not paragraphs:
        return {}
    first = paragraphs[0]
    ending = None
    for node in root.find_all(["p", "div", "section"]):
        text = node.get_text(" ", strip=True)
        if ("供稿" in text and ("校对" in text or len(text) < 120)) or "排版/审核" in text or "排版／审核" in text:
            # Choose the smallest element containing the credit line.
            if not any(("供稿" in child.get_text(" ", strip=True) or "排版/审核" in child.get_text(" ", strip=True)) for child in node.find_all(["p", "div", "section"], recursive=False)):
                ending = node
                break
    if ending is None:
        ending = paragraphs[-1]

    ending_ancestors = set(_ancestors(ending))
    common = next((node for node in _ancestors(first) if node in ending_ancestors), None)
    if common is None:
        return {}

    def branch_under(node: Tag, ancestor: Tag) -> Tag:
        current = node
        while isinstance(current.parent, Tag) and current.parent is not ancestor:
            current = current.parent
        return current

    start_branch = branch_under(first, common)
    end_branch = branch_under(ending, common)
    children = [child for child in common.children if isinstance(child, Tag)]
    if start_branch not in children or end_branch not in children:
        return {}
    start_index, end_index = children.index(start_branch), children.index(end_branch)
    if end_index < start_index:
        return {}

    slot = soup.new_tag("section")
    slot["data-wenying-body-slot"] = "true"
    slot["style"] = "box-sizing:border-box;width:100%;"
    start_branch.insert_before(slot)
    removed = 0
    # Keep the credit branch and everything following it exactly as captured.
    for child in children[start_index:end_index]:
        child.decompose()
        removed += 1
    return {
        "html": str(root),
        "firstText": first.get_text(" ", strip=True)[:300],
        "endingText": ending.get_text(" ", strip=True)[:300],
        "removedBranches": removed,
    }


def apply_asset_replacements(value: str, replacements: dict[str, str]) -> str:
    result = value
    for source, embedded in replacements.items():
        result = result.replace(source, embedded).replace(source.replace("&", "&amp;"), embedded)
    return result
