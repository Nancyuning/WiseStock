"""
i18n 測試：所有 t("字面字串") 都要有英文翻譯，且翻譯的 {變數} 要跟原文一致。
"""
import ast
import re
import string
from pathlib import Path

import pytest

import i18n

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "tests", "locales", "__pycache__", ".git"}


def _t_literals():
    """掃描專案所有 .py，找出 t("...") 的字面字串參數。"""
    found = []
    for path in ROOT.rglob("*.py"):
        if SKIP_DIRS & set(path.relative_to(ROOT).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                found.append((f"{path.relative_to(ROOT)}:{node.lineno}", node.args[0].value))
    return found


def _fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def test_every_t_call_has_english_translation():
    missing = [f"{loc}  {text!r}" for loc, text in _t_literals() if text not in i18n.EN]
    assert not missing, "缺少英文翻譯：\n" + "\n".join(missing)


def test_translations_keep_the_same_placeholders():
    bad = [k for k, v in i18n.EN.items() if _fields(k) != _fields(v)]
    assert not bad, "翻譯的 {變數} 跟原文不一致：\n" + "\n".join(bad)


def test_english_translations_contain_no_chinese():
    cjk = re.compile(r"[一-鿿]")
    bad = [k for k, v in i18n.EN.items() if cjk.search(v)]
    assert not bad, "英文翻譯裡還有中文：\n" + "\n".join(bad)


@pytest.mark.parametrize("lang, expected", [("en", "Buy"), ("zh", "買入")])
def test_t_switches_language(monkeypatch, lang, expected):
    monkeypatch.setattr(i18n, "get_lang", lambda: lang)
    assert i18n.t("買入") == expected


def test_t_falls_back_to_original_and_formats(monkeypatch):
    monkeypatch.setattr(i18n, "get_lang", lambda: "en")
    assert i18n.t("沒有翻譯的字串 {n}", n=3) == "沒有翻譯的字串 3"


def test_no_key_is_defined_in_two_locale_files():
    """同一個原文只能在一個 locale 檔出現，避免不同頁面翻成不同英文。共用詞放 en_common.py。"""
    import importlib
    import pkgutil
    from collections import defaultdict

    import locales

    owners = defaultdict(list)
    for mod in pkgutil.iter_modules(locales.__path__):
        if mod.name.startswith("en_"):
            for key in importlib.import_module(f"locales.{mod.name}").EN:
                owners[key].append(mod.name)
    dups = {k: v for k, v in owners.items() if len(v) > 1}
    assert not dups, "重複定義的翻譯 key：\n" + "\n".join(f"{k!r}: {v}" for k, v in dups.items())
