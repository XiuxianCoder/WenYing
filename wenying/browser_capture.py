from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import webview


class CaptureApi:
    def __init__(self, output: Path, source_url: str) -> None:
        self.output = output
        self.source_url = source_url

    def save_capture(self, payload: dict) -> dict:
        payload["sourceUrl"] = self.source_url
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(self.output)}


COLLECT_SCRIPT = r"""
(function () {
  if (document.getElementById('wenying-capture-button')) return;
  const button = document.createElement('button');
  button.id = 'wenying-capture-button';
  button.textContent = '采集此模板';
  Object.assign(button.style, {
    position: 'fixed', right: '22px', bottom: '24px', zIndex: '2147483647',
    border: '0', borderRadius: '6px', padding: '12px 20px', cursor: 'pointer',
    background: '#365b52', color: '#fff', fontSize: '15px', fontWeight: '600',
    boxShadow: '0 8px 28px rgba(0,0,0,.24)'
  });
  button.onclick = async () => {
    button.textContent = '正在采集…'; button.disabled = true;
    const root = document.querySelector('#js_content') || document.querySelector('article') || document.body;
    const nodes = Array.from(root.querySelectorAll('*')).slice(0, 2400);
    const styleKeys = ['display','position','width','max-width','margin','padding','color','background-color',
      'background-image','font-family','font-size','font-weight','line-height','letter-spacing','text-align',
      'border','border-radius','box-shadow','animation-name','animation-duration','transform','opacity'];
    const styles = nodes.map((el, index) => {
      const cs = getComputedStyle(el); const picked = {};
      styleKeys.forEach(k => { const v = cs.getPropertyValue(k); if (v) picked[k] = v; });
      return {index, tag: el.tagName.toLowerCase(), id: el.id || '', className: String(el.className || '').slice(0,200),
        text: (el.innerText || '').trim().slice(0,240), style: picked};
    });
    const assets = Array.from(root.querySelectorAll('img,video,source,svg')).map(el => ({
      tag: el.tagName.toLowerCase(), src: el.getAttribute('data-src') || el.getAttribute('data-backsrc') || el.currentSrc || el.src || '',
      type: el.getAttribute('type') || '', width: el.getBoundingClientRect().width,
      height: el.getBoundingClientRect().height, outerHTML: el.outerHTML.slice(0,5000)
    }));
    const animations = Array.from(document.getAnimations()).map(a => ({
      id: a.id || '', playState: a.playState, currentTime: a.currentTime,
      timing: a.effect && a.effect.getTiming ? a.effect.getTiming() : {}
    }));
    const payload = {title: document.title, url: location.href, viewport: {width: innerWidth, height: innerHeight},
      html: root.outerHTML.slice(0,700000), styles, assets, animations};
    try {
      await window.pywebview.api.save_capture(payload);
      button.textContent = '采集完成 ✓'; button.style.background = '#a44b38';
    } catch (e) {
      button.textContent = '采集失败，重试'; button.disabled = false;
    }
  };
  document.body.appendChild(button);
})();
"""


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: browser_capture.py URL OUTPUT_JSON")
    url, output = sys.argv[1], Path(sys.argv[2])
    api = CaptureApi(output, url)
    window = webview.create_window("文映 · 模板浏览器", url=url, js_api=api, width=1180, height=820, min_size=(900, 650))

    def inject() -> None:
        def delayed() -> None:
            # Let lazy-loaded WeChat assets settle before adding the control.
            import time
            time.sleep(2)
            try:
                window.evaluate_js(COLLECT_SCRIPT)
            except Exception:
                pass
        threading.Thread(target=delayed, daemon=True).start()

    window.events.loaded += inject
    webview.start(gui="edgechromium", debug=False, private_mode=False)


if __name__ == "__main__":
    main()

