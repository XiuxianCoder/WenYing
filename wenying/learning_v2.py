from __future__ import annotations

import base64
import io
import json
import mimetypes
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .model_client import ModelError


def _image_url(path: str) -> str:
    """Downscale model inputs; the renderer still uses the untouched original."""
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=78, optimize=True)
            raw = output.getvalue()
        return f"data:image/jpeg;base64,{base64.b64encode(raw).decode('ascii')}"
    except Exception:
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


def _api_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if "mp.weixin.qq.com" in url:
        raise ModelError("模型 API 地址不能填写公众号地址；公众号地址应填写在主页面。")
    if not url.startswith(("https://", "http://")):
        raise ModelError("模型 API 地址格式不正确。")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def _parse_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and data.get("choices"):
        choice = data["choices"][0]
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        raw: Any = message.get("content", message.get("text", ""))
    else:
        raw = data
    if isinstance(raw, list):
        # Content-part arrays use {type:"text", text:"..."}; direct JSON
        # arrays contain template/placement objects and should remain arrays.
        if all(isinstance(item, dict) and any(k in item for k in ("type", "text", "content")) for item in raw):
            pieces = []
            for item in raw:
                value = item.get("text", item.get("content", ""))
                if isinstance(value, dict):
                    value = value.get("value", "")
                pieces.append(str(value))
            raw = "".join(pieces)
        else:
            parsed: Any = raw
            return _normalize(parsed)
    if isinstance(raw, dict):
        return raw
    cleaned = str(raw).strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        starts = [(cleaned.find("{"), "{"), (cleaned.find("["), "[")]
        starts = [item for item in starts if item[0] >= 0]
        if not starts:
            raise ModelError("模型没有返回可解析的 JSON。")
        start, kind = min(starts)
        end = cleaned.rfind("}" if kind == "{" else "]")
        parsed = json.loads(cleaned[start:end + 1])
    return _normalize(parsed)


def _normalize(parsed: Any) -> dict[str, Any]:
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        if len(parsed) == 1 and isinstance(parsed[0], dict) and "styleTokens" in parsed[0]:
            return parsed[0]
        return {"placements": parsed}
    raise ModelError(f"模型返回了不支持的数据类型：{type(parsed).__name__}")


def call_json(endpoint: str, api_key: str, model: str, content: list[dict[str, Any]], seed: int | None = None) -> dict[str, Any]:
    if not api_key:
        raise ModelError("尚未配置 API Key。")
    payload = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.75 if seed is not None else 0.1, "response_format": {"type": "json_object"}}
    # DashScope hybrid Qwen models enable thinking by default. For direct
    # HTTP JSON-mode calls this creates very long latency and may leave only
    # a partial final object. Alibaba documents this as a top-level field.
    if "dashscope.aliyuncs.com" in endpoint.lower():
        payload["enable_thinking"] = False
    if seed is not None:
        payload["seed"] = int(seed)
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    timeouts = (75, 120)
    for attempt, timeout_seconds in enumerate(timeouts):
        request = urllib.request.Request(_api_url(endpoint), data=encoded, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return _parse_payload(json.loads(response.read().decode("utf-8")))
        except ModelError:
            raise
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:800]
            raise ModelError(f"模型接口返回 HTTP {exc.code}：{detail or exc.reason}") from exc
        except Exception as exc:
            last_error = exc
            if attempt + 1 < len(timeouts):
                time.sleep(2)
    raise ModelError(f"模型接口首次请求及自动重试均未返回：{last_error}") from last_error
def _fetch_html(url: str) -> str:
    if not url:
        return ""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Chrome/124 Safari/537.36", "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = response.read(2_000_000).decode("utf-8", errors="ignore")
        return re.sub(r"<script[\s\S]*?</script>", "", value, flags=re.I)[:180_000]
    except Exception as exc:
        raise ModelError(f"模板文章读取失败：{exc}。如果公众号限制访问，请添加文章长截图。") from exc


def learn_template(endpoint: str, api_key: str, model: str, article_url: str, screenshots: list[str], browser_capture: dict[str, Any] | None = None) -> dict[str, Any]:
    prompt = """你是微信公众号排版复刻专家。根据参考文章 HTML/CSS 和截图提炼排版，不复制正文。仅输出一个 JSON 对象，包含 name、styleTokens、blockStyles、layoutRules。styleTokens 必须包含 primaryColor、accentColor、textColor、mutedColor、paperColor、fontSize、lineHeight、paragraphSpacing、contentWidth、imageRadius。准确还原配色、字号、留白、标题装饰和图片形式。另外必须输出 components 对象，包含 headerHtml、coverHtml、leadHtml、titleHtml、headingHtml、paragraphHtml、quoteHtml、noticeHtml、infoCardHtml、imageHtml、endingHtml、footerHtml。正文组件只能保留样式并使用占位符，严禁复制模板样文文字。严格按原页面识别：coverHtml 是正文最前面的固定封面/GIF装饰；leadHtml 是标题前导语容器并使用 {{TEXT}}；endingHtml 是末尾固定署名、供稿、校对、审核等文字及其原始样式；footerHtml 是最后固定推荐图、装饰图、分隔线。组件必须使用微信公众号兼容的内联 CSS，并分别使用 {{TITLE}}、{{TEXT}}、{{NUMBER}}、{{IMAGE_SRC}}、{{CAPTION}} 占位符。必须保留采集素材中的真实图片/GIF/SVG地址，不得用渐变色或普通横线替代固定图片。可以输出 customCss，但禁止 JavaScript。"""
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    source_html = _fetch_html(article_url) if article_url and not browser_capture else ""
    if source_html:
        content.append({"type": "text", "text": f"来源：{article_url}\nHTML/CSS：\n{source_html}"})
    if browser_capture:
        raw_styles = browser_capture.get("styles", [])
        important_styles = [item for item in raw_styles if isinstance(item, dict) and (
            item.get("text") or item.get("tag") in {"section", "img", "svg", "video", "h1", "h2", "h3"}
            or str(item.get("style", {}).get("animation-name", "none")) != "none"
        )][:360]
        assets = [{key: item.get(key) for key in ("tag", "src", "type", "width", "height", "outerHTML")}
                  for item in browser_capture.get("assets", []) if isinstance(item, dict)]
        for item in assets:
            outer = str(item.get("outerHTML", ""))
            match = re.search(r'(?:data-src|data-backsrc)=["\']([^"\']+)', outer)
            if match:
                item["src"] = match.group(1).replace("&amp;", "&")
            item["outerHTML"] = outer[:1200]
        rendered = str(browser_capture.get("html", ""))
        rendered_excerpt = rendered if len(rendered) <= 120_000 else rendered[:60_000] + "\n<!-- 中部正文已省略 -->\n" + rendered[-60_000:]
        compact_capture = {"title": browser_capture.get("title"), "viewport": browser_capture.get("viewport"),
                           "styles": important_styles, "assets": assets,
                           "animations": browser_capture.get("animations", []), "renderedHtml": rendered_excerpt}
        content.append({"type": "text", "text": "以下是浏览器采集摘要。完整页面已在本地保存：\n" + json.dumps(compact_capture, ensure_ascii=False)})
    for path in screenshots:
        content.append({"type": "image_url", "image_url": {"url": _image_url(path)}})
    result = call_json(endpoint, api_key, model, content)
    if "styleTokens" not in result and isinstance(result.get("placements"), list):
        templates = [item for item in result["placements"] if isinstance(item, dict) and "styleTokens" in item]
        if templates:
            result = templates[0]
    if "styleTokens" not in result:
        raise ModelError("模型返回结果缺少 styleTokens。请使用支持结构化 JSON 输出的多模态模型。")
    components = result.get("components")
    if not isinstance(components, dict) or not any(components.get(key) for key in ("headerHtml", "footerHtml", "headingHtml", "imageHtml")):
        raise ModelError("模型没有返回可复用的模板 HTML 组件。请重试，或改用结构化输出能力更强的模型。")
    result.update({"sourceRefs": [article_url] if article_url else screenshots, "sourceType": "mixed" if article_url and screenshots else ("url" if article_url else "screenshot")})
    return result


ORIGINAL_STYLE_PRESETS = {
    "AI 智能匹配": "根据文章主题、受众和图片自动选择最合适的视觉方向",
    "雅致水墨": "东方留白、墨色黛青与少量朱砂、含蓄古典",
    "宋韵古典": "宋画气韵、米白宣纸、细线框与印章点缀",
    "国潮新中式": "传统纹样与现代层级结合，醒目但不俗艳",
    "清新文艺": "柔和浅色、轻盈留白、圆润图片、文化生活气息",
    "温暖治愈": "奶油暖色、柔和卡片、亲和舒缓",
    "自然森系": "低饱和绿与大地色、自然质感、安静清透",
    "现代杂志": "强标题层级、网格感、黑白与单一强调色",
    "极简留白": "大量留白、细字重层级、克制高级",
    "高级黑金": "黑白灰基底与少量金色，适合品牌与人物专题",
    "活动宣传": "时间地点卡片清晰、节奏活泼、行动信息突出",
    "节庆喜庆": "红金暖色、节庆装饰、热烈而整洁",
    "青春活力": "明快撞色、富有节奏、适合青年与社群活动",
    "科技未来": "深蓝青紫、几何线条、科技与数据感",
    "教育科普": "知识层级清楚、重点标注明确、阅读友好",
    "亲子童趣": "明亮柔和、圆角卡片、活泼但不幼稚",
    "简约政务": "端正克制、蓝灰配色、正式可靠",
    "文化展览": "策展画册感、图片主导、说明文字精致",
    "摄影画册": "大图沉浸、极少装饰、图注与留白突出",
}


def generate_original_template(endpoint: str, api_key: str, model: str, document: dict[str, Any], style_name: str, seed: int | None = None) -> dict[str, Any]:
    """Ask one multimodal model to design a reusable browser-first article system."""
    direction = ORIGINAL_STYLE_PRESETS.get(style_name, ORIGINAL_STYLE_PRESETS["AI 智能匹配"])
    blocks = [{"index": i, "type": block.get("type"), "level": block.get("level", 0), "text": block.get("text", "")[:500]}
              for i, block in enumerate(document.get("blocks", [])) if block.get("type") in {"heading", "paragraph", "quote"}]
    blocks = blocks[:48]
    prompt = f"""你是资深数字出版视觉设计师。请根据原稿内容和配图设计一套原创、优美、浏览器优先的自由 HTML 排版母版。
选择风格：{style_name}；方向：{direction}。
只学习原稿语义，不改写、不删减原文。允许渐变、SVG 装饰、CSS 关键帧轻动画、Grid/Flex、阴影、叠层和富有辨识度的卡片；禁止 JavaScript、表单和外链字体。
核心排版和颜色必须写在组件内联 CSS 中，增强动画与响应式规则写入 customCss，确保后续能够自动降级成公众号兼容版。
仅返回 JSON 对象，必须包含：
name；styleTokens(primaryColor,accentColor,textColor,mutedColor,paperColor,fontSize,lineHeight,paragraphSpacing,contentWidth,imageRadius)；
blockStyles；layoutRules；components；customCss。
components 必须包含 titleHtml、leadHtml、headingHtml、paragraphHtml、quoteHtml、noticeHtml、infoCardHtml、imageHtml、endingHtml、footerHtml。
组件只允许使用 {{{{TITLE}}}}、{{{{TEXT}}}}、{{{{IMAGE_SRC}}}}、{{{{CAPTION}}}} 等占位符，严禁把原稿文字写进组件。
标题要有辨识度，正文保证手机阅读清晰；提示、时间地点人物费用应有独立信息卡样式；图片宽度自适应且不过度装饰。"""
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt + "\n原稿标题：" + str(document.get("title", "")) + "\n原稿结构：" + json.dumps(blocks, ensure_ascii=False)}]
    names = document.get("imageNames", {})
    for image_id, path in list(document.get("images", {}).items())[:4]:
        if Path(path).is_file():
            content.extend([{"type": "text", "text": f"配图 {image_id}，文件名：{names.get(image_id, '')}"},
                            {"type": "image_url", "image_url": {"url": _image_url(path)}}])
    result = call_json(endpoint, api_key, model, content, seed=seed)
    if not isinstance(result.get("styleTokens"), dict) or not isinstance(result.get("components"), dict):
        raise ModelError("模型没有返回完整的原创排版结构，请重试。")
    result["name"] = str(result.get("name") or f"AI原创-{style_name}")
    result["sourceType"] = "ai_original"
    result["originalStyle"] = style_name
    result["creativeSeed"] = int(seed or 0)
    result["webEnhancements"] = True
    result["components"]["endingHtml"] = ""
    result["components"]["footerHtml"] = ""
    result.pop("exactFragments", None)
    return result

def optimize_document_text(endpoint: str, api_key: str, model: str, document: dict[str, Any], seed: int | None = None) -> dict[int, str]:
    """Optionally polish prose while preserving every factual value and block boundary."""
    blocks = [{"index": i, "type": block.get("type"), "text": block.get("text", "")}
              for i, block in enumerate(document.get("blocks", [])) if block.get("type") in {"heading", "paragraph", "quote"} and block.get("text", "").strip()]
    prompt = """你是严谨的中文编辑。仅润色表达，使文字更流畅、凝练并适合微信公众号阅读。
不得改变事实、立场、数字、日期、时间、地点、人名、机构名、联系方式、费用、专有名词、条款含义和段落顺序；不得新增或删除内容；不得合并或拆分段落；标题可以润色但不得改变主题。
按原 index 逐项返回且每项只能出现一次。仅输出 JSON：{"optimizedBlocks":[{"index":0,"text":"优化后的完整文字"}]}。"""
    result = call_json(endpoint, api_key, model, [{"type": "text", "text": prompt + "\n原稿：" + json.dumps(blocks, ensure_ascii=False)}], seed=seed)
    output: dict[int, str] = {}
    allowed = {int(item["index"]) for item in blocks}
    for item in result.get("optimizedBlocks", []) if isinstance(result.get("optimizedBlocks"), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        text = str(item.get("text", "")).strip()
        if index in allowed and text:
            output[index] = text
    return output

def plan_document_layout(endpoint: str, api_key: str, model: str, document: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """Semantically map Word blocks in bounded batches to avoid oversized requests."""
    blocks = [{"index": i, "type": b.get("type"), "level": b.get("level", 0), "text": str(b.get("text", ""))[:600]}
              for i, b in enumerate(document.get("blocks", [])) if b.get("type") in {"heading", "paragraph", "quote"}]
    available = ["heading", "paragraph", "lead", "emphasis", "notice", "info_card"]
    prompt = """你是微信公众号文章编辑。理解原稿语义，只做排版结构规划，绝不复制参考模板的任何正文。
为每个文字块选择样式角色：heading=小标题，paragraph=普通正文，lead=开篇导语，emphasis=重点，notice=须知提醒，info_card=时间地点人物费用信息卡。
保持原稿顺序和完整性，不增加任何内容。仅返回 JSON：{"assignments":[{"blockIndex":0,"role":"lead","slotIndex":0}]}。没有合适槽位时省略 slotIndex。"""
    template_summary = {"blockStyles": template.get("blockStyles", {}), "layoutRules": template.get("layoutRules", []),
                        "availableRoles": available, "componentNames": list(template.get("components", {}).keys())}
    valid_indices = {item["index"] for item in blocks}
    valid: list[dict[str, Any]] = []
    seen_blocks: set[int] = set()
    seen_slots: set[int] = set()
    batch_size = 24
    for start in range(0, len(blocks), batch_size):
        batch = blocks[start:start + batch_size]
        content = [{"type": "text", "text": prompt + "\n模板样式能力：" + json.dumps(template_summary, ensure_ascii=False)
                    + "\n原稿标题：" + str(document.get("title", "")) + "\n本批原稿块：" + json.dumps(batch, ensure_ascii=False)}]
        result = call_json(endpoint, api_key, model, content)
        assignments = result.get("assignments", [])
        for item in assignments if isinstance(assignments, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("blockIndex"))
            except (TypeError, ValueError):
                continue
            role = str(item.get("role", "paragraph"))
            if index not in valid_indices or index in seen_blocks or role not in available:
                continue
            output: dict[str, Any] = {"blockIndex": index, "role": role}
            try:
                slot = int(item.get("slotIndex"))
                if slot >= 0 and slot not in seen_slots:
                    output["slotIndex"] = slot
                    seen_slots.add(slot)
            except (TypeError, ValueError):
                pass
            valid.append(output)
            seen_blocks.add(index)
    return {"assignments": valid}
def choose_image_positions(endpoint: str, api_key: str, model: str, document: dict[str, Any], image_ids: list[str]) -> list[dict[str, Any]]:
    blocks = [{"index": i, "type": b.get("type"), "text": str(b.get("text", ""))[:400]}
              for i, b in enumerate(document["blocks"]) if b.get("type") in {"heading", "paragraph", "quote"}]
    prompt = "根据文章语义和图片画面确定插入位置。每张图片必须返回一次。仅输出 JSON 对象：{\"placements\":[{\"imageId\":\"...\",\"afterBlockIndex\":0,\"caption\":\"...\"}]}。段落：" + json.dumps(blocks, ensure_ascii=False)
    names = document.get("imageNames", {})
    placements: list[dict[str, Any]] = []
    batch_size = 4
    for start in range(0, len(image_ids), batch_size):
        batch = image_ids[start:start + batch_size]
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_id in batch:
            path = document["images"].get(image_id)
            if path:
                content += [{"type": "text", "text": f"图片 ID={image_id}，文件名={names.get(image_id, '')}"},
                            {"type": "image_url", "image_url": {"url": _image_url(path)}}]
        result = call_json(endpoint, api_key, model, content)
        values = result.get("placements", [])
        if isinstance(values, list):
            placements.extend(item for item in values if isinstance(item, dict))
    return placements
