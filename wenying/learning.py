from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.request
from pathlib import Path
from typing import Any

from .model_client import ModelError


def _data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


def _endpoint(value: str) -> str:
    url = value.strip().rstrip("/")
    if "mp.weixin.qq.com" in url:
        raise ModelError("模型 API 地址不能填写公众号文章地址。请在主页的“模板文章地址”中填写公众号链接。")
    if not url.startswith(("http://", "https://")):
        raise ModelError("模型 API 地址格式不正确。")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def fetch_article_html(url: str) -> str:
    if not url:
        return ""
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="ignore")
        # Keep style declarations and article body while removing executable noise.
        raw = re.sub(r"<script[\s\S]*?</script>", "", raw, flags=re.I)
        return raw[:180_000]
    except Exception as exc:
        raise ModelError(f"公众号文章读取失败：{exc}。可添加文章长截图继续分析。") from exc


def call_json(endpoint: str, api_key: str, model: str, content: list[dict[str, Any]], timeout: int = 180) -> dict[str, Any]:
    if not api_key:
        raise ModelError("尚未配置 API Key。")
    payload = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.1, "response_format": {"type": "json_object"}}
    request = urllib.request.Request(
        _endpoint(endpoint), data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"]
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") for part in raw if isinstance(part, dict))
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        return json.loads(raw)
    except ModelError:
        raise
    except Exception as exc:
        raise ModelError(f"模型调用失败：{exc}") from exc


def learn_template(endpoint: str, api_key: str, model: str, article_url: str, screenshots: list[str]) -> dict[str, Any]:
    article_html = fetch_article_html(article_url) if article_url else ""
    prompt = """你是微信公众号排版复刻专家。请从参考文章 HTML/CSS 和截图中准确归纳可复用视觉规则，不复制原文。
仅输出 JSON，包含 name, sourceType, sourceRefs, styleTokens, blockStyles, layoutRules。
styleTokens 必须含 primaryColor, accentColor, textColor, mutedColor, paperColor, fontSize(数字), lineHeight(数字), paragraphSpacing(数字), contentWidth(数字), imageRadius(数字)。
blockStyles 必须描述 title, heading, paragraph, quote, image。重点还原颜色、字号、留白、标题装饰、图片宽度与卡片形式，适配微信公众号内联 CSS。"""
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if article_url:
        content.append({"type": "text", "text": f"来源地址：{article_url}"})
    if article_html:
        content.append({"type": "text", "text": "以下是文章 HTML/CSS：\n" + article_html})
    for path in screenshots:
        content.append({"type": "image_url", "image_url": {"url": _data_url(path)}})
    result = call_json(endpoint, api_key, model, content)
    result["sourceRefs"] = [article_url] if article_url else list(screenshots)
    result["sourceType"] = "mixed" if article_url and screenshots else ("url" if article_url else "screenshot")
    return result


def choose_image_positions(endpoint: str, api_key: str, model: str, document: dict[str, Any], image_ids: list[str]) -> list[dict[str, Any]]:
    blocks = [{"index": i, "type": b.get("type"), "text": b.get("text", "")[:1000]} for i, b in enumerate(document["blocks"]) if b.get("type") in {"heading", "paragraph", "quote"}]
    prompt = "根据文章语义与图片画面确定插图位置。仅输出 JSON：{\"placements\":[{\"imageId\":\"...\",\"afterBlockIndex\":0,\"caption\":\"...\"}]}。每张图片都必须返回一次，索引只能来自给定段落。\n" + json.dumps(blocks, ensure_ascii=False)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    names = document.get("imageNames", {})
    for image_id in image_ids:
        path = document["images"].get(image_id)
        if path:
            content.extend([{"type": "text", "text": f"ID={image_id} 文件名={names.get(image_id, '')}"}, {"type": "image_url", "image_url": {"url": _data_url(path)}}])
    return call_json(endpoint, api_key, model, content).get("placements", [])
