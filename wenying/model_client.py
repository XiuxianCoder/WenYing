from __future__ import annotations

import base64
import json
import mimetypes
import urllib.request
from pathlib import Path
from typing import Any


class ModelError(RuntimeError):
    pass


def _data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def analyze_template(endpoint: str, api_key: str, model: str, source_url: str = "", images: list[str] | None = None) -> dict[str, Any]:
    if not endpoint or not model:
        raise ModelError("请先填写 API 地址和模型名称。")
    if not api_key:
        raise ModelError("请填写 API Key；它只在本次运行中使用。")
    prompt = """你是微信公众号排版设计师。分析输入的参考文章或截图，只学习视觉排版规律，不复制文章内容。
请仅输出 JSON 对象，字段必须包含：name, sourceType, sourceRefs, styleTokens, blockStyles, layoutRules。
styleTokens 必须包含 primaryColor, accentColor, textColor, mutedColor, paperColor, fontSize(数字), lineHeight(数字), paragraphSpacing(数字)。
blockStyles 描述 title, heading, paragraph, quote, image。所有颜色使用 #RRGGBB。设计必须适合微信公众号内联 CSS。"""
    if source_url:
        prompt += f"\n参考文章地址：{source_url}"
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in images or []:
        content.append({"type": "image_url", "image_url": {"url": _data_url(path)}})
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    url = endpoint.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"]
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        return json.loads(raw)
    except Exception as exc:
        raise ModelError(f"模型调用失败：{exc}") from exc
