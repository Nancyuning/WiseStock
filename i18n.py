"""
i18n.py — 介面雙語（English / 繁體中文）

用法
  t("持股檔數")                 → 英文模式回傳 "Holdings"，中文模式回傳原文
  t("共 {n} 筆", n=3)           → 帶變數的字串用 str.format 具名參數

  中文原文本身就是 key；英文翻譯放在 locales/en_*.py 的 EN dict（每個模組一個檔案，
  載入時自動合併）。找不到翻譯時回傳原文，所以漏翻只會顯示中文、不會壞掉。

  資料庫裡存的值（買入/賣出、買賣理由、大盤位階…）一律維持中文，只在顯示時翻譯。
  股票名稱等來自證交所的資料不翻譯。
"""
from __future__ import annotations

import importlib
import pkgutil

import streamlit as st

import locales

LANGS = {"en": "English", "zh": "繁體中文"}
DEFAULT_LANG = "en"


def _load_en() -> dict[str, str]:
    merged: dict[str, str] = {}
    for mod in pkgutil.iter_modules(locales.__path__):
        if mod.name.startswith("en_"):
            merged.update(importlib.import_module(f"locales.{mod.name}").EN)
    return merged


EN = _load_en()


def get_lang() -> str:
    try:
        lang = st.session_state.get("lang", DEFAULT_LANG)
    except Exception:  # 不在 Streamlit 執行環境（例如單元測試）
        lang = DEFAULT_LANG
    return lang if lang in LANGS else DEFAULT_LANG


def t(text: str, **kwargs) -> str:
    out = text if get_lang() == "zh" else EN.get(text, text)
    return out.format(**kwargs) if kwargs else out


def t_cols(df):
    """DataFrame 顯示前翻譯欄位名稱（內部仍用中文欄名運算）。"""
    return df.rename(columns={c: t(c) for c in df.columns if isinstance(c, str)})


def render_language_picker(container=None) -> None:
    """語言切換下拉選單；選擇會存在 session_state["lang"]。"""
    target = container or st.sidebar
    current = get_lang()
    choice = target.selectbox(
        "🌐 Language / 語言",
        options=list(LANGS),
        index=list(LANGS).index(current),
        format_func=LANGS.get,
        key="_lang_picker",
    )
    if choice != current:
        st.session_state["lang"] = choice
        st.rerun()
