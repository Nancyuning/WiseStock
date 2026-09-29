"""
market_radar_ui.html 的雙語測試：
  - HTML 內嵌的 SECTOR_EN 必須跟 locales/en_sectors.py 完全一致
  - 每個 T('字面字串') 都要有英文翻譯，翻譯的 {變數} 要跟原文一致、不能含中文
  - views/research.py 注入 window.* 用的錨點 "<script>\\n'use strict';" 必須存在
"""
import json
import re
from pathlib import Path

from locales.en_sectors import EN as SECTORS_EN

HTML = (Path(__file__).resolve().parent.parent / "market_radar_ui.html").read_text(encoding="utf-8")
CJK = re.compile(r"[一-鿿]")


def _js_ui_dict() -> dict:
    return json.loads(re.search(r"const EN = (\{.*?\});", HTML, re.S).group(1))


def _js_sector_dict() -> dict:
    return json.loads(re.search(r"/\*SECTOR_EN_START\*/(\{.*?\})/\*SECTOR_EN_END\*/", HTML, re.S).group(1))


def _placeholders(s: str) -> set:
    return set(re.findall(r"\{(\w+)\}", s))


def test_html_sector_map_matches_locale_file():
    """HTML 內建的類股對照 = en_sectors.py 的全部類股，翻譯與 Python 端（合併後的 i18n.EN）一致。
    （共用詞例如「其他」放在 en_common.py，所以比對合併後的結果。）"""
    import i18n

    html_map = _js_sector_dict()
    assert set(SECTORS_EN) <= set(html_map), f"HTML 缺少類股：{sorted(set(SECTORS_EN) - set(html_map))}"
    mismatched = {k: (v, i18n.EN.get(k)) for k, v in html_map.items() if i18n.EN.get(k) != v}
    assert not mismatched, f"HTML 與 locales 翻譯不一致：{mismatched}"


def test_every_T_call_in_html_has_translation():
    ui = _js_ui_dict()
    used = set(re.findall(r"\bT\('([^']+)'", HTML))
    missing = sorted(used - set(ui))
    assert not missing, f"HTML 裡 T() 用到但沒有翻譯：{missing}"


def test_html_translations_are_english_and_keep_placeholders():
    for zh, en in {**_js_ui_dict(), **_js_sector_dict()}.items():
        assert not CJK.search(en), f"翻譯還有中文：{zh!r} → {en!r}"
        assert _placeholders(zh) == _placeholders(en), f"佔位不一致：{zh!r} → {en!r}"


def test_injection_anchor_used_by_research_view_still_exists():
    assert HTML.count("<script>\n'use strict';") == 1
    assert "window.LANG" in HTML
