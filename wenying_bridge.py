from __future__ import annotations

import contextlib
import copy
import html
import json
import os
import re
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup

from wenying.docx_parser import parse_docx
from wenying.image_placement import add_external_images, apply_ai_placements, place_images_evenly
from wenying.learning_v2 import (
    ORIGINAL_STYLE_PRESETS,
    choose_image_positions,
    generate_original_template,
    learn_template,
    optimize_document_text,
    plan_document_layout,
)
from wenying.models import DEFAULT_TEMPLATE, DocumentContent
from wenying.renderer_v3 import render_html
from wenying.research_writer import write_article
from wenying.template_store import list_templates, load_template, save_template
from wenying.wechat_adapter import TARGETS, adapt_html
from wenying.wechat_publisher import WeChatPublisher


ROOT = Path(os.getenv("WENYING_PROJECT_ROOT", Path(__file__).resolve().parent)).resolve()
RUNTIME_ROOT = Path(os.getenv("WENYING_DATA_ROOT", ROOT)).resolve()
DATA = RUNTIME_ROOT / "data"
OUTPUT = RUNTIME_ROOT / "output"
ASSETS = OUTPUT / "assets"
TEMPLATES = DATA / "templates"
SETTINGS = DATA / "settings.json"
BROWSER_CAPTURE = DATA / "template_browser_capture.json"
ERROR_LOG = DATA / "wenying_error.log"
for folder in (DATA, OUTPUT, ASSETS, TEMPLATES):
    folder.mkdir(parents=True, exist_ok=True)


def _safe_filename(value: str, suffix: str = "") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-") or "文映文章"
    return f"{cleaned[:90]}{suffix}.html"


def _write_log(label: str) -> None:
    try:
        with ERROR_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Electron bridge {label}\n{traceback.format_exc()}\n")
    except OSError:
        pass


class WenYingEngine:
    def __init__(self) -> None:
        self.document: DocumentContent | None = None
        self.template: dict[str, Any] = copy.deepcopy(DEFAULT_TEMPLATE)
        self.template_ready = False
        self.unmatched_images: list[str] = []
        self.template_images: list[str] = []
        self.output_html = ""
        self.preview_path = ""
        self.existing_html_path = ""
        self.settings = self._load_settings()

    def _load_settings(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "endpoint": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "wechat_appid": "",
            "wechat_secret": "",
            "wechat_author": "",
            "output_dir": str(OUTPUT),
            "ui_font": "华文行楷",
        }
        try:
            value = json.loads(SETTINGS.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                defaults.update(value)
        except Exception:
            pass
        return defaults

    def _save_settings(self) -> None:
        SETTINGS.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")

    def _output_dir(self) -> Path:
        raw = str(self.settings.get("output_dir", "")).strip()
        folder = Path(raw).expanduser() if raw else OUTPUT
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _require_document(self) -> DocumentContent:
        if not self.document:
            raise ValueError("请先导入 Word，或使用 AI 联网写作创建原稿。")
        return self.document

    def _require_model(self) -> tuple[str, str, str]:
        endpoint = str(self.settings.get("endpoint", "")).strip()
        api_key = str(self.settings.get("api_key", "")).strip()
        model = str(self.settings.get("model", "")).strip()
        if not endpoint or not model or not api_key:
            raise ValueError("请先在设置中填写模型地址、模型名称和 API Key。")
        return endpoint, api_key, model

    def _write_preview(self, source: str | None = None, suffix: str = "_预览") -> Path:
        document = self._require_document()
        content = self.output_html if source is None else source
        path = self._output_dir() / _safe_filename(document.title, suffix)
        path.write_text(content, encoding="utf-8")
        self.preview_path = str(path.resolve())
        return path

    def _template_cards(self) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for name, path in list_templates(TEMPLATES).items():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                tokens = value.get("styleTokens", {}) if isinstance(value, dict) else {}
                cards.append({
                    "name": name,
                    "path": str(path.resolve()),
                    "sourceType": str(value.get("sourceType", "template")),
                    "primaryColor": str(tokens.get("primaryColor", "#365b52")),
                    "accentColor": str(tokens.get("accentColor", "#a44b38")),
                })
            except Exception:
                continue
        return cards

    def public_settings(self) -> dict[str, Any]:
        return {
            "endpoint": str(self.settings.get("endpoint", "")),
            "model": str(self.settings.get("model", "")),
            "output_dir": str(self.settings.get("output_dir", str(OUTPUT))),
            "ui_font": str(self.settings.get("ui_font", "华文行楷")),
            "wechat_appid": str(self.settings.get("wechat_appid", "")),
            "wechat_author": str(self.settings.get("wechat_author", "")),
            "apiKeyConfigured": bool(str(self.settings.get("api_key", "")).strip()),
            "wechatSecretConfigured": bool(str(self.settings.get("wechat_secret", "")).strip()),
        }

    def state(self, include_html: bool = True) -> dict[str, Any]:
        document = self.document
        blocks = []
        headings: list[str] = []
        placed = 0
        if document:
            for index, block in enumerate(document.blocks):
                blocks.append({
                    "index": index,
                    "type": block.type,
                    "text": block.text,
                    "level": block.level,
                    "imageId": block.image_id,
                    "items": block.items,
                    "rows": block.rows,
                })
                if block.type == "heading" and block.text:
                    headings.append(block.text)
                if block.type == "image":
                    placed += 1
        tokens = self.template.get("styleTokens", {}) if isinstance(self.template, dict) else {}
        return {
            "ready": True,
            "document": None if not document else {
                "title": document.title,
                "blocks": blocks,
                "blockCount": len(document.blocks),
                "imageCount": len(document.images),
                "placedImageCount": placed,
                "headings": headings,
            },
            "template": {
                "name": str(self.template.get("name", "未选择模板")),
                "ready": self.template_ready,
                "sourceType": str(self.template.get("sourceType", "builtin")),
                "primaryColor": str(tokens.get("primaryColor", "#365b52")),
                "accentColor": str(tokens.get("accentColor", "#a44b38")),
            },
            "unmatchedImages": len(self.unmatched_images),
            "hasOutput": bool(self.output_html),
            "previewPath": self.preview_path,
            "previewHtml": self.output_html if include_html else "",
            "existingHtmlPath": self.existing_html_path,
            "templates": self._template_cards(),
            "styles": list(ORIGINAL_STYLE_PRESETS.keys()),
            "targets": list(TARGETS),
            "settings": self.public_settings(),
        }

    def get_state(self, _params: dict[str, Any]) -> dict[str, Any]:
        return self.state()

    def save_settings(self, params: dict[str, Any]) -> dict[str, Any]:
        for key in ("endpoint", "model", "output_dir", "ui_font", "wechat_appid", "wechat_author"):
            if key in params:
                self.settings[key] = str(params.get(key, "")).strip()
        if str(params.get("api_key", "")).strip():
            self.settings["api_key"] = str(params["api_key"]).strip()
        if str(params.get("wechat_secret", "")).strip():
            self.settings["wechat_secret"] = str(params["wechat_secret"]).strip()
        if params.get("clear_api_key"):
            self.settings["api_key"] = ""
        if params.get("clear_wechat_secret"):
            self.settings["wechat_secret"] = ""
        self._output_dir()
        self._save_settings()
        return self.state(include_html=False)

    def parse_word(self, params: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(params.get("path", "")))
        if not path.is_file():
            raise FileNotFoundError("找不到选择的 Word 文档。")
        self.document = parse_docx(str(path), str(ASSETS / path.stem))
        self.template = copy.deepcopy(DEFAULT_TEMPLATE)
        self.template_ready = False
        self.unmatched_images = []
        self.output_html = ""
        self.preview_path = ""
        self.existing_html_path = ""
        return self.state()

    def add_images(self, params: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document()
        paths = [str(item) for item in params.get("paths", []) if Path(str(item)).is_file()]
        self.unmatched_images.extend(add_external_images(document, paths, str(ASSETS / _safe_filename(document.title).removesuffix(".html"))))
        self.output_html = ""
        return self.state()

    def research_write(self, params: dict[str, Any]) -> dict[str, Any]:
        endpoint, api_key, model = self._require_model()
        topic = str(params.get("topic", "")).strip()
        if not topic:
            raise ValueError("请填写文章主题。")
        document, sources = write_article(
            endpoint,
            api_key,
            model,
            topic,
            str(params.get("keywords", "")),
            str(params.get("article_type", "资讯综述")),
            int(params.get("length", 1500)),
            bool(params.get("include_sources", True)),
            str(params.get("focus", "自动判断")),
            str(params.get("requirements", "")),
        )
        self.document = document
        self.template = copy.deepcopy(DEFAULT_TEMPLATE)
        self.template_ready = False
        self.unmatched_images = []
        self.output_html = ""
        result = self.state()
        result["sourceCount"] = len(sources)
        result["sources"] = [asdict(source) for source in sources]
        return result

    def select_template(self, params: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(params.get("path", ""))).resolve()
        if not path.is_file() or path.parent != TEMPLATES.resolve():
            raise ValueError("模板路径无效。")
        self.template = load_template(path)
        self.template_ready = True
        self.output_html = ""
        return self.state()

    def delete_template(self, params: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(params.get("path", ""))).resolve()
        if not path.is_file() or path.parent != TEMPLATES.resolve():
            raise ValueError("模板路径无效。")
        path.unlink()
        return self.state(include_html=False)

    def generate_original(self, params: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document()
        endpoint, api_key, model = self._require_model()
        working = copy.deepcopy(document)
        style_name = str(params.get("style", "AI 智能匹配"))
        seed = int(params.get("seed", 0) or 0) or None
        if bool(params.get("optimize_text", False)):
            optimized = optimize_document_text(endpoint, api_key, model, working.to_dict(), seed)
            for index, value in optimized.items():
                if 0 <= index < len(working.blocks):
                    working.blocks[index].text = value
        template = generate_original_template(endpoint, api_key, model, working.to_dict(), style_name, seed)
        if self.unmatched_images:
            placements = choose_image_positions(endpoint, api_key, model, working.to_dict(), self.unmatched_images)
            apply_ai_placements(working, placements)
        place_images_evenly(working, self.unmatched_images)
        self.unmatched_images = []
        template["documentPlan"] = plan_document_layout(endpoint, api_key, model, working.to_dict(), template)
        saved = save_template(template, {}, TEMPLATES)
        self.template = load_template(saved)
        self.template["documentPlan"] = template["documentPlan"]
        self.template_ready = True
        self.document = working
        self.output_html = render_html(working, self.template)
        self._write_preview()
        return self.state()

    def learn_template(self, params: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document()
        endpoint, api_key, model = self._require_model()
        url = str(params.get("url", "")).strip()
        screenshots = [str(item) for item in params.get("screenshots", []) if Path(str(item)).is_file()]
        capture: dict[str, Any] = {}
        if BROWSER_CAPTURE.is_file():
            try:
                candidate = json.loads(BROWSER_CAPTURE.read_text(encoding="utf-8"))
                if not url or candidate.get("sourceUrl") == url:
                    capture = candidate
            except Exception:
                capture = {}
        if not url and not screenshots and not capture:
            raise ValueError("请填写模板文章地址，或添加模板截图。")
        template = learn_template(endpoint, api_key, model, url, screenshots, capture)
        saved = save_template(template, capture, TEMPLATES)
        self.template = load_template(saved)
        self.template_ready = True
        if self.unmatched_images:
            placements = choose_image_positions(endpoint, api_key, model, document.to_dict(), self.unmatched_images)
            apply_ai_placements(document, placements)
        place_images_evenly(document, self.unmatched_images)
        self.unmatched_images = []
        self.template["documentPlan"] = plan_document_layout(endpoint, api_key, model, document.to_dict(), self.template)
        self.output_html = render_html(document, self.template)
        self._write_preview()
        return self.state()

    def generate_from_template(self, _params: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document()
        if not self.template_ready:
            raise ValueError("请先选择本地模板。")
        endpoint, api_key, model = self._require_model()
        if self.unmatched_images:
            placements = choose_image_positions(endpoint, api_key, model, document.to_dict(), self.unmatched_images)
            apply_ai_placements(document, placements)
        place_images_evenly(document, self.unmatched_images)
        self.unmatched_images = []
        self.template["documentPlan"] = plan_document_layout(endpoint, api_key, model, document.to_dict(), self.template)
        self.output_html = render_html(document, self.template)
        self._write_preview()
        return self.state()

    def render_current(self, _params: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document()
        self.output_html = render_html(document, self.template)
        self._write_preview()
        return self.state()

    def adapt_current(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.output_html:
            self.render_current({})
        target = str(params.get("target", TARGETS[0]))
        if target not in TARGETS:
            raise ValueError("未知的输出目标。")
        adapted = adapt_html(self.output_html, target)
        return {"html": adapted.html, "report": list(adapted.report), "target": target}

    def export_html(self, params: dict[str, Any]) -> dict[str, Any]:
        value = self.adapt_current(params)
        path = Path(str(params.get("path", "")))
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value["html"]), encoding="utf-8")
        return {**value, "path": str(path.resolve())}

    def load_existing_html(self, params: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(params.get("path", "")))
        if not path.is_file():
            raise FileNotFoundError("找不到选择的 HTML 文件。")
        source = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(source, "html.parser")
        title = (soup.title.get_text(" ", strip=True) if soup.title else "") or path.stem
        if not self.document:
            self.document = DocumentContent(title=title)
        else:
            self.document.title = title
        self.output_html = source
        self.preview_path = str(path.resolve())
        self.existing_html_path = str(path.resolve())
        return self.state()

    def wechat_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document()
        if not self.output_html:
            self.render_current({})
        title = str(params.get("title", document.title)).strip() or document.title
        author = str(params.get("author", self.settings.get("wechat_author", ""))).strip()
        adapted = adapt_html(self.output_html, "微信公众号正文")
        content = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title></head>
<body style="margin:0;padding:28px 12px;background:#ededed"><main style="box-sizing:border-box;max-width:677px;margin:auto;padding:28px 22px 48px;background:#fff">
<p style="margin:0 0 8px;color:#999;font-size:13px">微信公众号草稿预览</p><h1 style="margin:0 0 12px;font-size:26px;line-height:1.45">{html.escape(title)}</h1>
<p style="margin:0 0 20px;color:#888;font-size:14px">作者：{html.escape(author or '未填写')}</p>{adapted.html}</main></body></html>'''
        path = self._output_dir() / _safe_filename(title, "_公众号草稿预览")
        path.write_text(content, encoding="utf-8")
        return {"path": str(path.resolve()), "html": content, "report": list(adapted.report)}

    def test_wechat(self, _params: dict[str, Any]) -> dict[str, Any]:
        publisher = WeChatPublisher(str(self.settings.get("wechat_appid", "")), str(self.settings.get("wechat_secret", "")))
        publisher.access_token()
        return {"ok": True, "message": "公众号接口连接成功，AppID、AppSecret 与 IP 白名单均可用。"}

    def publish_wechat(self, params: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document()
        if not self.output_html:
            self.render_current({})
        mode = str(params.get("mode", "draft"))
        if mode not in {"draft", "publish", "mass"}:
            raise ValueError("未知的发布方式。")
        title = str(params.get("title", document.title)).strip()
        if not title:
            raise ValueError("请填写文章标题。")
        author = str(params.get("author", self.settings.get("wechat_author", ""))).strip()
        digest = str(params.get("digest", "")).strip()
        cover = str(params.get("cover", "")).strip()
        self.settings["wechat_author"] = author
        self._save_settings()
        adapted = adapt_html(self.output_html, "微信公众号正文")
        publisher = WeChatPublisher(str(self.settings.get("wechat_appid", "")), str(self.settings.get("wechat_secret", "")))
        result = publisher.publish(
            adapted.html,
            title,
            author,
            digest,
            cover,
            direct_publish=mode == "publish",
            mass_send=mode == "mass",
        )
        return {
            "draftMediaId": result.draft_media_id,
            "publishId": result.publish_id,
            "massMessageId": result.mass_msg_id,
            "mode": mode,
        }


ENGINE = WenYingEngine()
METHODS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "get-state": ENGINE.get_state,
    "save-settings": ENGINE.save_settings,
    "parse-word": ENGINE.parse_word,
    "add-images": ENGINE.add_images,
    "research-write": ENGINE.research_write,
    "select-template": ENGINE.select_template,
    "delete-template": ENGINE.delete_template,
    "generate-original": ENGINE.generate_original,
    "learn-template": ENGINE.learn_template,
    "generate-from-template": ENGINE.generate_from_template,
    "render-current": ENGINE.render_current,
    "adapt-current": ENGINE.adapt_current,
    "export-html": ENGINE.export_html,
    "load-existing-html": ENGINE.load_existing_html,
    "wechat-preview": ENGINE.wechat_preview,
    "test-wechat": ENGINE.test_wechat,
    "publish-wechat": ENGINE.publish_wechat,
}


def respond(message: dict[str, Any]) -> None:
    sys.__stdout__.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.__stdout__.flush()


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        request_id: Any = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            method = str(request.get("method", ""))
            params = request.get("params", {})
            if method not in METHODS:
                raise ValueError(f"未知操作：{method}")
            if not isinstance(params, dict):
                raise ValueError("操作参数格式不正确。")
            with contextlib.redirect_stdout(sys.stderr):
                result = METHODS[method](params)
            respond({"id": request_id, "ok": True, "result": result})
        except Exception as exc:
            _write_log(str(request.get("method", "unknown")) if "request" in locals() else "protocol")
            respond({"id": request_id, "ok": False, "error": str(exc) or exc.__class__.__name__})


if __name__ == "__main__":
    main()
