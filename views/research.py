"""
views/research.py
市場研究頁面：市場掃描 + 個股分析（買賣點評分）+ 技術圖表
"""
from __future__ import annotations
import json
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

from stock_data import get_relative_strength
from stock_chart_widget import render_stock_chart_section
from services.scoring import score_buy, score_sell
from i18n import t, t_cols, get_lang

# 選用的擴充分頁：views/extra_tabs.py 若存在，提供 TABS = [(分頁名稱, render 函式), ...]
# render 函式參數為 (cached_name, cached_price, user_id)。沒有這個檔案時只顯示內建分頁。
try:
    from views.extra_tabs import TABS as _EXTRA_TABS
except ImportError:
    _EXTRA_TABS = []

_BUILTIN_TABS = ["市場掃描", "個股分析", "技術圖表"]

# ══════════════════════════════════════════════════════════
# 模組層級 import + 快取函式
# （不能在函式內用 @st.cache_data 再存進 session_state，
#   Streamlit 無法序列化 cached function 物件，會直接 crash）
# ══════════════════════════════════════════════════════════
from market_radar_data import (
    get_twse_daily, get_tpex_daily,
    get_institutional_investors, get_taiex_index,
    get_limit_up_stocks, get_inst_history,
    _price_date, _chip_date, _is_trading_day,
    _prev_trading_day, clear_all_cache,
)

# 回傳值含已翻譯的提示訊息，所以語言也要是快取 key 的一部分（lang 參數只用來區分快取；注意不能加底線前綴，st.cache_data 會忽略底線開頭的參數）
@st.cache_data(ttl=300)
def _c_twse_cached(d, lang):  return get_twse_daily(d)

@st.cache_data(ttl=300)
def _c_tpex_cached(d, lang):  return get_tpex_daily(d)

@st.cache_data(ttl=1800)
def _c_inst_cached(d, lang):  return get_institutional_investors(d)

@st.cache_data(ttl=60, show_spinner=False)
def _c_taiex_cached(d, lang): return get_taiex_index(d)

@st.cache_data(ttl=1800)
def _c_lu_cached(d, lang):    return get_limit_up_stocks(date=d, market="both")

def _c_twse(d):  return _c_twse_cached(d, get_lang())
def _c_tpex(d):  return _c_tpex_cached(d, get_lang())
def _c_inst(d):  return _c_inst_cached(d, get_lang())
def _c_taiex(d): return _c_taiex_cached(d, get_lang())
def _c_lu(d):    return _c_lu_cached(d, get_lang())


def render(cached_name, cached_price, user_id: str = "admin"):
    # ★ 偵測 ?analyze=2330 參數，自動切換到個股分析 tab
    analyze_code = str(st.query_params.get("analyze", "")).strip().upper()
    
    # 初始化 tab 索引
    if "research_active_tab" not in st.session_state:
        st.session_state.research_active_tab = 0
    
    # 若有 analyze 參數，切換到個股分析 tab (index 1)
    if analyze_code and st.session_state.research_active_tab != 1:
        st.session_state.research_active_tab = 1
    
    tab_names = _BUILTIN_TABS + [name for name, _ in _EXTRA_TABS]
    active_idx = st.session_state.research_active_tab
    if active_idx >= len(tab_names):
        active_idx = st.session_state.research_active_tab = 0
    
    # 手動渲染 tabs（用 button 模擬）
    cols = st.columns(len(tab_names))
    for i, name in enumerate(tab_names):
        with cols[i]:
            if st.button(t(name), key=f"tab_{i}", width="stretch", 
                        type="primary" if i == active_idx else "secondary"):
                st.session_state.research_active_tab = i
                # ★ 切換到非個股分析 tab 時，清除 analyze 參數
                if i != 1 and "analyze" in st.query_params:
                    del st.query_params["analyze"]
                st.rerun()
    
    st.divider()
    
    # 根據 active_idx 渲染對應內容
    if active_idx == 0:
        _render_market_scan_tab()
    elif active_idx == 1:
        _render_stock_analysis_tab(cached_name, cached_price)
    elif active_idx == 2:
        _render_chart_tab(cached_name, cached_price)
    else:
        _EXTRA_TABS[active_idx - len(_BUILTIN_TABS)][1](cached_name, cached_price, user_id)


def _render_stock_analysis_tab(cached_name, cached_price):
    """
    個股分析 Tab:
    1. 搜尋框
    2. 買賣點評分（技術指標）
    3. 籌碼分析（法人 + 大戶）
    """
    from market_radar_data import get_tdcc_shareholding_with_history, calc_holder_analysis
    
    # 讀取 analyze 參數
    ticker = str(st.query_params.get("analyze", "")).strip().upper()
    
    # ═══════════════════════════════════════════════════════════
    # 搜尋框
    # ═══════════════════════════════════════════════════════════
    st.markdown(t("### 🔍 個股深度分析"))
    st.caption(t("輸入股票代號，一次查看技術面評分、籌碼面分析"))
    
    col1, col2 = st.columns([5, 1])
    with col1:
        ticker_input = st.text_input(
            t("輸入股票代號（例如 2330）"),
            key="stock_analysis_ticker",
            value=ticker if ticker else "",
            label_visibility="collapsed",
            placeholder=t("股票代號，例如 2330")
        )
    with col2:
        search_btn = st.button(t("深度分析"), key="stock_analysis_btn", width="stretch", type="primary")
    
    # 當使用者點擊查詢按鈕
    if search_btn and ticker_input.strip():
        st.query_params["analyze"] = ticker_input.strip().upper()
        st.rerun()
    
    ticker = ticker_input.strip().upper()
    
    if not ticker:
        st.info(t("👆 請輸入股票代號開始分析"))
        return
    
    # ═══════════════════════════════════════════════════════════
    # 基本資訊
    # ═══════════════════════════════════════════════════════════
    st.markdown(f"## {ticker}　{cached_name(ticker)}")
    
    # ═══════════════════════════════════════════════════════════
    # 1. 買賣點評分
    # ═══════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown(t("### 📊 買賣點評分"))
    
    with st.spinner(t("計算技術指標...")):
        import yfinance as yf
        fmt = ticker + ".TW" if not ticker.endswith(".TW") else ticker
        raw = yf.download(fmt, period="1y", progress=False, auto_adjust=True)
    
    if not raw.empty:
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw[["Open","High","Low","Close","Volume"]].copy().dropna()
        cur    = float(df["Close"].iloc[-1])
        ema20  = float(df["Close"].ewm(span=20,  adjust=False).mean().iloc[-1])
        ema60  = float(df["Close"].ewm(span=60,  adjust=False).mean().iloc[-1])
        ema120 = float(df["Close"].ewm(span=120, adjust=False).mean().iloc[-1])
        high52 = float(df["Close"].max())
        pfh    = (cur - high52) / high52 * 100
        delta  = df["Close"].diff()
        gain   = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
        loss   = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
        rsi    = float((100 - 100 / (1 + gain / loss.replace(0, float("nan")))).iloc[-1])
        sma20  = df["Close"].rolling(20).mean()
        std20  = df["Close"].rolling(20).std()
        bbu    = float((sma20 + 2*std20).iloc[-1])
        bbl    = float((sma20 - 2*std20).iloc[-1])
        bbpct  = (cur - bbl) / (bbu - bbl) * 100 if bbu != bbl else 50
        rs, _, _ = get_relative_strength(ticker, days=60)
        
        ind = {"cur": cur, "ema20": ema20, "ema60": ema60, "ema120": ema120,
               "rsi": rsi, "pfh": pfh, "bbpct": bbpct, "rs": rs}
        b = score_buy(ind)
        sl = score_sell(ind)
        buy, buy_total, buy_max, buy_grade, buy_color = b["rows"], b["total"], b["max"], b["grade"], b["color"]
        sell, sell_total, sell_max, sell_grade, sell_color = sl["rows"], sl["total"], sl["max"], sl["grade"], sl["color"]
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(t("#### 📈 買點評分"))
            b1, b2 = st.columns([1, 2])
            b1.metric(t("買點分數"), f"{buy_total} / {buy_max}")
            b2.markdown(f"**<span style='color:{buy_color}'>{buy_grade}</span>**", unsafe_allow_html=True)
            df_buy = pd.DataFrame(buy)
            df_buy["得分"] = df_buy.apply(lambda r: f"{r['得分']}/{r['滿分']}", axis=1)
            st.dataframe(t_cols(df_buy[["條件","結果","得分","說明"]]), width="stretch", hide_index=True)
        with c2:
            st.markdown(t("#### 📤 賣點評分"))
            s1, s2 = st.columns([1, 2])
            s1.metric(t("賣點風險分"), f"{sell_total} / {sell_max}")
            s2.markdown(f"**<span style='color:{sell_color}'>{sell_grade}</span>**", unsafe_allow_html=True)
            df_sell = pd.DataFrame(sell)
            df_sell["風險分"] = df_sell.apply(lambda r: f"{r['風險分']}/{r['滿分']}", axis=1)
            st.dataframe(t_cols(df_sell[["條件","觸發","風險分","說明"]]), width="stretch", hide_index=True)
        st.info(t("⚠️ 評分只反映技術面，不代表未來必然漲跌。停損紀律永遠優先於評分。"))
    else:
        st.warning(t("無法取得技術指標資料"))
    
    # ═══════════════════════════════════════════════════════════
    # 2. 籌碼分析（法人 + 大戶）
    # ═══════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown(t("### 💼 籌碼面分析"))
    
    # 閾值設定（直接顯示，不可摺疊）
    st.markdown(t("##### ⚙️ 大戶/散戶閾值設定"))
    col_w, col_r = st.columns(2)
    with col_w:
        st.markdown(t("**大戶持股 ≥ X 張**"))
        whale_thresh = st.radio(
            t("大戶閾值"),
            options=[400, 600, 800, 1000],
            index=0,
            key="whale_thresh_analysis",
            label_visibility="collapsed",
            horizontal=True
        )
    with col_r:
        st.markdown(t("**散戶持股 ＜ Y 張**"))
        retail_thresh = st.radio(
            t("散戶閾值"),
            options=[10, 50, 100, 200, 400],
            index=0,
            key="retail_thresh_analysis",
            label_visibility="collapsed",
            horizontal=True
        )
    st.caption(t("💡 當前設定：大戶 ≥ {whale} 張、散戶 < {retail} 張", whale=whale_thresh, retail=retail_thresh))
    st.markdown("---")
    
    # 載入市場資料
    with st.spinner(t("載入籌碼資料...")):
        market_data, warns = _get_radar_data()
    
    # 查詢大戶籌碼
    has_whale_data = False
    with st.spinner(t("⏳ 抓取 {ticker} 集保資料...", ticker=ticker)):
        try:
            df_t, err = get_tdcc_shareholding_with_history(ticker)
            if err:
                st.error(t("❌ 查詢失敗：{err}", err=err))
                market_data["whale"][ticker] = {"_error": err}
            elif df_t.empty:
                st.warning(t("⚠️ 無 {ticker} 集保資料", ticker=ticker))
                market_data["whale"][ticker] = {"_error": t("無集保資料")}
            else:
                res = calc_holder_analysis(df_t)
                if res:
                    w    = res.get("本週", {})
                    prev = res.get("上週", {})
                    market_data["whale"][ticker] = {
                        "whale_pct":     float(w.get("大戶持股%", 0)),
                        "retail_pct":    float(w.get("散戶持股%", 0)),
                        "whale_cnt":     int(w.get("大戶人數", 0)),
                        "whale_cnt_chg": int(w.get("大戶人數", 0) - prev.get("大戶人數", w.get("大戶人數", 0))),
                        "total_holders": int(w.get("總股東人數", 0)),
                        "whale_chg":     float(res.get("大戶持股變化%", 0)),
                        "holder_chg":    int(res.get("總股東人數變化", 0)),
                        "history":       res.get("history", []),
                        "raw_levels":    res.get("raw_levels", {}),
                        "dist": {
                            "whale":  float(w.get("大戶持股%", 0)),
                            "mid":    float(w.get("中戶持股%", 0)),
                            "retail": float(w.get("散戶持股%", 0)),
                        },
                    }
                    has_whale_data = True
                else:
                    st.error(t("❌ 分析失敗"))
                    market_data["whale"][ticker] = {"_error": t("分析失敗")}
        except Exception as e:
            st.error(t("❌ 查詢失敗：{err}", err=str(e)))
            market_data["whale"][ticker] = {"_error": str(e)}
    
    # 渲染籌碼分析結果（HTML）- 根據是否有資料動態調整高度
    render_height = 1800 if has_whale_data else 100
    _render_html_section_with_height(market_data, "inst-detail", height=render_height, 
                                      whale_thresh=whale_thresh, retail_thresh=retail_thresh)


def _render_chart_tab(cached_name, cached_price):
    """技術圖表 Tab: TradingView 圖表"""
    render_stock_chart_section()
    _chart_raw_ticker = st.session_state.get("chart_ticker_input", "").strip().upper()
    if _chart_raw_ticker:
        st.caption(f"📌 {_chart_raw_ticker}　{cached_name(_chart_raw_ticker)}")



def _get_radar_data() -> tuple[dict, list[str]]:
    """載入市場資料，用 session_state 同日快取，避免三個 tab 各自打 API。"""
    # 注意：快取函式 _c_twse / _c_tpex / _c_inst / _c_taiex / _c_lu
    # 已在模組層級定義，不再存入 session_state（Streamlit 無法序列化它們）
    for k in list(st.session_state.keys()):
            if k.startswith("_radar_data_"):
                del st.session_state[k]

    trade_date = st.session_state.get("radar_trade_date_str", _price_date())

    cache_key = f"_radar_data_{trade_date}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    ep = _price_date()
    ec = _chip_date()

    def _fmt(val):
        try:    return f"{int(float(val)):+,}"
        except: return "—"

    def _prev(d):
        return _prev_trading_day(datetime.strptime(d, "%Y-%m-%d")).strftime("%Y-%m-%d")

    _SECTOR_MERGE = {
        "金融保險業":"金融","金融業":"金融","銀行業":"金融","保險業":"金融",
        "證券業":"金融","期貨業":"金融","票券業":"金融",
        "塑膠工業":"傳產","鋼鐵工業":"傳產","化學工業":"傳產",
        "橡膠工業":"傳產","食品工業":"傳產","紡織纖維":"傳產",
        "玻璃陶瓷":"傳產","造紙工業":"傳產","農業科技":"傳產","水泥工業":"傳產",
        "建材營造業":"營建","建材營造":"營建","電機機械":"營建","居家生活":"營建",
    }
    def _merge(raw):
        s = str(raw).strip() if raw and str(raw).strip() not in ("","nan") else "其他"
        if s in _SECTOR_MERGE: return _SECTOR_MERGE[s]
        for k,v in _SECTOR_MERGE.items():
            if k in s: return v
        return s

    data = {"meta":{"date":ep,"chip_date":ec},
            "index":{}, "sectors":[], "stocks":{},
            "limitup":[], "whale":{}, "inst_detail":{}, "inst_hist":{}}
    warns = []

    # 加權指數
    for d in [ep, _prev(ep)]:
        try:
            tc, tch, err = _c_taiex(d)
            if not err and tc > 0:
                if d != ep: warns.append(t("[指數] 使用 {d}", d=d))
                break
            if err: warns.append(t("[指數] {err}", err=err))
        except Exception as e:
            warns.append(t("[指數] {err}", err=e)); tc=tch=0

    # 個股行情
    frames = []
    for fn, label in [(_c_twse,"上市"),(_c_tpex,"上櫃")]:
        for d in [ep, _prev(ep)]:
            try:
                df, err = fn(d)
                if not err and not df.empty:
                    df["市場"] = label
                    if d != ep: warns.append(t("[{label}] 使用 {d}", label=t(label), d=d))
                    frames.append(df); break
                if err: warns.append(f"[{t(label)}] {err}")
            except Exception as e:
                warns.append(f"[{t(label)}] {e}")
    if frames:
        import pandas as _pd
        df_all = _pd.concat(frames, ignore_index=True)
        for col in ["成交量","收盤","漲跌幅%"]:
            df_all[col] = _pd.to_numeric(df_all.get(col, _pd.Series(dtype=float)).astype(str).str.replace(",",""), errors="coerce").fillna(0)
        if "代號" in df_all.columns:
            df_all = df_all.sort_values("成交量",ascending=False).drop_duplicates("代號",keep="first")
        up = int((df_all["漲跌幅%"]>0).sum())
        dn = int((df_all["漲跌幅%"]<0).sum())
        if "成交金額" in df_all.columns:
            df_all["成交金額"] = _pd.to_numeric(df_all["成交金額"].astype(str).str.replace(",",""),errors="coerce").fillna(0)
            amt = df_all['成交金額'].sum()
            vol_str = f"{amt/1e8:.0f}億" if get_lang() == "zh" else f"NT${amt/1e9:,.1f}B"
        else:
            vol = df_all['成交量'].sum()
            vol_str = f"{vol/1e4:.0f}億張" if get_lang() == "zh" else f"{vol/1e4*100:,.0f}M lots"
        data["index"] = {"taiex":tc,"change":tch,"up":up,"down":dn,"vol":vol_str}

        if "類股" not in df_all.columns:
            df_all["類股"] = "其他"

        # 統一類股名稱（上市/上櫃格式不同）
        _SECTOR_NORM = {
            "上櫃指數股票型基金(ETF)": "ETF",
            "上櫃ETF": "ETF",
            "指數股票型基金(ETF)": "ETF",
            "上市指數股票型基金": "ETF",
            "電腦及週邊設備業": "電腦週邊",
            "電腦及周邊設備業": "電腦週邊",
            "其他電子業": "其他電子類",
            "其他電子類": "其他電子類",
            "通信網路業": "通信網路",
            "光電業": "光電業",
            "半導體業": "半導體業",
            "生技醫療業": "生技醫療",
            "電子零組件業": "電子零組件",
            "電子通路業": "電子通路",
            "資訊服務業": "資訊服務",
            "金融保險業": "金融保險",
        }

        def _norm_sector(s):
            s = str(s).strip()
            if not s or s in ("nan", ""): return "其他"
            return s

        df_all["類股_m"] = df_all["類股"].apply(_norm_sector)

        grp = df_all.groupby("類股_m").agg(pct=("漲跌幅%","mean"),vol=("成交量","sum")).reset_index()

        data["sectors"] = [
            {"name":str(r["類股_m"]),"pct":round(float(r["pct"]),2),"vol":int(r["vol"])}
            for _,r in grp.sort_values("pct",ascending=False).iterrows()
        ]

        for _,row in df_all.iterrows():
            code = str(row.get("代號","")).strip()
            if not code: continue
            data["stocks"][code] = {
                "name":str(row.get("名稱","")),"price":float(row.get("收盤",0)),
                "chg":float(row.get("漲跌幅%",0)),"vol":f"{int(row.get('成交量',0)):,}",
                "sector":str(row.get("類股_m","其他")),
                "f":"—","t":"—","d":"—",
            }

    # 三大法人
    try:
        df_i = None
        for d in [ec, _prev(ec)]:
            df_i2, ei2 = _c_inst(d)
            if not ei2 and not df_i2.empty:
                if d != ec: warns.append(t("[法人] 使用 {d}", d=d))
                df_i = df_i2; break
            if ei2: warns.append(t("[法人] {err}", err=ei2))
        if df_i is not None:
            for _,row in df_i.iterrows():
                code = str(row.get("代號","")).strip()
                if not code: continue
                ir = {"f":_fmt(row.get("外資買賣超(張)",0)),
                      "t":_fmt(row.get("投信買賣超(張)",0)),
                      "d":_fmt(row.get("自營商買賣超(張)",0)),
                      "total":_fmt(row.get("三大法人合計(張)",0))}
                if code in data["stocks"]: data["stocks"][code].update(ir)
                data["inst_detail"][code] = ir
        # inst_hist 前5大
        top5 = sorted(data["inst_detail"].items(),
                      key=lambda x:abs(int(str(x[1].get("f","0")).replace(",","").replace("+","") or 0)),
                      reverse=True)[:5]
        for code,_ in top5:
            try:
                h = get_inst_history(code, days=20)
                if h: data["inst_hist"][code] = h
            except: pass
    except Exception as e:
        warns.append(t("[法人] {err}", err=e))

    # 漲停
    try:
        df_lu, elu = _c_lu(ep)
        if elu: warns.append(t("[漲停] {err}", err=elu))
        elif not df_lu.empty:
            if "成交量" in df_lu.columns: df_lu = df_lu.sort_values("成交量",ascending=False)
            df_lu = df_lu.drop_duplicates(subset="代號",keep="first")
            data["limitup"] = [
                {"code":str(r.get("代號","")),"name":str(r.get("名稱","")),"type":str(r.get("主題類型","其他")),
                 "price":float(r.get("收盤",0) or 0),"pct":float(r.get("漲跌幅%",10) or 10),
                 "locked":bool(r.get("是否一字板",False)),"days":int(r.get("連漲停日",1) or 1),
                 "vol":int(r.get("成交量",0) or 0)}
                for _,r in df_lu.iterrows()
            ]
    except Exception as e:
        warns.append(t("[漲停] {err}", err=e))

    st.session_state[cache_key] = (data, warns)
    return data, warns


def _render_html_section(market_data: dict, section: str):
    """注入資料並渲染 HTML，section 控制哪個 page 預設開啟。"""
    heights = {"sector": 1400, "limitup": 900, "inst": 1000}
    _render_html_section_with_height(market_data, section, heights.get(section, 800))


def _render_html_section_with_height(market_data: dict, section: str, height: int, whale_thresh: int = 400, retail_thresh: int = 10):
    """注入資料並渲染 HTML，可自定義高度和閾值。"""
    html_path = Path(__file__).parent.parent / "market_radar_ui.html"
    if not html_path.exists():
        html_path = Path(__file__).parent / "market_radar_ui.html"
    if not html_path.exists():
        st.error(t("❌ 找不到 market_radar_ui.html"))
        return
    
    try:
        html_code = html_path.read_text(encoding="utf-8")
        
        # ✅ 確保 market_data 可以被序列化
        def clean_data(obj):
            """清理資料，確保可以被 JSON 序列化"""
            if isinstance(obj, dict):
                return {k: clean_data(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_data(item) for item in obj]
            elif isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            else:
                return str(obj)
        
        cleaned_data = clean_data(market_data)
        data_json = json.dumps(cleaned_data, ensure_ascii=False, default=str)
        
        inject = f"""<script>
window.MARKET_DATA = {data_json};
window.RADAR_DEFAULT_PAGE = '{section}';
window.WHALE_THRESH = {whale_thresh};
window.RETAIL_THRESH = {retail_thresh};
window.LANG = '{get_lang()}';
</script>"""
        html_out = html_code.replace("<script>\n'use strict';", inject + "\n<script>\n'use strict';", 1)
        st.iframe(html_out, height=height)
    except Exception as e:
        st.error(t("❌ HTML 渲染失敗：{err}", err=str(e)))
        with st.expander(t("🔍 查看錯誤詳情")):
            import traceback
            st.code(traceback.format_exc())


def _render_sidebar_controls():
    """Sidebar 日期選擇 + 清快取，三個 tab 共用。"""
    with st.sidebar:
        st.markdown("---")
        st.markdown(t("### 📡 類股熱點"))
        default_d = _price_date()
        td = st.date_input(t("查詢日期"), value=datetime.strptime(default_d,"%Y-%m-%d").date(), key="radar_trade_date").strftime("%Y-%m-%d")
        st.session_state["radar_trade_date_str"] = td
        try:
            if not _is_trading_day(datetime.strptime(default_d,"%Y-%m-%d")):
                p = _prev_trading_day(datetime.strptime(default_d,"%Y-%m-%d")).strftime("%Y-%m-%d")
                st.caption(t("🗓️ 休市日，顯示 {date}", date=p))
        except: pass
        if st.button(t("🗑️ 清除快取"), width="stretch", key="radar_clear"):
            clear_all_cache()
            # st.cache_data.clear()
            for k in list(st.session_state.keys()):
                if k.startswith("_radar"): del st.session_state[k]
            st.rerun()


def _render_sector_tab():
    _render_sidebar_controls()
    with st.spinner(t("載入市場資料...")):
        market_data, warns = _get_radar_data()
    if warns:
        with st.sidebar.expander(t("⚠️ {n} 則警告", n=len(warns))):
            for w in warns: st.caption(w)
    idx = market_data.get("index", {})
    if idx:
        c1,c2,c3,c4 = st.columns(4)
        sign = "+" if idx.get("change",0)>=0 else ""
        c1.metric(t("加權指數"), f"{idx.get('taiex',0):,.0f}", f"{sign}{idx.get('change',0):.2f}%")
        c2.metric(t("上漲"), idx.get("up","—"))
        c3.metric(t("下跌"), idx.get("down","—"))
        c4.metric(t("成交量"), idx.get("vol","—"))
    _render_html_section(market_data, "sector")


def _render_market_scan_tab():
    """
    市場掃描 Tab:
    1. 大盤指數
    2. 類股熱度
    3. 今日焦點（radio 切換，用 HTML 渲染）
    """
    _render_sidebar_controls()
    
    with st.spinner(t("載入市場資料...")):
        market_data, warns = _get_radar_data()
    
    if warns:
        with st.sidebar.expander(t("⚠️ {n} 則警告", n=len(warns))):
            for w in warns: st.caption(w)
    
    # ═══════════════════════════════════════════════════════════
    # 1. 大盤指數
    # ═══════════════════════════════════════════════════════════
    idx = market_data.get("index", {})
    if idx:
        c1, c2, c3, c4 = st.columns(4)
        sign = "+" if idx.get("change", 0) >= 0 else ""
        c1.metric(t("加權指數"), f"{idx.get('taiex', 0):,.0f}", f"{sign}{idx.get('change', 0):.2f}%")
        c2.metric(t("上漲"), idx.get("up", "—"))
        c3.metric(t("下跌"), idx.get("down", "—"))
        c4.metric(t("成交量"), idx.get("vol", "—"))
    
    # ═══════════════════════════════════════════════════════════
    # 2. 類股熱度
    # ═══════════════════════════════════════════════════════════
    _render_html_section_with_height(market_data, "sector", height=1200)
    
    st.markdown("---")
    
    # ═══════════════════════════════════════════════════════════
    # 3. 今日焦點（radio 切換，用 HTML 渲染）
    # ═══════════════════════════════════════════════════════════
    st.markdown(t("### 📊 今日焦點"))
    
    focus_type = st.radio(
        t("選擇焦點類型"),
        options=[t("漲停股"), t("法人買賣超")],
        horizontal=True,
        label_visibility="collapsed",
        key=f"market_scan_focus_{get_lang()}"   # 換語言時選項文字會變，換 key 避免舊值對不上
    )
    
    if focus_type == t("漲停股"):
        # 渲染漲停分析（HTML）
        _render_html_section_with_height(market_data, "limitup", height=1500)
    elif focus_type == t("法人買賣超"):
        # 渲染法人買賣超表格（HTML）
        _render_html_section_with_height(market_data, "inst-ranking", height=1200)