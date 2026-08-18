from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .exact_template_v2 import apply_asset_replacements, build_exact_fragments, normalize_lazy_images


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value).strip().rstrip(".")
    return cleaned[:80] or "未命名模板"


def _asset_data_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Chrome/124 Safari/537.36"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(20_000_000)
        content_type = response.headers.get_content_type()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    fmt = (query.get("wx_fmt") or [""])[0].lower()
    if fmt in {"gif", "png", "jpeg", "jpg", "webp"}:
        content_type = "image/jpeg" if fmt in {"jpeg", "jpg"} else f"image/{fmt}"
    if not content_type or content_type == "application/octet-stream":
        content_type = mimetypes.guess_type(urllib.parse.urlparse(url).path)[0] or "image/png"
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def localize_template_assets(template: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    """Embed remote visual assets used by template components, including GIFs."""
    replacements: dict[str, str] = {}
    for asset in capture.get("assets", []):
        if not isinstance(asset, dict):
            continue
        url = str(asset.get("src", ""))
        if not url.startswith(("https://", "http://")) or url in replacements:
            continue
        try:
            replacements[url] = _asset_data_url(url)
        except Exception:
            # Keep the original URL as a usable online fallback.
            continue
    components = template.get("components", {})
    if isinstance(components, dict):
        for key, value in list(components.items()):
            if not isinstance(value, str):
                continue
            for old, new in replacements.items():
                value = value.replace(old, new)
            components[key] = value
    template["components"] = components
    template["localizedAssets"] = replacements
    fragments = build_exact_fragments(str(capture.get("html", "")))
    if fragments:
        fragments["prefixHtml"] = apply_asset_replacements(fragments.get("prefixHtml", ""), replacements)
        fragments["suffixHtml"] = apply_asset_replacements(fragments.get("suffixHtml", ""), replacements)
        fragments["skeletonHtml"] = apply_asset_replacements(fragments.get("skeletonHtml", ""), replacements)
        fragments["fixedModulesHtml"] = [apply_asset_replacements(item, replacements) for item in fragments.get("fixedModulesHtml", [])]
        template["exactFragments"] = fragments
    template["capturedPage"] = {
        "title": capture.get("title", ""),
        "sourceUrl": capture.get("sourceUrl", capture.get("url", "")),
        "html": capture.get("html", ""),
        "styles": capture.get("styles", []),
        "assets": capture.get("assets", []),
        "animations": capture.get("animations", []),
    }
    return template


def save_template(template: dict[str, Any], capture: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    prepared = localize_template_assets(template, capture) if capture else template
    path = directory / f"{safe_name(str(prepared.get('name', '未命名模板')))}.json"
    path.write_text(json.dumps(prepared, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_templates(directory: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not directory.exists():
        return result
    for path in sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            result[str(value.get("name", path.stem))] = path
        except Exception:
            continue
    return result


def load_template(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("模板文件格式不正确")
    captured = value.get("capturedPage", {})
    existing_fragments = value.get("exactFragments", {})
    if (not existing_fragments or not existing_fragments.get("skeletonHtml")) and isinstance(captured, dict) and captured.get("html"):
        fragments = build_exact_fragments(str(captured["html"]))
        replacements = value.get("localizedAssets", {})
        if fragments and isinstance(replacements, dict):
            fragments["prefixHtml"] = apply_asset_replacements(fragments.get("prefixHtml", ""), replacements)
            fragments["suffixHtml"] = apply_asset_replacements(fragments.get("suffixHtml", ""), replacements)
        fragments["skeletonHtml"] = apply_asset_replacements(fragments.get("skeletonHtml", ""), replacements)
        fragments["fixedModulesHtml"] = [apply_asset_replacements(item, replacements) for item in fragments.get("fixedModulesHtml", [])]
        value["exactFragments"] = fragments
    fragments = value.get("exactFragments", {})
    if isinstance(fragments, dict):
        if fragments.get("prefixHtml"):
            fragments["prefixHtml"] = normalize_lazy_images(str(fragments["prefixHtml"]))
        if fragments.get("suffixHtml"):
            fragments["suffixHtml"] = normalize_lazy_images(str(fragments["suffixHtml"]))
        if fragments.get("skeletonHtml"):
            fragments["skeletonHtml"] = normalize_lazy_images(str(fragments["skeletonHtml"]))
    return value



