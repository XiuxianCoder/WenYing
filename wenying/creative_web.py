from __future__ import annotations

import hashlib
from typing import Any


def _variant(style: str, seed: int) -> int:
    digest = hashlib.sha256(f"{style}:{seed}".encode("utf-8")).digest()
    return digest[0] % 4


def enhance_ai_original(
    body: str, title: str, template: dict[str, Any], width: int
) -> tuple[str, str]:
    """Add a browser-only visual layer without changing article content."""
    if template.get("sourceType") != "ai_original":
        return body, ""
    tokens = template.get("styleTokens", {})
    primary = str(tokens.get("primaryColor", "#315d58"))
    accent = str(tokens.get("accentColor", "#c99b62"))
    paper = str(tokens.get("paperColor", "#fffdf8"))
    style_name = str(template.get("originalStyle", "AI 原创"))
    seed = int(template.get("creativeSeed", 0) or 0)
    variant = _variant(style_name, seed)

    ornaments = (
        '<circle cx="32" cy="32" r="18"/><path d="M62 32h150"/>',
        '<path d="M8 44C58 4 110 76 166 30S258 18 300 46"/><circle cx="154" cy="31" r="7"/>',
        '<path d="M18 60L70 12l52 48 52-48 52 48"/><path d="M42 72h210"/>',
        '<circle cx="38" cy="38" r="25"/><circle cx="82" cy="38" r="12"/><path d="M112 38h166"/>',
    )[variant]
    hero = f'''
<section class="wy-web-hero" aria-hidden="true">
  <div class="wy-orb wy-orb-a"></div><div class="wy-orb wy-orb-b"></div>
  <svg class="wy-hero-svg" viewBox="0 0 310 82" fill="none" stroke="currentColor" stroke-width="2">{ornaments}</svg>
</section>'''
    footer = '''
<section class="wy-web-ending" aria-hidden="true">
  <span></span><i>◆</i><span></span>
</section>'''
    css = f'''
@keyframes wy-rise{{from{{opacity:0;transform:translateY(18px)}}to{{opacity:1;transform:none}}}}
@keyframes wy-float{{0%,100%{{transform:translate3d(0,0,0) scale(1)}}50%{{transform:translate3d(12px,-10px,0) scale(1.08)}}}}
@keyframes wy-draw{{from{{stroke-dashoffset:520}}to{{stroke-dashoffset:0}}}}
.wy-free-page{{position:relative;isolation:isolate;overflow:hidden;box-shadow:0 24px 80px rgba(32,39,37,.14);border:1px solid {accent}33}}
.wy-free-page>section,.wy-free-page>h1,.wy-free-page>h2,.wy-free-page>p,.wy-free-page>table{{animation:wy-rise .68s ease both}}
.wy-web-hero{{position:relative;min-height:150px;margin:0 -20px 34px;overflow:hidden;background:linear-gradient(135deg,{primary} 0%,{accent} 100%);color:white}}
.wy-hero-svg{{position:absolute;width:min(70%,430px);right:5%;top:26px;color:rgba(255,255,255,.72);stroke-dasharray:520;animation:wy-draw 2.2s ease-out both}}
.wy-orb{{position:absolute;border-radius:50%;filter:blur(2px);animation:wy-float 7s ease-in-out infinite}}
.wy-orb-a{{width:120px;height:120px;left:-32px;top:-40px;background:rgba(255,255,255,.14)}}
.wy-orb-b{{width:78px;height:78px;right:8%;bottom:-34px;background:{paper}33;animation-delay:-2.5s}}
.wy-web-ending{{display:flex!important;align-items:center;gap:14px;margin:46px 0 4px;color:{accent};animation:wy-rise .8s ease both}}
.wy-web-ending span{{height:1px;flex:1;background:linear-gradient(90deg,transparent,{accent},transparent)}}
.wy-web-ending i{{font-style:normal;font-size:12px;animation:wy-float 4s ease-in-out infinite}}
@media(max-width:520px){{.wy-web-hero{{min-height:124px}}}}
@media(prefers-reduced-motion:reduce){{.wy-free-page *{{animation:none!important}}}}
'''
    return hero + body + footer, css
