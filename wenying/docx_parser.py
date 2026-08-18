from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import ContentBlock, DocumentContent

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _text(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{W}t")).strip()


def parse_docx(path: str, asset_dir: str) -> DocumentContent:
    """Parse common Word blocks in document order using only the standard library."""
    source = Path(path)
    assets = Path(asset_dir)
    assets.mkdir(parents=True, exist_ok=True)
    result = DocumentContent(title=source.stem)

    with zipfile.ZipFile(source) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        rels: dict[str, str] = {}
        rel_path = "word/_rels/document.xml.rels"
        if rel_path in archive.namelist():
            rel_root = ET.fromstring(archive.read(rel_path))
            rels = {node.attrib.get("Id", ""): node.attrib.get("Target", "") for node in rel_root}

        body = document.find(f"{W}body")
        if body is None:
            return result

        first_heading = ""
        for child in body:
            if child.tag == f"{W}p":
                text = _text(child)
                style_node = child.find(f"{W}pPr/{W}pStyle")
                style = style_node.attrib.get(f"{W}val", "") if style_node is not None else ""
                level = 0
                digits = "".join(c for c in style if c.isdigit())
                if style.lower().startswith("heading") or style.startswith("标题"):
                    level = int(digits or "1")
                if level and text:
                    result.blocks.append(ContentBlock("heading", text=text, level=level))
                    first_heading = first_heading or text
                elif text:
                    result.blocks.append(ContentBlock("paragraph", text=text))

                for blip in child.iter(f"{A}blip"):
                    rel_id = blip.attrib.get(f"{R}embed", "")
                    target = rels.get(rel_id, "")
                    member = "word/" + target.lstrip("/")
                    if not target or member not in archive.namelist():
                        continue
                    suffix = Path(target).suffix or ".png"
                    image_id = f"image_{len(result.images) + 1}"
                    output = assets / f"{image_id}{suffix}"
                    with archive.open(member) as src, output.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    result.images[image_id] = os.path.abspath(output)
                    result.image_names[image_id] = Path(target).name
                    result.blocks.append(ContentBlock("image", image_id=image_id))

            elif child.tag == f"{W}tbl":
                rows = []
                for row in child.findall(f"{W}tr"):
                    rows.append([_text(cell) for cell in row.findall(f"{W}tc")])
                if rows:
                    result.blocks.append(ContentBlock("table", rows=rows))

        if first_heading:
            result.title = first_heading
    return result

