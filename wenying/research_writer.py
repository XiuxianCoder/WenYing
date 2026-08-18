from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from .learning_v2 import call_json
from .model_client import ModelError
from .models import ContentBlock, DocumentContent


class ResearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchSource:
    title: str
    url: str
    snippet: str = ""
    content: str = ""


def _public_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def search_web(query: str, limit: int = 8) -> list[SearchSource]:
    """Merge fresh news and general web RSS results without requiring a search API key."""
    sources: list[SearchSource] = []
    seen: set[str] = set()
    endpoints = (
        "https://www.bing.com/news/search?" + urllib.parse.urlencode({"q": query, "format": "rss", "setlang": "zh-CN"}),
        "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "format": "rss", "setlang": "zh-CN"}),
    )
    errors: list[str] = []
    for url in endpoints:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 WenYing/1.0", "Accept": "application/rss+xml,application/xml"})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                root = ET.fromstring(response.read(2_000_000))
        except Exception as exc:
            errors.append(str(exc)); continue
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            snippet = BeautifulSoup(item.findtext("description") or "", "html.parser").get_text(" ", strip=True)
            if link and link not in seen and _public_url(link):
                sources.append(SearchSource(title, link, snippet[:500])); seen.add(link)
            if len(sources) >= limit:
                break
        if len(sources) >= limit:
            break
    if not sources:
        detail = f"（{'；'.join(errors[:2])}）" if errors else ""
        raise ResearchError("没有检索到可用资料，请更换关键词后重试。" + detail)
    return sources


def _extract_page(source: SearchSource) -> SearchSource:
    request = urllib.request.Request(source.url, headers={"User-Agent": "Mozilla/5.0 WenYing/1.0", "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            mime = response.headers.get_content_type()
            if mime not in {"text/html", "application/xhtml+xml", "text/plain"}:
                return source
            raw = response.read(1_500_000).decode(response.headers.get_content_charset() or "utf-8", errors="ignore")
        soup = BeautifulSoup(raw, "html.parser")
        for node in soup(["script", "style", "nav", "footer", "form", "noscript", "aside"]):
            node.decompose()
        root = soup.find("article") or soup.find("main") or soup.body or soup
        paragraphs = [node.get_text(" ", strip=True) for node in root.find_all(["h1", "h2", "h3", "p", "li"])]
        text = "\n".join(value for value in paragraphs if len(value) >= 20)
        return SearchSource(source.title, source.url, source.snippet, text[:6000])
    except Exception:
        return source


def research(query: str, limit: int = 6) -> list[SearchSource]:
    sources = search_web(query, limit)
    with ThreadPoolExecutor(max_workers=min(6, len(sources))) as executor:
        return list(executor.map(_extract_page, sources))


def _blocks_from_text(value: str) -> list[ContentBlock]:
    """Accept plain text, Markdown, or simple HTML returned by compatible models."""
    text = str(value or "").strip()
    if not text:
        return []
    fences = list(re.finditer(r"```(?:[\w.+#-]+)?\s*\n([\s\S]*?)```", text))
    if fences:
        parsed: list[ContentBlock] = []
        cursor = 0
        for match in fences:
            parsed.extend(_blocks_from_text(text[cursor:match.start()]))
            code = match.group(1).strip("\r\n")
            if code:
                parsed.append(ContentBlock("code", code))
            cursor = match.end()
        parsed.extend(_blocks_from_text(text[cursor:]))
        return parsed
    if re.search(r"</?(?:p|h[1-6]|section|blockquote|li|pre)\b", text, flags=re.I):
        soup = BeautifulSoup(text, "html.parser")
        parsed: list[ContentBlock] = []
        for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "li", "pre"]):
            item_text = node.get_text(" ", strip=True)
            if not item_text:
                continue
            if node.name == "pre":
                parsed.append(ContentBlock("code", node.get_text("\n", strip=True)))
            elif node.name.startswith("h"):
                parsed.append(ContentBlock("heading", item_text, level=min(3, int(node.name[1]))))
            elif node.name == "blockquote":
                parsed.append(ContentBlock("quote", item_text))
            else:
                parsed.append(ContentBlock("paragraph", item_text))
        if parsed:
            return parsed
    text = re.sub(r"^```(?:markdown|md|text|html)?\s*|\s*```$", "", text, flags=re.I)
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n+", text) if chunk.strip()]
    if len(chunks) == 1 and "\n" in text:
        chunks = [line.strip() for line in text.splitlines() if line.strip()]
    blocks: list[ContentBlock] = []
    for chunk in chunks:
        heading = re.match(r"^#{1,6}\s+(.+)$", chunk)
        if heading:
            level = min(3, len(chunk) - len(chunk.lstrip("#")))
            blocks.append(ContentBlock("heading", heading.group(1).strip(), level=level))
        elif re.match(r"^【[^】]{1,30}】$", chunk) or (len(chunk) <= 24 and chunk.endswith(("：", ":"))):
            blocks.append(ContentBlock("heading", chunk.strip("：:"), level=1))
        elif chunk.startswith(">"):
            blocks.append(ContentBlock("quote", re.sub(r"^>\s?", "", chunk)))
        else:
            blocks.append(ContentBlock("paragraph", chunk))
    return blocks


def _coerce_article(result: dict[str, Any], fallback_title: str) -> tuple[str, list[ContentBlock]]:
    """Normalize common JSON shapes emitted by OpenAI-compatible providers."""
    candidates: list[dict[str, Any]] = [result]
    for key in ("article", "data", "result", "output"):
        nested = result.get(key)
        if isinstance(nested, dict):
            candidates.insert(0, nested)
    title = fallback_title.strip()
    for candidate in candidates:
        for key in ("title", "headline", "articleTitle", "article_title"):
            if str(candidate.get(key, "")).strip():
                title = str(candidate[key]).strip()
                break
        if title != fallback_title.strip():
            break

    blocks: list[ContentBlock] = []

    def add_value(value: Any, default_type: str = "paragraph") -> None:
        if isinstance(value, str):
            blocks.extend(_blocks_from_text(value))
            return
        if isinstance(value, list):
            for item in value:
                add_value(item, default_type)
            return
        if not isinstance(value, dict):
            return
        item_type = str(value.get("type", value.get("blockType", default_type))).lower()
        mapped_type = "heading" if item_type in {"heading", "header", "subtitle", "section", "h1", "h2", "h3"} else ("quote" if item_type in {"quote", "blockquote"} else ("code" if item_type in {"code", "codeblock", "code_block", "pre"} else "paragraph"))
        item_title = str(value.get("title", value.get("heading", value.get("subtitle", "")))).strip()
        if item_title and item_title != title:
            blocks.append(ContentBlock("heading", item_title, level=1))
        text_value = next((value[key] for key in ("text", "content", "body", "paragraph", "value", "description") if value.get(key)), "")
        if isinstance(text_value, str) and text_value.strip():
            parsed = [ContentBlock("code", text_value.strip())] if mapped_type == "code" else _blocks_from_text(text_value)
            if mapped_type != "paragraph" and len(parsed) == 1 and parsed[0].type == "paragraph":
                parsed[0].type = mapped_type
                parsed[0].level = 1 if mapped_type == "heading" else 0
            blocks.extend(parsed)
        elif isinstance(text_value, (list, dict)):
            add_value(text_value, mapped_type)
        for key in ("sections", "blocks", "paragraphs", "items"):
            if value.get(key) is not text_value:
                add_value(value.get(key), default_type)

    for candidate in candidates:
        before = len(blocks)
        for key in ("blocks", "sections", "paragraphs", "content", "body", "article", "text", "answer", "placements"):
            if key in candidate:
                add_value(candidate.get(key))
        if len(blocks) > before:
            break
    return title or fallback_title.strip(), blocks


def write_article(
    endpoint: str, api_key: str, model: str, topic: str, keywords: str,
    article_type: str, length: int, include_sources: bool = True,
    focus: str = "自动判断", requirements: str = "",
) -> tuple[DocumentContent, list[SearchSource]]:
    query = keywords.strip() or topic.strip()
    sources = research(query)
    research_pack = [
        {"sourceId": index + 1, "title": source.title, "url": source.url,
         "snippet": source.snippet, "content": source.content}
        for index, source in enumerate(sources)
    ]
    focus_text = focus.strip() or "自动判断"
    requirement_text = requirements.strip() or "无额外要求，由你根据主题合理组织"
    prompt = f"""你是严谨的微信公众号中文作者。当前日期：{date.today().isoformat()}。
请围绕主题“{topic}”撰写一篇{article_type}，目标长度约{length}字。
文章侧重点：{focus_text}。
具体内容要求：{requirement_text}。
只能依据给定检索资料陈述可核实的事实；资料冲突时明确说明，不得虚构数据、人物、政策或引语。保持自然、有吸引力的公众号表达，避免空洞套话。
仅返回 JSON 对象：{{"title":"标题","summary":"摘要","blocks":[{{"type":"heading|paragraph|quote|code","text":"完整文字"}}]}}。
如果侧重点或具体要求涉及编程，必须给出可运行的完整代码和必要命令，并使用 type=code 的独立块保存代码；不得把代码压缩成普通段落。
blocks 必须形成完整文章，绝对不能为空；至少返回 6 个正文块，总字数接近 {length} 字。标题不要重复进入 blocks。不要输出 Markdown、HTML 或代码围栏。输出前检查 JSON 中不仅有 title，而且有完整 blocks 正文。资料如下：
{json.dumps(research_pack, ensure_ascii=False)}"""
    result = call_json(endpoint, api_key, model, [{"type": "text", "text": prompt}])
    title, blocks = _coerce_article(result, topic)
    if not blocks:
        repair_prompt = f"""你刚才只返回了文章标题，没有正文。现在请一次性补全约 {length} 字的{article_type}。
主题：{topic}
标题：{title}
文章侧重点：{focus_text}
具体内容要求：{requirement_text}
严格依据下面的资料摘要，不得虚构事实。只返回 JSON：{{"title":"标题","content":"包含小标题和完整段落的全文"}}。
content 不得为空，不能只返回标题。资料摘要：
{json.dumps([{"title": item["title"], "snippet": item["snippet"], "content": item["content"][:1800]} for item in research_pack], ensure_ascii=False)}"""
        repaired = call_json(endpoint, api_key, model, [{"type": "text", "text": repair_prompt}])
        title, blocks = _coerce_article(repaired, title)
    if not blocks:
        raise ModelError("模型连续两次只返回标题，没有生成正文。请在模型设置中改用 qwen3.6-flash 后重试。")
    if include_sources:
        blocks.append(ContentBlock("heading", "资料来源", level=1))
        for index, source in enumerate(sources, 1):
            blocks.append(ContentBlock("paragraph", f"[{index}] {source.title}：{source.url}"))
    return DocumentContent(title=title, blocks=blocks), sources
