"""
views/monitor.py
監控中心頁面：持倉總覽 + K線圖＋交易點位
"""
import streamlit as st
import pandas as pd
from datetime import date, timedelta

from database import (
    get_open_positions, get_all_trades, get_buy_trades_missing_bench,
    update_bench_price,
)
from formatting import color_dir, trades_to_df
from i18n import t, t_cols
from stock_data import get_price_on_date


def render(cached_name, cached_price, cached_rs, cached_hist, user_id: str = "admin",
           readonly: bool = False):
    # ── Summary Bar ───────────────────────────────────────
    _positions_summary = get_open_positions(user_id)
    _total_cost_summary = 0
    _total_mktval_summary = 0
    for _pos in _positions_summary:
        _ticker_s, _net_s, _cost_s, _buy_s = _pos[0], _pos[1], _pos[2], _pos[3]
        _avg_s = _cost_s / _buy_s if _buy_s > 0 else 0
        _cur_s = cached_price(_ticker_s)
        _total_cost_summary += _avg_s * _net_s
        if _cur_s:
            _total_mktval_summary += _cur_s * _net_s
    _total_ret_summary = (
        (_total_mktval_summary / _total_cost_summary - 1) * 100
        if _total_cost_summary > 0 and _total_mktval_summary > 0 else None
    )
    _total_pnl_abs = _total_mktval_summary - _total_cost_summary
    _sb1, _sb2, _sb3, _sb4, _sb5 = st.columns(5)
    _sb1.metric(t("持股檔數"), t("{n} 檔", n=len(_positions_summary)))
    _sb2.metric(t("總成本"), f"${_total_cost_summary:,.0f}")
    _sb3.metric(t("總市值（估算）"), f"${_total_mktval_summary:,.0f}")
    _sb4.metric(t("預估損益（元）"),
                f"${_total_pnl_abs:+,.0f}" if _total_mktval_summary > 0 else "—")
    _sb5.metric(t("整體報酬"),
                f"{_total_ret_summary:+.2f}%" if _total_ret_summary is not None else "—")
    st.divider()

    sub_tab = st.tabs([t("持倉總覽"), t("K線圖＋交易點位")])

    # ══════════════════════════════════════════════════════
    # 持倉總覽
    # ══════════════════════════════════════════════════════
    with sub_tab[0]:
        positions = get_open_positions(user_id)
        if not positions:
            st.info(t("目前沒有持倉，先去新增交易或匯入 CSV！"))
        else:
            missing = get_buy_trades_missing_bench(user_id)
            if missing and not readonly:
                st.warning(t("有 {n} 筆買入紀錄缺少當日 0050 價格", n=len(missing)))
                if st.button(t("🔄 自動補抓")):
                    prog = st.progress(0)
                    for i, (tid, tdate_val) in enumerate(missing):
                        bp = get_price_on_date("0050", tdate_val)
                        if bp:
                            update_bench_price(tid, bp)
                        prog.progress((i+1)/len(missing))
                    prog.empty()
                    st.success(t("補抓完成！"))
                    st.rerun()

            bench_now = cached_price("0050")
            rows = []
            for pos in positions:
                (ticker, net_shares, total_cost, total_buy_shares, first_buy_date,
                bench_weighted_cost, bench_shares_with_price,
                target_price, stop_loss, estimated_eps) = pos

                avg_cost = total_cost / total_buy_shares if total_buy_shares > 0 else 0
                name = cached_name(ticker)
                cur  = cached_price(ticker)
                pnl = pnl_pct = None
                if cur:
                    pnl     = (cur - avg_cost) * net_shares
                    pnl_pct = (cur / avg_cost - 1) * 100 if avg_cost > 0 else 0
                rs, _, _ = cached_rs(ticker)
                bench_compare = "—"
                if bench_shares_with_price and bench_now:
                    avg_b = bench_weighted_cost / bench_shares_with_price
                    b_ret = (bench_now / avg_b - 1) * 100 if avg_b > 0 else None
                    if b_ret is not None and pnl_pct is not None:
                        diff = pnl_pct - b_ret
                        tmpl = ("0050={b:+.1f}%（你多賺 {d:.1f}%）" if diff >= 0
                                else "0050={b:+.1f}%（你少賺 {d:.1f}%）")
                        bench_compare = t(tmpl, b=b_ret, d=abs(diff))
                rows.append({
                    "股票":        f"{ticker} {name}",
                    "持股(股)":    net_shares,
                    "均成本":      round(avg_cost, 2) if avg_cost else None,
                    "現價":        round(cur, 2) if cur else None,
                    "損益(元)":    round(pnl, 0) if pnl is not None else None,
                    "我的報酬(%)": round(pnl_pct, 2) if pnl_pct is not None else None,
                    "若買0050":    bench_compare,
                    "近60日RS(%)": round(rs, 2) if rs is not None else None,
                    "目標價":      round(target_price, 2) if target_price else None,
                    "停損價":      round(stop_loss, 2) if stop_loss else None,
                })
            st.dataframe(
                t_cols(pd.DataFrame(rows)),
                width="stretch",
                hide_index=True,
                column_config={
                    t("均成本"):       st.column_config.NumberColumn(format="%.2f"),
                    t("現價"):         st.column_config.NumberColumn(format="%.2f"),
                    t("損益(元)"):     st.column_config.NumberColumn(format="%+,.0f"),
                    t("我的報酬(%)"):  st.column_config.NumberColumn(format="%+.2f%%"),
                    t("近60日RS(%)"):  st.column_config.NumberColumn(format="%+.2f%%"),
                    t("目標價"):       st.column_config.NumberColumn(format="%.2f"),
                    t("停損價"):       st.column_config.NumberColumn(format="%.2f"),
                },
            )
            st.caption(t("**若買0050** = 同期買 0050 的報酬比較　｜　**近60日RS** = 個股 vs 0050 相對強度"))

            st.divider()
            st.subheader(t("近 60 日相對走勢（起點=100）"))
            ticker_map = {f"{pos[0]} {cached_name(pos[0])}": pos[0] for pos in positions}
            sel_label = st.selectbox(t("選擇股票"), list(ticker_map.keys()), key="monitor_kline_select")
            sel = ticker_map[sel_label]
            sh = cached_hist(sel)
            bh = cached_hist("0050")
            if sh is not None and bh is not None:
                try:
                    import plotly.graph_objects as go
                    combined = pd.DataFrame({sel_label: sh, "0050": bh}).dropna()
                    mid_val  = 100
                    all_vals = pd.concat([combined[sel_label], combined["0050"]])
                    spread   = max(abs(all_vals - mid_val).max() * 1.3, 3)
                    fig_ov = go.Figure()
                    fig_ov.add_trace(go.Scatter(
                        x=combined.index, y=combined[sel_label],
                        name=sel_label, mode="lines",
                        line=dict(color="#ef5350", width=2.5),
                    ))
                    fig_ov.add_trace(go.Scatter(
                        x=combined.index, y=combined["0050"],
                        name=t("0050（大盤）"), mode="lines",
                        line=dict(color="#5b9bd5", width=1.8, dash="dot"),
                    ))
                    fig_ov.add_hline(y=100, line_dash="dash", line_color="#555", line_width=1)
                    fig_ov.update_layout(
                        height=300,
                        yaxis=dict(range=[mid_val-spread*1.3, mid_val+spread*1.3], gridcolor="#2a2e39"),
                        xaxis=dict(gridcolor="#2a2e39"),
                        plot_bgcolor="#131722", paper_bgcolor="#131722",
                        font=dict(color="#d1d4dc"),
                        legend=dict(orientation="h", y=1.08),
                        margin=dict(l=0, r=0, t=30, b=0),
                        hovermode="x unified",
                    )
                    st.plotly_chart(fig_ov, width="stretch")
                    st.caption(t("紅線=個股　藍虛線=0050　基準線100=起始點，高於100代表這段期間漲更多"))
                except ImportError:
                    st.line_chart(pd.DataFrame({sel_label: sh, "0050": bh}).dropna(), height=300)
            else:
                st.warning(t("股價資料抓取失敗"))

    # ══════════════════════════════════════════════════════
    # K線圖＋交易點位
    # ══════════════════════════════════════════════════════
    with sub_tab[1]:
        st.header(t("K線圖＋交易點位"))
        st.caption(t("在 K 線上標出你的實際買賣點，直觀回顧進出場位置"))
        try:
            import plotly.graph_objects as go
        except ImportError:
            st.error(t("請先執行：pip install plotly"))
            return

        all_trades = get_all_trades(user_id)
        if not all_trades:
            st.info(t("還沒有任何交易紀錄"))
            return

        traded_tickers = sorted(set(tr["ticker"] for tr in all_trades))
        ticker_map     = {f"{tk} {cached_name(tk)}": tk for tk in traded_tickers}
        sel_label      = st.selectbox(t("選擇股票"), list(ticker_map.keys()))
        sel            = ticker_map[sel_label]

        col1, col2 = st.columns(2)
        with col1:
            period_opt = st.selectbox(t("時間範圍"), ["3個月","6個月","1年","2年","自訂"], format_func=t)
        with col2:
            days_map = {"3個月":90,"6個月":180,"1年":365,"2年":730}
            if period_opt == "自訂":
                date_from = st.date_input(t("起始日"), value=date.today()-timedelta(days=180))
                date_to   = st.date_input(t("結束日"), value=date.today())
            else:
                date_from = date.today() - timedelta(days=days_map[period_opt])
                date_to   = date.today()
                st.write(f"{date_from} ～ {date_to}")

        ema_options = st.multiselect(t("顯示 EMA 均線"), [5,10,20,60,120,240], default=[20,60])

        with st.spinner(t("抓取 K 線資料...")):
            import yfinance as yf
            t_fmt  = sel + ".TW" if not sel.endswith(".TW") else sel
            df_raw = yf.download(t_fmt, start=str(date_from),
                                end=str(date_to+timedelta(days=1)),
                                progress=False, auto_adjust=True)
        if df_raw.empty:
            st.error(t("股價資料抓取失敗"))
            return
        if isinstance(df_raw.columns, pd.MultiIndex):
            df_raw.columns = df_raw.columns.get_level_values(0)
        df_raw.index = pd.to_datetime(df_raw.index)
        df_k = df_raw[["Open","High","Low","Close","Volume"]].copy().dropna()
        for e in ema_options:
            df_k[f"EMA{e}"] = df_k["Close"].ewm(span=e, adjust=False).mean()

        ticker_trades = [tr for tr in all_trades
                        if tr["ticker"] == sel
                        and str(date_from) <= tr["date"] <= str(date_to)]
        buy_trades  = [tr for tr in ticker_trades if tr["direction"] == "買入"]
        sell_trades = [tr for tr in ticker_trades if tr["direction"] == "賣出"]

        def safe_price(tr):
            try: return float(tr["price"])
            except (TypeError, ValueError): return None

        buy_trades  = [tr for tr in buy_trades  if safe_price(tr) is not None]
        sell_trades = [tr for tr in sell_trades if safe_price(tr) is not None]

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df_k.index,
            open=df_k["Open"], high=df_k["High"],
            low=df_k["Low"],   close=df_k["Close"],
            name=t("K線"),
            increasing_line_color="#e53935", decreasing_line_color="#26a69a",
            increasing_fillcolor="#e53935",  decreasing_fillcolor="#26a69a",
        ))
        ema_colors = {5:"#f39c12",10:"#e74c3c",20:"#e91e8c",60:"#3498db",120:"#2ecc71",240:"#1abc9c"}
        for e in ema_options:
            if f"EMA{e}" in df_k.columns:
                fig.add_trace(go.Scatter(
                    x=df_k.index, y=df_k[f"EMA{e}"],
                    name=f"EMA{e}", line=dict(color=ema_colors.get(e,"#aaa"), width=1.5), opacity=0.85,
                ))

        if not ticker_trades:
            st.warning(t("⚠️ 在 {start} 至 {end} 區間內找不到 {ticker} 的交易紀錄。", start=date_from, end=date_to, ticker=sel))
        elif not buy_trades and not sell_trades:
            st.info(t("K 線已載入，但此區間沒有買賣紀錄可標記"))

        if buy_trades:
            b_dates  = [pd.to_datetime(tr["date"]) for tr in buy_trades]
            b_prices = [float(tr["price"]) for tr in buy_trades]
            b_hover  = [t("買入 {shares}股 @ {price:.2f}<br>理由：{reason}", shares=tr["shares"],
                          price=float(tr["price"]), reason=t(tr["reason"]) if tr["reason"] else "—")
                        for tr in buy_trades]
            fig.add_trace(go.Scatter(
                x=b_dates, y=[p * 0.98 for p in b_prices],
                mode="markers+text", name=t("買入(B)"),
                marker=dict(symbol="triangle-up", size=14, color="#FFFF36",
                            line=dict(color="white", width=1)),
                text=["B"]*len(b_dates), textposition="bottom center",
                textfont=dict(color="#FFFF36", size=10, family="Arial Black"),
                customdata=b_hover, hovertemplate="%{customdata}<extra></extra>",
            ))
        if sell_trades:
            s_dates  = [pd.to_datetime(tr["date"]) for tr in sell_trades]
            s_prices = [float(tr["price"]) for tr in sell_trades]
            s_hover  = [t("賣出 {shares}股 @ {price:.2f}<br>理由：{reason}", shares=tr["shares"],
                          price=float(tr["price"]), reason=t(tr["exit_reason"]) if tr["exit_reason"] else "—")
                        for tr in sell_trades]
            fig.add_trace(go.Scatter(
                x=s_dates, y=[p * 1.02 for p in s_prices],
                mode="markers+text", name=t("賣出(S)"),
                marker=dict(symbol="triangle-down", size=14, color="#2E4BCC",
                            line=dict(color="white", width=1)),
                text=["S"]*len(s_dates), textposition="top center",
                textfont=dict(color="#2E4BCC", size=10, family="Arial Black"),
                customdata=s_hover, hovertemplate="%{customdata}<extra></extra>",
            ))

        fig.update_layout(
            title=t("{ticker} {name}　K線圖", ticker=sel, name=sel_label.split(' ',1)[-1]),
            xaxis_rangeslider_visible=False, height=600,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            plot_bgcolor="#131722", paper_bgcolor="#131722",
            font=dict(color="#d1d4dc"),
            xaxis=dict(gridcolor="#2a2e39"), yaxis=dict(gridcolor="#2a2e39"),
            hovermode="x unified",
        )
        st.plotly_chart(fig, width="stretch")

        if ticker_trades:
            st.divider()
            st.subheader(t("此區間交易明細"))
            df_t = trades_to_df(ticker_trades)
            disp = ["日期","方向","價格","股數","買入理由","賣出理由","備註"]
            df_show = df_t[disp].copy()
            for col in ["方向", "買入理由", "賣出理由", "備註"]:   # 備註：Demo 範例備註有翻譯
                df_show[col] = df_show[col].map(lambda v: t(v) if isinstance(v, str) else v)
            df_show = t_cols(df_show)
            st.dataframe(df_show.style.map(color_dir, subset=[t("方向")]),
                        width="stretch", hide_index=True)