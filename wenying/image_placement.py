from __future__ import annotations

import hashlib

import re
import shutil
from pathlib import Path

from .models import ContentBlock, DocumentContent


def _normalized(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", value, flags=re.UNICODE).lower()


def add_external_images(document: DocumentContent, paths: list[str], asset_dir: str) -> list[str]:
    """Add external images and place filename matches; return unmatched image ids."""
    assets = Path(asset_dir)
    assets.mkdir(parents=True, exist_ok=True)
    unmatched: list[str] = []
    existing_hashes = {hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in document.images.values() if Path(path).is_file()}
    for source_name in paths:
        source = Path(source_name)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest in existing_hashes:
            continue
        existing_hashes.add(digest)
        image_id = f"external_{len(document.images) + 1}"
        target = assets / f"{image_id}{source.suffix.lower()}"
        shutil.copy2(source, target)
        document.images[image_id] = str(target.resolve())
        document.image_names[image_id] = source.name
        stem = _normalized(source.stem)
        match_index = -1
        if stem:
            for index, block in enumerate(document.blocks):
                block_text = _normalized(block.text)
                if stem in block_text or (len(stem) >= 4 and block_text and block_text in stem):
                    match_index = index
                    break
        if match_index >= 0:
            document.blocks.insert(match_index + 1, ContentBlock("image", image_id=image_id))
        else:
            unmatched.append(image_id)
    return unmatched


def apply_ai_placements(document: DocumentContent, placements: list[dict]) -> None:
    valid = []
    for item in placements:
        image_id = str(item.get("imageId", ""))
        if image_id not in document.images:
            continue
        try:
            after = max(-1, min(int(item.get("afterBlockIndex", -1)), len(document.blocks) - 1))
        except (TypeError, ValueError):
            continue
        valid.append((after, image_id, str(item.get("caption", ""))))
    for after, image_id, caption in sorted(valid, reverse=True):
        if any(block.type == "image" and block.image_id == image_id for block in document.blocks):
            continue
        document.blocks.insert(after + 1, ContentBlock("image", text=caption, image_id=image_id))

def place_images_evenly(document: DocumentContent, image_ids: list[str]) -> None:
    """Deterministic fallback: spread unresolved images through readable content."""
    pending = [image_id for image_id in image_ids if image_id in document.images and not any(
        block.type == "image" and block.image_id == image_id for block in document.blocks
    )]
    if not pending:
        return
    candidates = [index for index, block in enumerate(document.blocks)
                  if block.type in {"paragraph", "heading", "quote"} and block.text.strip()
                  and not (block.type == "heading" and block.text.strip() == document.title.strip())]
    if not candidates:
        candidates = [len(document.blocks) - 1]
    placements = []
    for position, image_id in enumerate(pending, start=1):
        candidate_index = min(len(candidates) - 1, max(0, round(position * (len(candidates) - 1) / (len(pending) + 1))))
        placements.append((candidates[candidate_index], image_id))
    for after, image_id in sorted(placements, reverse=True):
        document.blocks.insert(after + 1, ContentBlock("image", image_id=image_id))
