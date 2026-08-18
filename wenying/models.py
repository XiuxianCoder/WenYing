from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ContentBlock:
    type: str
    text: str = ""
    level: int = 0
    image_id: str = ""
    items: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class DocumentContent:
    title: str = "未命名文章"
    blocks: list[ContentBlock] = field(default_factory=list)
    images: dict[str, str] = field(default_factory=dict)
    image_names: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "blocks": [asdict(block) for block in self.blocks],
            "images": self.images,
            "imageNames": self.image_names,
        }


DEFAULT_TEMPLATE: dict[str, Any] = {
    "name": "烟岚水墨",
    "sourceType": "builtin",
    "sourceRefs": [],
    "styleTokens": {
        "primaryColor": "#24463f",
        "accentColor": "#a44b38",
        "textColor": "#292b29",
        "mutedColor": "#77746d",
        "paperColor": "#f7f3e9",
        "fontSize": 16,
        "lineHeight": 1.9,
        "paragraphSpacing": 18,
    },
    "blockStyles": {
        "title": "居中宋体大标题，墨色，留白充足",
        "heading": "黛青小节标题，朱砂序号点缀",
        "paragraph": "舒展正文，适合手机阅读",
        "quote": "浅宣纸底色、左侧黛青细线",
        "image": "通栏圆角图片，附灰色图注",
    },
    "layoutRules": ["保持原文顺序", "小节之间增加呼吸感", "装饰克制，不遮蔽内容"],
}

