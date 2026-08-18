from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag


def _leaf_text_blocks(root: Tag) -> list[Tag]:
    blocks: list[Tag] = []
    for node in root.find_all(["p", "div", "section"]):
        text = node.get_text(" ", strip=True)
        direct = node.find_all(["p", "div", "section"], recursive=False)
        if len(text) >= 25 and not any(len(child.get_text(" ", strip=True)) >= 20 for child in direct):
            blocks.append(node)
    return blocks


def _find_ending(root: Tag, fallback: Tag) -> Tag:
    candidates: list[Tag] = []
    for node in root.find_all(["p", "div", "section"]):
        text = node.get_text(" ", strip=True)
        if "供稿" in text or "排版/审核" in text or "排版／审核" in text:
            candidates.append(node)
    # Smallest candidate is the actual credit line rather than its wrapper.
    return min(candidates, key=lambda node: len(node.get_text(" ", strip=True))) if candidates else fallback


def _trim_after(node: Tag, root: Tag, slot: Tag) -> None:
    node.insert_before(slot)
    sibling = node
    while sibling is not None:
        following = sibling.next_sibling
        sibling.extract()
        sibling = following
    current = slot.parent
    while isinstance(current, Tag) and current is not root:
        sibling = current.next_sibling
        while sibling is not None:
            following = sibling.next_sibling
            sibling.extract()
            sibling = following
        current = current.parent

def _trim_before(node: Tag, root: Tag) -> None:
    sibling = node.previous_sibling
    while sibling is not None:
        previous = sibling.previous_sibling
        sibling.extract()
        sibling = previous
    current = node.parent
    while isinstance(current, Tag) and current is not root:
        sibling = current.previous_sibling
        while sibling is not None:
            previous = sibling.previous_sibling
            sibling.extract()
            sibling = previous
        current = current.parent

def _style_path(node: Tag, root: Tag, placeholder: str = "{{TEXT}}", depth: int = 4) -> str:
    maker = BeautifulSoup("", "html.parser")
    built: Any = placeholder
    current: Any = node
    count = 0
    while isinstance(current, Tag) and current is not root and count < depth:
        wrapper = maker.new_tag(current.name, attrs=dict(current.attrs))
        wrapper.append(built)
        built = wrapper
        current = current.parent
        count += 1
    return str(built)

def _exact_heading(root: Tag, keyword: str) -> Tag | None:
    matches: list[Tag] = []
    for text_node in root.find_all(string=True):
        text = "".join(str(text_node).split()).strip("【】[]")
        if text == keyword and isinstance(text_node.parent, Tag):
            matches.append(text_node.parent)
    return matches[-1] if matches else None


def _bounded_ancestor(node: Tag | None, root: Tag, required: tuple[str, ...], minimum: int, maximum: int) -> Tag | None:
    if node is None:
        return None
    candidates: list[Tag] = []
    current: Any = node
    while isinstance(current, Tag) and current is not root:
        text = current.get_text(" ", strip=True)
        if minimum <= len(text) <= maximum and all(value in text for value in required):
            candidates.append(current)
        current = current.parent
    return max(candidates, key=lambda item: len(str(item))) if candidates else None


def _fixed_modules(root: Tag) -> list[str]:
    modules: list[Tag] = []
    registration = _bounded_ancestor(_exact_heading(root, "活动主办单位"), root, ("活动主办单位", "报名须知"), 100, 500)
    if registration is not None:
        modules.append(registration)
    for keyword in ("温馨提示", "入馆须知"):
        notice = _bounded_ancestor(_exact_heading(root, keyword), root, (keyword,), 400, 1800)
        if notice is not None and not any(notice is item or notice in item.parents for item in modules):
            modules.append(notice)
    return [str(module) for module in modules]
def _semantic_style_slots(root: Tag) -> dict[str, str]:
    """Extract reusable styled paths from real template nodes without sample text."""
    candidates = [node for node in root.find_all(["p", "h1", "h2", "h3", "section"])
                  if 2 <= len(node.get_text(" ", strip=True)) <= 260]
    def pick(test, depth=4):
        for node in candidates:
            text = node.get_text(" ", strip=True)
            if test(node, text):
                return _style_path(node, root, depth=depth)
        return ""
    heading = pick(lambda node, text: node.name in {"h1", "h2", "h3"} and len(text) <= 30)
    info = pick(lambda node, text: any(key in text for key in ("活动时间", "活动地点", "活动人数", "主讲人", "年龄范围", "材料费")), 2)
    notice = pick(lambda node, text: any(key in text for key in ("注意事项", "温馨提示", "须知")) and len(text) >= 12, 2)
    emphasis = pick(lambda node, text: node.find("strong") is not None and 12 <= len(text) <= 180, 2)
    paragraph = pick(lambda node, text: node.name == "p" and 25 <= len(text) <= 220, 2)
    return {key: value for key, value in {"heading": heading, "paragraph": paragraph,
            "emphasis": emphasis, "notice": notice, "info_card": info}.items() if value}

def _named_section_slots(root: Tag) -> dict[str, str]:
    result: dict[str, str] = {}
    for keyword in ("温馨提示", "入馆须知"):
        heading = _exact_heading(root, keyword)
        if heading is None:
            continue
        container: Tag | None = None
        current: Any = heading
        while isinstance(current, Tag) and current is not root:
            length = len(current.get_text(" ", strip=True))
            direct_tags = [child for child in current.children if isinstance(child, Tag)]
            if length >= 80 and len(direct_tags) >= 2:
                container = current
                break
            current = current.parent
        if container is None:
            continue
        copy = BeautifulSoup(str(container), "html.parser").find()
        if copy is None:
            continue
        title_text = next((node for node in copy.find_all(string=True)
                           if "".join(str(node).split()).strip("【】[]") == keyword), None)
        if title_text is None:
            continue
        title_parent = title_text.parent
        title_text.replace_with("{{TITLE}}")
        title_branch: Tag = title_parent if isinstance(title_parent, Tag) else copy
        while isinstance(title_branch.parent, Tag) and title_branch.parent is not copy:
            title_branch = title_branch.parent
        content_branch = next((child for child in copy.children if isinstance(child, Tag) and child is not title_branch), None)
        if content_branch is None:
            continue
        content_branch.clear()
        content_branch.append("{{CONTENT}}")
        result[keyword] = str(copy)
    return result

def _build_dom_skeleton(captured_html: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Annotate replaceable source text/images while preserving the complete DOM."""
    soup = BeautifulSoup(captured_html, "html.parser")
    root = soup.find(id="js_content") or soup.find("article") or soup.find("body") or soup
    ending = _find_ending(root, root)
    ordered = list(root.descendants)
    order = {id(node): index for index, node in enumerate(ordered)}
    ending_order = order.get(id(ending), len(ordered))
    candidates: list[Tag] = []
    for node in root.find_all(["p", "h1", "h2", "h3", "section"]):
        text = node.get_text(" ", strip=True)
        if not text or len(text) > 1200 or order.get(id(node), ending_order) >= ending_order:
            continue
        nested = node.find_all(["p", "h1", "h2", "h3", "section"])
        if any(child is not node and child.get_text(" ", strip=True) for child in nested):
            continue
        candidates.append(node)
    slots: list[dict[str, Any]] = []
    for index, node in enumerate(candidates):
        slot_id = f"text-{index}"
        node["data-wenying-text-slot"] = slot_id
        text = node.get_text(" ", strip=True)
        slots.append({"slotId": slot_id, "slotIndex": index, "sourceText": text[:800],
                      "tag": node.name, "kind": "heading" if node.name in {"h1", "h2", "h3"} or len(text) <= 16 else "paragraph"})
    first_order = order.get(id(candidates[0]), 0) if candidates else 0
    image_slots: list[str] = []
    for image in root.find_all("img"):
        image_order = order.get(id(image), 0)
        if first_order <= image_order < ending_order:
            slot_id = f"image-{len(image_slots)}"
            image["data-wenying-image-slot"] = slot_id
            image_slots.append(slot_id)
    return str(root), slots, image_slots

def build_exact_fragments(captured_html: str) -> dict[str, Any]:
    """Extract balanced, exact fixed HTML before and after the replaceable body."""
    skeleton_html, content_slots, image_slots = _build_dom_skeleton(captured_html)
    prefix_soup = BeautifulSoup(captured_html, "html.parser")
    prefix_root = prefix_soup.find(id="js_content") or prefix_soup.find("article") or prefix_soup.find("body") or prefix_soup
    prefix_blocks = _leaf_text_blocks(prefix_root)
    if not prefix_blocks:
        return {}
    first_text = prefix_blocks[0].get_text(" ", strip=True)
    lead_html = _style_path(prefix_blocks[0], prefix_root)
    paragraph_html = _style_path(prefix_blocks[1], prefix_root, depth=3) if len(prefix_blocks) > 1 else lead_html
    fixed_modules = _fixed_modules(prefix_root)
    style_slots = _semantic_style_slots(prefix_root)
    named_sections = _named_section_slots(prefix_root)
    slot = prefix_soup.new_tag("section")
    slot["data-wenying-prefix-end"] = "true"
    _trim_after(prefix_blocks[0], prefix_root, slot)

    suffix_soup = BeautifulSoup(captured_html, "html.parser")
    suffix_root = suffix_soup.find(id="js_content") or suffix_soup.find("article") or suffix_soup.find("body") or suffix_soup
    suffix_blocks = _leaf_text_blocks(suffix_root)
    if not suffix_blocks:
        return {}
    ending = _find_ending(suffix_root, suffix_blocks[-1])
    ending_text = ending.get_text(" ", strip=True)
    _trim_before(ending, suffix_root)
    return {
        "prefixHtml": str(prefix_root),
        "leadHtml": lead_html,
        "paragraphHtml": paragraph_html,
        "fixedModulesHtml": fixed_modules,
        "styleSlots": style_slots,
        "namedSections": named_sections,
        "skeletonHtml": skeleton_html,
        "contentSlots": content_slots,
        "imageSlots": image_slots,
        "suffixHtml": str(suffix_root),
        "firstText": first_text[:300],
        "endingText": ending_text[:300],
    }


def normalize_lazy_images(value: str) -> str:
    """Promote WeChat data-src to src so exported HTML loads without WeChat JS."""
    soup = BeautifulSoup(value, "html.parser")
    for image in soup.find_all("img"):
        actual = image.get("data-src") or image.get("data-backsrc")
        if actual:
            image["src"] = actual
        image.attrs.pop("data-src", None)
        image.attrs.pop("data-backsrc", None)
    return str(soup)

def apply_asset_replacements(value: str, replacements: dict[str, str]) -> str:
    result = value
    for source, embedded in replacements.items():
        result = result.replace(source, embedded).replace(source.replace("&", "&amp;"), embedded)
    return result



