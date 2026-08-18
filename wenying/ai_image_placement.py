from __future__ import annotations

import base64
import json
import mimetypes
import urllib.request
from pathlib import Path
from typing import Any

from .model_client import ModelError


def _data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def place_article_images(endpoint: str, api_key: str, model: str, document: dict[str, Any], image_ids: list[str]) -> list[dict[str, Any]]:
    blocks = [
        {"index": i, "type": block.get("type"), "level": block.get("level"), "text": block.get("text", "")[:800]}
        for i, block in enumerate(document.get("blocks", []))
        if block.get("type") in {"heading", "paragraph", "quote"}
    ]
    prompt = (
        "你是中文公众号图文编辑。根据文章段落语义、图片文件名和图片画面，为每张图片选择最合适的插入位置。"
        "不要改变文章内容。仅输出 JSON：{\"placements\":[{\"imageId\":字符串,\"afterBlockIndex\":整数,"
        "\"caption\":简短图注,\"reason\":简短理由}]}。afterBlockIndex 必须引用提供的段落索引。\n"
        f"文章标题：{document.get('title', '')}\n段落：{json.dumps(blocks, ensure_ascii=False)}"
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    names = document.get("imageNames", {})
    for image_id in image_ids:
        path = document.get("images", {}).get(image_id)
        if path:
            content.append({"type": "text", "text": f"图片 ID={image_id}，文件名={names.get(image_id, '')}"})
            content.append({"type": "image_url", "image_url": {"url": _data_url(path)}})
    payload = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.1, "response_format": {"type": "json_object"}}
    url = endpoint.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"]
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        return json.loads(raw).get("placements", [])
    except Exception as exc:
        raise ModelError(f"智能配图失败：{exc}") from exc
