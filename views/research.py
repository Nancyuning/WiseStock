"""
views/research.py
市場研究頁面：技術圖表 + 買賣點評分 + 水位計算機 + 類股熱點
"""
from __future__ import annotations
import json
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

from stock_data import get_relative_strength
from database import get_open_positions
from formatting import fmt_pct, fmt_price
from stock_chart_widget import render_stock_chart_section
from services.scoring import score_buy, score_sell, classify_rebalance
from strategy import STRATEGY

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

@st.cache_data(ttl=300)
def _c_twse(d):  return get_twse_daily(d)

@st.cache_data(ttl=300)
def _c_tpex(d):  return get_tpex_daily(d)

@st.cache_data(ttl=1800)
def _c_inst(d):  return get_institutional_investors(d)

@st.cache_data(ttl=60, show_spinner=False)
def _c_taiex(d): return get_taiex_index(d)

@st.cache_data(ttl=1800)
def _c_lu(d):    return get_limit_up_stocks(date=d, market="both")


def render(cached_name, cached_price, user_id: str = "admin"):
    # ★ 偵測 ?analyze=2330 參數，自動切換到個股分析 tab
    analyze_code = str(st.query_params.get("analyze", "")).strip().upper()
    
    # 初始化 tab 索引
    if "research_active_tab" not in st.session_state:
        st.session_state.research_active_tab = 0
    
    # 若有 analyze 參數，切換到個股分析 tab (index 1)
    if analyze_code and st.session_state.research_active_tab != 1:
        st.session_state.research_active_tab = 1
    
    tab_names = ["市場掃描", "個股分析", "技術圖表", "水位計算機"]
    active_idx = st.session_state.research_active_tab
    
    # 手動渲染 tabs（用 button 模擬）
    cols = st.columns(4)
    for i, name in enumerate(tab_names):
        with cols[i]:
            if st.button(name, key=f"tab_{i}", width="stretch", 
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
    elif active_idx == 3:
        _render_water_level(cached_name, cached_price, user_id)


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
    st.markdown("### 🔍 個股深度分析")
    st.caption("輸入股票代號，一次查看技術面評分、籌碼面分析")
    
    col1, col2 = st.columns([5, 1])
    with col1:
        ticker_input = st.text_input(
            "輸入股票代號（例如 2330）",
            key="stock_analysis_ticker",
            value=ticker if ticker else "",
            label_visibility="collapsed",
            placeholder="股票代號，例如 2330"
        )
    with col2:
        search_btn = st.button("深度分析", key="stock_analysis_btn", width="stretch", type="primary")
    
    # 當使用者點擊查詢按鈕
    if search_btn and ticker_input.strip():
        st.query_params["analyze"] = ticker_input.strip().upper()
        st.rerun()
    
    ticker = ticker_input.strip().upper()
    
    if not ticker:
        st.info("👆 請輸入股票代號開始分析")
        return
    
    # ═══════════════════════════════════════════════════════════
    # 基本資訊
    # ═══════════════════════════════════════════════════════════
    st.markdown(f"## {ticker}　{cached_name(ticker)}")
    
    # ═══════════════════════════════════════════════════════════
    # 1. 買賣點評分
    # ═══════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 📊 買賣點評分")
    
    with st.spinner("計算技術指標..."):
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
            st.markdown("#### 📈 買點評分")
            b1, b2 = st.columns([1, 2])
            b1.metric("買點分數", f"{buy_total} / {buy_max}")
            b2.markdown(f"**<span style='color:{buy_color}'>{buy_grade}</span>**", unsafe_allow_html=True)
            df_buy = pd.DataFrame(buy)
            df_buy["得分"] = df_buy.apply(lambda r: f"{r['得分']}/{r['滿分']}", axis=1)
            st.dataframe(df_buy[["條件","結果","得分","說明"]], width="stretch", hide_index=True)
        with c2:
            st.markdown("#### 📤 賣點評分")
            s1, s2 = st.columns([1, 2])
            s1.metric("賣點風險分", f"{sell_total} / {sell_max}")
            s2.markdown(f"**<span style='color:{sell_color}'>{sell_grade}</span>**", unsafe_allow_html=True)
            df_sell = pd.DataFrame(sell)
            df_sell["風險分"] = df_sell.apply(lambda r: f"{r['風險分']}/{r['滿分']}", axis=1)
            st.dataframe(df_sell[["條件","觸發","風險分","說明"]], width="stretch", hide_index=True)
        st.info("⚠️ 評分只反映技術面，不代表未來必然漲跌。停損紀律永遠優先於評分。")
    else:
        st.warning("無法取得技術指標資料")
    
    # ═══════════════════════════════════════════════════════════
    # 2. 籌碼分析（法人 + 大戶）
    # ═══════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 💼 籌碼面分析")
    
    # 閾值設定（直接顯示，不可摺疊）
    st.markdown("##### ⚙️ 大戶/散戶閾值設定")
    col_w, col_r = st.columns(2)
    with col_w:
        st.markdown("**大戶持股 ≥ X 張**")
        whale_thresh = st.radio(
            "大戶閾值",
            options=[400, 600, 800, 1000],
            index=0,
            key="whale_thresh_analysis",
            label_visibility="collapsed",
            horizontal=True
        )
    with col_r:
        st.markdown("**散戶持股 ＜ Y 張**")
        retail_thresh = st.radio(
            "散戶閾值",
            options=[10, 50, 100, 200, 400],
            index=0,
            key="retail_thresh_analysis",
            label_visibility="collapsed",
            horizontal=True
        )
    st.caption(f"💡 當前設定：大戶 ≥ {whale_thresh} 張、散戶 < {retail_thresh} 張")
    st.markdown("---")
    
    # 載入市場資料
    with st.spinner("載入籌碼資料..."):
        market_data, warns = _get_radar_data()
    
    # 查詢大戶籌碼
    has_whale_data = False
    with st.spinner(f"⏳ 抓取 {ticker} 集保資料..."):
        try:
            df_t, err = get_tdcc_shareholding_with_history(ticker)
            if err:
                st.error(f"❌ 查詢失敗：{err}")
                market_data["whale"][ticker] = {"_error": err}
            elif df_t.empty:
                st.warning(f"⚠️ 無 {ticker} 集保資料")
                market_data["whale"][ticker] = {"_error": "無集保資料"}
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
                    st.error("❌ 分析失敗")
                    market_data["whale"][ticker] = {"_error": "分析失敗"}
        except Exception as e:
            st.error(f"❌ 查詢失敗：{str(e)}")
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



def _render_water_level(cached_name, cached_price, user_id: str = "admin"):
    from stock_data import get_market_risk_score, check_stock_signals, stress_test

    st.header("💰 水位計算機")
    st.caption("智慧計算建議持股水位 · 低位加碼 · 高位保護 · 汰弱留強")
    st.caption("⚠️ 以下「建議」皆為程式依技術指標自動計算的結果，僅供個人研究參考，不構成投資建議。")

    @st.cache_data(ttl=1800)
    def _cached_risk():
        return get_market_risk_score()

    with st.spinner("計算市場震盪機率..."):
        risk = _cached_risk()

    osc_prob        = risk["oscillation_prob"]
    osc_days        = risk["oscillation_days"]
    suggested_ratio = risk["suggested_ratio"]
    bd              = risk["breakdown"]

    col_gauge, col_meta = st.columns([1, 2])
    with col_gauge:
        gauge  = STRATEGY["market_risk"]["gauge"]
        gc     = "#ef5350" if osc_prob >= gauge["high"] else "#f39c12" if osc_prob >= gauge["mid"] else "#26a69a"
        rlabel = "高風險"  if osc_prob >= gauge["high"] else "中風險"  if osc_prob >= gauge["mid"] else "低風險"
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);
            border:2px solid {gc};border-radius:16px;padding:24px 16px;text-align:center;box-shadow:0 0 20px {gc}44;">
            <div style="font-size:13px;color:#aaa;margin-bottom:4px;">震盪機率</div>
            <div style="font-size:52px;font-weight:900;color:{gc};line-height:1;">{osc_prob:.0f}<span style="font-size:24px">%</span></div>
            <div style="font-size:14px;color:{gc};margin-top:6px;font-weight:bold;">{rlabel}</div>
            <hr style="border-color:#333;margin:12px 0;">
            <div style="display:flex;justify-content:space-around;">
                <div><div style="font-size:11px;color:#888;">震盪倒數</div>
                     <div style="font-size:22px;font-weight:bold;color:#fff;">{osc_days}<span style="font-size:12px;color:#888;"> 日</span></div></div>
                <div><div style="font-size:11px;color:#888;">建議水位</div>
                     <div style="font-size:22px;font-weight:bold;color:#FFD700;">{suggested_ratio:.0f}<span style="font-size:12px;color:#888;"> %</span></div></div>
            </div>
        </div>""", unsafe_allow_html=True)

    with col_meta:
        st.markdown("##### 📡 指標明細")
        if bd["rsi_val"] is not None:
            w = STRATEGY["market_risk"]["weights"]
            st.dataframe(pd.DataFrame([
                {"指標":"0050 RSI(14)","數值":f"{bd['rsi_val']:.1f}","風險貢獻":f"{bd['rsi_score']:.0f}/100","權重":f"{w['rsi']:.0%}"},
                {"指標":"季線乖離率","數值":f"{bd['bias_val']:+.1f}%","風險貢獻":f"{bd['bias_score']:.0f}/100","權重":f"{w['bias']:.0%}"},
                {"指標":"20日年化波動率","數值":f"{bd['vol_val']:.1f}%","風險貢獻":f"{bd['vol_score']:.0f}/100","權重":f"{w['vol']:.0%}"},
                {"指標":"VIX","數值":f"{bd['vix_val']:.1f}","風險貢獻":f"{bd['vix_score']:.0f}/100","權重":f"{w['vix']:.0%}"},
            ]), width="stretch", hide_index=True)
        if bd["market_label"]: st.info(f"大盤現況：**{bd['market_label']}**")
        if risk["error"]:      st.warning(f"部分指標抓取失敗：{risk['error']}")

    st.divider()
    st.subheader("② 輸入你的資金狀況")
    positions = get_open_positions(user_id)
    auto_mv   = 0
    pos_data  = []
    for pos in positions:
        (ticker, net_shares, total_cost, total_buy_shares, _, _, _, target_price, stop_loss, _) = pos
        avg_cost = total_cost / total_buy_shares if total_buy_shares > 0 else 0
        cur      = cached_price(ticker)
        mval     = (cur * net_shares) if cur else (avg_cost * net_shares)
        auto_mv += mval
        pos_data.append({"ticker":ticker,"net_shares":net_shares,"avg_cost":avg_cost,"cur":cur,
                          "market_val":mval,"stop_loss":stop_loss,"target_price":target_price})

    col_i1, col_i2 = st.columns(2)
    with col_i1:
        stock_val = st.number_input("目前持股市值（元）", min_value=0, step=1000, value=int(auto_mv),
                                     help="已自動從持倉總覽計算，也可手動修改")
        if auto_mv > 0: st.caption(f"📌 系統自動計算：${auto_mv:,.0f}")
    with col_i2:
        cash_val = st.number_input("目前可動用閒錢（元）", min_value=0, step=10000, value=0)

    total_asset = stock_val + cash_val
    if total_asset <= 0:
        st.warning("請輸入持股市值或閒錢金額")
        return
    current_ratio = (stock_val / total_asset * 100) if total_asset > 0 else 0

    st.divider()
    st.subheader("③ 水位分析")
    suggested_val = total_asset * (suggested_ratio / 100)
    diff_val      = suggested_val - stock_val
    diff_ratio    = current_ratio - suggested_ratio

    m1,m2,m3,m4 = st.columns(4)
    m1.metric("總資產", f"${total_asset:,.0f}")
    m2.metric("目前持股", f"${stock_val:,.0f}", delta=f"現況 {current_ratio:.1f}%", delta_color="off")
    m3.metric("建議持股", f"${suggested_val:,.0f}", delta=f"目標 {suggested_ratio:.0f}%", delta_color="off")
    if diff_val > 0:
        m4.metric("水位差距", f"可加碼 ${diff_val:,.0f}", delta=f"低配 {abs(diff_ratio):.1f}%")
        st.success(f"✅ 目前水位 **{current_ratio:.1f}%** 低於建議 **{suggested_ratio:.0f}%**，尚有 **${diff_val:,.0f}** 加碼空間")
    else:
        m4.metric("水位差距", f"超配 ${abs(diff_val):,.0f}", delta=f"超配 {abs(diff_ratio):.1f}%", delta_color="inverse")
        st.error(f"⚠️ 目前水位 **{current_ratio:.1f}%** 高於建議 **{suggested_ratio:.0f}%**，需減碼約 **${abs(diff_val):,.0f}**")

    st.divider()
    st.subheader("④ 持股技術診斷儀表板")
    if not positions:
        st.info("目前無持倉")
        return

    with st.spinner("診斷中..."):
        sig_results = []
        for p in pos_data:
            sig = check_stock_signals(p["ticker"], avg_cost=p["avg_cost"])
            sig.update({"ticker":p["ticker"],"name":cached_name(p["ticker"]),
                         "net_shares":p["net_shares"],"market_val":p["market_val"],
                         "pnl_pct":((p["cur"]/p["avg_cost"]-1)*100 if p["cur"] and p["avg_cost"] else None)})
            sig_results.append(sig)

    for sig in sig_results:
        raw      = sig.get("raw", {})
        pnl_pct  = sig.get("pnl_pct")
        pnl_color = "#ef5350" if (pnl_pct or 0) >= 0 else "#26a69a"
        slope_up = raw.get("ma20_slope_up")
        atr_stop = raw.get("atr_trail_stop")
        rs5,rs10,rs60 = sig.get("rs_5"),sig.get("rs_10"),sig.get("rs_60")
        k,d,r = sig.get("k_val"),sig.get("d_val"),sig.get("rsi_val")
        obv   = sig.get("obv_slope")
        s_html = ""
        if slope_up is not None:
            s_html = f"<span style='color:{'#26a69a' if slope_up else '#ef5350'};font-size:11px;font-weight:600'>EMA20 {'↑' if slope_up else '↓'}</span>"
        with st.container(border=True):
            r1c0,r1c1,r1c2,r1c3 = st.columns([3,2,2,2])
            r1c0.markdown(f"<div style='font-size:16px;font-weight:700'>{sig['ticker']}　{sig['name']}</div>"
                          f"<div style='font-size:22px;font-weight:800;color:{pnl_color}'>{fmt_pct(pnl_pct)}</div>",
                          unsafe_allow_html=True)
            for col, label, key in [(r1c1,"動能狀態","momentum"),(r1c2,"進場時機","timing"),(r1c3,"量價配合","volume")]:
                col.markdown(f"<div style='font-size:11px;color:#888'>{label}</div>"
                             f"<div style='font-size:20px'>{sig[f'{key}_emoji']} "
                             f"<span style='font-size:14px;font-weight:600'>{sig[f'{key}_label']}</span></div>",
                             unsafe_allow_html=True)
            r2c0,r2c1,r2c2,r2c3 = st.columns([3,2,2,2])
            dp = [f"市值 ${sig['market_val']:,.0f}"]
            if atr_stop is not None: dp.append(f"ATR停利 {atr_stop:.2f}")
            r2c0.markdown(f"<div style='font-size:11px;color:#aaa'>{'　'.join(dp)}</div><div>{s_html}</div>", unsafe_allow_html=True)
            rs_p = []
            if rs5  is not None: rs_p.append(f"5d {rs5:+.1f}%")
            if rs10 is not None: rs_p.append(f"10d {rs10:+.1f}%")
            if rs60 is not None: rs_p.append(f"60d {rs60:+.1f}%")
            r2c1.caption("　".join(rs_p) if rs_p else "資料不足")
            r2c2.caption(f"K {k:.0f}　D {d:.0f}　RSI {r:.0f}") if all(v is not None for v in [k,d,r]) else r2c2.caption("計算中")
            r2c3.caption(f"OBV {'↑' if obv >= 0 else '↓'}　{abs(obv)/1e3:.0f}K") if obv is not None else r2c3.caption("計算中")

    st.divider()
    st.subheader("⑤ 加減碼建議")
    buckets = {"trim": [], "entry": [], "hold": []}
    for sig in sig_results:
        kind, reasons = classify_rebalance(sig, diff_val)
        buckets[kind].append((sig, reasons))
    trim_list, entry_list, hold_list = buckets["trim"], buckets["entry"], buckets["hold"]

    t_trim, t_entry, t_hold = st.tabs([f"🔴 建議減碼（{len(trim_list)}）", f"🟢 建議加碼（{len(entry_list)}）", f"🟡 續抱觀察（{len(hold_list)}）"])
    with t_trim:
        if not trim_list: st.success("目前無需減碼 👍")
        else:
            for sig, reasons in trim_list:
                with st.container(border=True):
                    c1,c2 = st.columns([1,2])
                    c1.markdown(f"**{sig['ticker']} {sig['name']}**  \n現價 {fmt_price(sig['raw'].get('current_price') or 0)} | 損益 {fmt_pct(sig.get('pnl_pct'))}")
                    c2.markdown("**減碼原因：** " + "　/　".join(reasons))
    with t_entry:
        if not entry_list: st.info("目前無同時滿足條件的加碼標的")
        else:
            for sig, reasons in entry_list:
                with st.container(border=True):
                    c1,c2 = st.columns([1,2])
                    c1.markdown(f"**{sig['ticker']} {sig['name']}**  \n現價 {fmt_price(sig['raw'].get('current_price') or 0)} | 損益 {fmt_pct(sig.get('pnl_pct'))}")
                    c2.markdown("**加碼原因：** " + "　/　".join(reasons))
    with t_hold:
        for sig, reasons in hold_list:
            st.markdown(f"• **{sig['ticker']} {sig['name']}** — {' / '.join(reasons)}")

    st.divider()
    with st.expander("🧯 壓力測試（點擊展開）", expanded=False):
        _pt_positions = get_open_positions(user_id)
        if not _pt_positions:
            st.info("先新增持倉才能做壓力測試")
        else:
            _pt_map = {f"{p[0]} {cached_name(p[0])}": p[0] for p in _pt_positions}
            _pt_label = st.selectbox("選擇股票", list(_pt_map.keys()), key="stress_sel")
            _pt_sel = _pt_map[_pt_label]
            _pt_pos = next(p for p in _pt_positions if p[0] == _pt_sel)
            _, _pt_net, _pt_cost, _pt_buy = _pt_pos[0], _pt_pos[1], _pt_pos[2], _pt_pos[3]
            _pt_avg = _pt_cost / _pt_buy if _pt_buy > 0 else 0
            st.info(f"**{_pt_label}**｜{_pt_net} 股｜均成本 {_pt_avg:.2f} 元｜總成本 {_pt_cost:,.0f} 元")
            _drop_pct = st.slider("模擬跌幅", min_value=-50, max_value=-5, value=-20, step=5)
            _r = stress_test(_pt_avg, _pt_net, _drop_pct)
            _pc1,_pc2,_pc3 = st.columns(3)
            _pc1.metric("目前市值", f"${_r['current_value']:,.0f}")
            _pc2.metric("模擬虧損", f"${abs(_r['loss']):,.0f}", delta=f"{_drop_pct}%", delta_color="inverse")
            _pc3.metric("跌後剩餘", f"${_r['new_value']:,.0f}")
            st.divider()
            _sc_rows = []
            for _sname, _pct in [("2020 疫情崩盤",-30),("2022 升息熊市",-25),("2025/04 貿易戰",-20)]:
                _rr = stress_test(_pt_avg, _pt_net, _pct)
                _sc_rows.append({"情境":_sname,"跌幅":f"{_pct}%","帳面虧損":f"${abs(_rr['loss']):,.0f}","剩餘市值":f"${_rr['new_value']:,.0f}"})
            st.dataframe(pd.DataFrame(_sc_rows), width="stretch", hide_index=True)
            st.warning("💬 看到這個數字，你買之前真的想清楚了嗎？")

    with st.expander("📖 指標算法說明（點擊展開）", expanded=False):
        w, hc, sc = STRATEGY["market_risk"]["weights"], STRATEGY["health"], STRATEGY["signals"]
        st.markdown(f"""
**A. 動能狀態 — RS 相對強度矩陣**
強力噴發：RS5>RS10>0 且 RS60>0　趨勢偏多：RS10>0　盤整/弱勢：RS10<0

**B. 進場時機 — KD 隨機指標 + RSI**
KD 9-3-3；黃金交叉=K↑穿越D；RSI>{sc['rsi_overheat']} 過熱；K<{hc['kd_oversold']} 超賣、K>{hc['kd_overbought']} 超買

**C. 量價配合 — OBV 能量潮**
價量齊揚：OBV 5日斜率>0　誘多背離：股價新高但OBV下降

**D. 水位計算** — 0050 RSI×{w['rsi']:.0%} + 季線乖離×{w['bias']:.0%} + 20日波動率×{w['vol']:.0%} + VIX×{w['vix']:.0%}

**E. ATR 停利參考價** = 近60日最高收盤 − {hc['atr_multiplier']}×ATR14
        """)


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
                if d != ep: warns.append(f"[指數] 使用 {d}")
                break
            if err: warns.append(f"[指數] {err}")
        except Exception as e:
            warns.append(f"[指數] {e}"); tc=tch=0

    # 個股行情
    frames = []
    for fn, label in [(_c_twse,"上市"),(_c_tpex,"上櫃")]:
        for d in [ep, _prev(ep)]:
            try:
                df, err = fn(d)
                if not err and not df.empty:
                    df["市場"] = label
                    if d != ep: warns.append(f"[{label}] 使用 {d}")
                    frames.append(df); break
                if err: warns.append(f"[{label}] {err}")
            except Exception as e:
                warns.append(f"[{label}] {e}")
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
            vol_str = f"{df_all['成交金額'].sum()/1e8:.0f}億"
        else:
            vol_str = f"{df_all['成交量'].sum()/1e4:.0f}億張"
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
                if d != ec: warns.append(f"[法人] 使用 {d}")
                df_i = df_i2; break
            if ei2: warns.append(f"[法人] {ei2}")
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
        warns.append(f"[法人] {e}")

    # 漲停
    try:
        df_lu, elu = _c_lu(ep)
        if elu: warns.append(f"[漲停] {elu}")
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
        warns.append(f"[漲停] {e}")

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
        st.error(f"❌ 找不到 market_radar_ui.html")
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
</script>"""
        html_out = html_code.replace("<script>\n'use strict';", inject + "\n<script>\n'use strict';", 1)
        st.iframe(html_out, height=height)
    except Exception as e:
        st.error(f"❌ HTML 渲染失敗：{str(e)}")
        with st.expander("🔍 查看錯誤詳情"):
            import traceback
            st.code(traceback.format_exc())


def _render_sidebar_controls():
    """Sidebar 日期選擇 + 清快取，三個 tab 共用。"""
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 📡 類股熱點")
        default_d = _price_date()
        td = st.date_input("查詢日期", value=datetime.strptime(default_d,"%Y-%m-%d").date(), key="radar_trade_date").strftime("%Y-%m-%d")
        st.session_state["radar_trade_date_str"] = td
        try:
            if not _is_trading_day(datetime.strptime(default_d,"%Y-%m-%d")):
                p = _prev_trading_day(datetime.strptime(default_d,"%Y-%m-%d")).strftime("%Y-%m-%d")
                st.caption(f"🗓️ 休市日，顯示 {p}")
        except: pass
        if st.button("🗑️ 清除快取", width="stretch", key="radar_clear"):
            clear_all_cache()
            # st.cache_data.clear()
            for k in list(st.session_state.keys()):
                if k.startswith("_radar"): del st.session_state[k]
            st.rerun()


def _render_sector_tab():
    _render_sidebar_controls()
    with st.spinner("載入市場資料..."):
        market_data, warns = _get_radar_data()
    if warns:
        with st.sidebar.expander(f"⚠️ {len(warns)} 則警告"):
            for w in warns: st.caption(w)
    idx = market_data.get("index", {})
    if idx:
        c1,c2,c3,c4 = st.columns(4)
        sign = "+" if idx.get("change",0)>=0 else ""
        c1.metric("加權指數", f"{idx.get('taiex',0):,.0f}", f"{sign}{idx.get('change',0):.2f}%")
        c2.metric("上漲", idx.get("up","—"))
        c3.metric("下跌", idx.get("down","—"))
        c4.metric("成交量", idx.get("vol","—"))
    _render_html_section(market_data, "sector")


def _render_market_scan_tab():
    """
    市場掃描 Tab:
    1. 大盤指數
    2. 類股熱度
    3. 今日焦點（radio 切換，用 HTML 渲染）
    """
    _render_sidebar_controls()
    
    with st.spinner("載入市場資料..."):
        market_data, warns = _get_radar_data()
    
    if warns:
        with st.sidebar.expander(f"⚠️ {len(warns)} 則警告"):
            for w in warns: st.caption(w)
    
    # ═══════════════════════════════════════════════════════════
    # 1. 大盤指數
    # ═══════════════════════════════════════════════════════════
    idx = market_data.get("index", {})
    if idx:
        c1, c2, c3, c4 = st.columns(4)
        sign = "+" if idx.get("change", 0) >= 0 else ""
        c1.metric("加權指數", f"{idx.get('taiex', 0):,.0f}", f"{sign}{idx.get('change', 0):.2f}%")
        c2.metric("上漲", idx.get("up", "—"))
        c3.metric("下跌", idx.get("down", "—"))
        c4.metric("成交量", idx.get("vol", "—"))
    
    # ═══════════════════════════════════════════════════════════
    # 2. 類股熱度
    # ═══════════════════════════════════════════════════════════
    _render_html_section_with_height(market_data, "sector", height=1200)
    
    st.markdown("---")
    
    # ═══════════════════════════════════════════════════════════
    # 3. 今日焦點（radio 切換，用 HTML 渲染）
    # ═══════════════════════════════════════════════════════════
    st.markdown("### 📊 今日焦點")
    
    focus_type = st.radio(
        "選擇焦點類型",
        options=["漲停股", "法人買賣超"],
        horizontal=True,
        label_visibility="collapsed",
        key="market_scan_focus"
    )
    
    if focus_type == "漲停股":
        # 渲染漲停分析（HTML）
        _render_html_section_with_height(market_data, "limitup", height=1500)
    elif focus_type == "法人買賣超":
        # 渲染法人買賣超表格（HTML）
        _render_html_section_with_height(market_data, "inst-ranking", height=1200)