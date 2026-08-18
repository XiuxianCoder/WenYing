from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import re
import urllib.parse
import urllib.request
import urllib.request as urllib_request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag
from PIL import Image, ImageOps


class WeChatPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishResult:
    draft_media_id: str
    publish_id: str = ""
    mass_msg_id: str = ""


def _json_request(url: str, payload: dict[str, Any] | None = None, timeout: int = 45) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise WeChatPublishError(f"微信接口连接失败：{exc}") from exc
    if not isinstance(result, dict):
        raise WeChatPublishError("微信接口返回了无法识别的数据。")
    error_code = int(result.get("errcode", 0) or 0)
    if error_code != 0:
        raw_message = str(result.get("errmsg", "未知错误"))
        if error_code == 40164:
            match = re.search(r"invalid ip\s+([^,\s]+)", raw_message, flags=re.I)
            reported = match.group(1) if match else ""
            ipv4_match = re.search(r"(?:\d{1,3}\.){3}\d{1,3}", reported or raw_message)
            public_ip = ipv4_match.group(0) if ipv4_match else reported
            ip_text = f"当前接口出口 IP：{public_ip}\n" if public_ip else ""
            raise WeChatPublishError(
                "当前电脑的公网出口 IP 未加入公众号白名单。\n\n"
                + ip_text
                + "请登录微信公众平台，进入“设置与开发 → 基本配置（或开发接口管理）→ IP白名单”，"
                + "把上面的 IPv4 地址加入并保存，然后重新发布。\n\n"
                + "如果网络使用动态公网 IP，地址变化后需要重新更新白名单。"
            )
        raise WeChatPublishError(f"微信接口错误 {error_code}：{raw_message}")
    return result


def _multipart_request(url: str, content: bytes, filename: str, mime: str, timeout: int = 60) -> dict[str, Any]:
    boundary = "----WenYing" + hashlib.sha1(content).hexdigest()[:18]
    head = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    body = head + content + f"\r\n--{boundary}--\r\n".encode("ascii")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise WeChatPublishError(f"微信图片上传失败：{exc}") from exc
    if int(result.get("errcode", 0) or 0) != 0:
        raise WeChatPublishError(f"微信图片上传错误 {result.get('errcode')}：{result.get('errmsg', '未知错误')}")
    return result


def _source_bytes(src: str) -> tuple[bytes, str]:
    if src.startswith("data:"):
        match = re.match(r"data:([^;,]+)?(?:;base64)?,(.*)", src, flags=re.S)
        if not match:
            raise WeChatPublishError("正文中存在无法识别的内嵌图片。")
        mime = match.group(1) or "image/png"
        try:
            return base64.b64decode(match.group(2)), mime
        except Exception as exc:
            raise WeChatPublishError("正文中的内嵌图片解码失败。") from exc
    if src.startswith(("http://", "https://")):
        request = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(12_000_000), response.headers.get_content_type() or "image/jpeg"
    if src.startswith("file:"):
        parsed = urllib.parse.urlparse(src)
        local = urllib_request.url2pathname(parsed.path)
        if re.match(r"^/[A-Za-z]:/", local):
            local = local[1:]
        path = Path(local)
        if path.is_file():
            return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/jpeg"
        raise WeChatPublishError(f"找不到正文图片：{src[:100]}")
    path = Path(src)
    if path.is_file():
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/jpeg"
    raise WeChatPublishError(f"找不到正文图片：{src[:100]}")


def _jpeg_for_wechat(content: bytes, max_bytes: int = 950_000) -> tuple[bytes, str, str]:
    try:
        with Image.open(io.BytesIO(content)) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            for quality in (88, 80, 72, 64, 56):
                output = io.BytesIO()
                image.save(output, "JPEG", quality=quality, optimize=True)
                if len(output.getvalue()) <= max_bytes:
                    return output.getvalue(), "image/jpeg", "wenying.jpg"
            return output.getvalue(), "image/jpeg", "wenying.jpg"
    except Exception as exc:
        raise WeChatPublishError(f"图片转换失败：{exc}") from exc


class WeChatPublisher:
    def __init__(self, appid: str, secret: str) -> None:
        self.appid = appid.strip()
        self.secret = secret.strip()
        if not self.appid or not self.secret:
            raise WeChatPublishError("请先配置公众号 AppID 和 AppSecret。")

    def access_token(self) -> str:
        query = urllib.parse.urlencode({"grant_type": "client_credential", "appid": self.appid, "secret": self.secret})
        result = _json_request("https://api.weixin.qq.com/cgi-bin/token?" + query)
        token = str(result.get("access_token", ""))
        if not token:
            raise WeChatPublishError("微信没有返回 access_token，请检查 AppID、AppSecret 和 IP 白名单。")
        return token

    def _upload_body_image(self, token: str, content: bytes) -> str:
        image, mime, filename = _jpeg_for_wechat(content)
        result = _multipart_request(
            "https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token=" + urllib.parse.quote(token),
            image, filename, mime,
        )
        url = str(result.get("url", ""))
        if not url:
            raise WeChatPublishError("微信上传正文图片后没有返回 URL。")
        return url

    def _upload_cover(self, token: str, content: bytes) -> str:
        image, mime, filename = _jpeg_for_wechat(content)
        result = _multipart_request(
            "https://api.weixin.qq.com/cgi-bin/material/add_material?access_token="
            + urllib.parse.quote(token) + "&type=thumb",
            image, filename, mime,
        )
        media_id = str(result.get("media_id", ""))
        if not media_id:
            raise WeChatPublishError("微信上传封面后没有返回 media_id。")
        return media_id

    def publish(
        self, html_fragment: str, title: str, author: str = "", digest: str = "",
        cover_path: str = "", direct_publish: bool = False, mass_send: bool = False,
    ) -> PublishResult:
        token = self.access_token()
        soup = BeautifulSoup(html_fragment, "html.parser")
        images = soup.find_all("img")
        first_content: bytes | None = None
        uploaded: dict[str, str] = {}
        for image in images:
            if not isinstance(image, Tag):
                continue
            src = str(image.get("src", "")).strip()
            if not src:
                continue
            raw, _mime = _source_bytes(src)
            first_content = first_content or raw
            digest_key = hashlib.sha256(raw).hexdigest()
            if digest_key not in uploaded:
                uploaded[digest_key] = self._upload_body_image(token, raw)
            image["src"] = uploaded[digest_key]

        if cover_path:
            cover_content = Path(cover_path).read_bytes()
        elif first_content:
            cover_content = first_content
        else:
            raise WeChatPublishError("文章没有图片，请在发布窗口选择一张封面图。")
        thumb_media_id = self._upload_cover(token, cover_content)
        content = str(soup)
        if len(content.encode("utf-8")) >= 950_000:
            raise WeChatPublishError("适配后的正文超过微信接口 1MB 限制，请减少图片装饰或拆分文章。")
        article = {
            "title": title[:64], "author": author[:16], "digest": digest[:120],
            "content": content, "content_source_url": "", "thumb_media_id": thumb_media_id,
            "need_open_comment": 0, "only_fans_can_comment": 0,
        }
        if mass_send:
            mass_article = dict(article)
            mass_article["show_cover_pic"] = 0
            material = _json_request(
                "https://api.weixin.qq.com/cgi-bin/material/add_news?access_token=" + urllib.parse.quote(token),
                {"articles": [mass_article]}, timeout=60,
            )
            media_id = str(material.get("media_id", ""))
            if not media_id:
                raise WeChatPublishError("微信创建群发图文素材后没有返回 media_id。")
            sent = _json_request(
                "https://api.weixin.qq.com/cgi-bin/message/mass/sendall?access_token=" + urllib.parse.quote(token),
                {
                    "filter": {"is_to_all": True, "tag_id": 0},
                    "mpnews": {"media_id": media_id},
                    "msgtype": "mpnews",
                    "send_ignore_reprint": 0,
                }, timeout=60,
            )
            return PublishResult(media_id, mass_msg_id=str(sent.get("msg_id", "")))
        draft = _json_request(
            "https://api.weixin.qq.com/cgi-bin/draft/add?access_token=" + urllib.parse.quote(token),
            {"articles": [article]}, timeout=60,
        )
        media_id = str(draft.get("media_id", ""))
        if not media_id:
            raise WeChatPublishError("草稿创建成功响应中缺少 media_id。")
        if not direct_publish:
            return PublishResult(media_id)
        published = _json_request(
            "https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token=" + urllib.parse.quote(token),
            {"media_id": media_id}, timeout=60,
        )
        return PublishResult(media_id, str(published.get("publish_id", "")))
