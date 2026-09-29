"""
views/analytics.py
績效回顧 — 已出清持股、賣出後遺憾追蹤、買賣理由統計、週報
"""
import pandas as pd
import streamlit as st
from datetime import date, timedelta

from database import (
    get_all_trades, get_open_positions, get_reason_stats, get_realized_sells,
)
from formatting import fmt_pct, fmt_price, color_pnl, color_dir, trades_to_df
from i18n import t, t_cols


def _show(df, pnl_cols=(), dir_cols=(), label_cols=()):
    """顯示用：翻譯欄位名稱與固定值（方向、理由、判定等），再上色。內部運算仍用中文。"""
    disp = df.copy()
    for c in label_cols:
        disp[c] = disp[c].map(lambda v: t(v) if isinstance(v, str) else v)
    disp = t_cols(disp)
    styler = disp.style
    if pnl_cols:
        styler = styler.map(color_pnl, subset=[t(c) for c in pnl_cols])
    if dir_cols:
        styler = styler.map(lambda v: color_dir("買入" if v in ("買入", t("買入")) else "賣出"),
                            subset=[t(c) for c in dir_cols])
    st.dataframe(styler, width="stretch", hide_index=True)


def render(cached_name, cached_price, cached_rs,
           get_price_after_sell, user_id: str = "admin"):

    tab1, tab2, tab3, tab4 = st.tabs([
        t("📤 已出清持股"), t("📊 賣出後遺憾追蹤"), t("買賣理由統計"), t("📝 週報")
    ])

    # ── Tab 1：已出清持股（每一筆賣出的已實現損益，FIFO 配對）──
    with tab1:
        sells = get_realized_sells(user_id)
        if not sells:
            st.info(t("還沒有任何賣出紀錄"))
        else:
            rows = []
            unmatched_total = 0
            for s in sells:
                has_cost = s["matched_shares"] > 0
                pnl_pct  = ((s["sell_price"] / s["avg_cost"] - 1) * 100)  if has_cost else None
                unmatched_total += s["unmatched_shares"]

                note = (t("⚠️ {n} 股找不到對應買入紀錄（可能是使用本 app 前的庫存），不計入損益",
                          n=s["unmatched_shares"]) if s["unmatched_shares"] > 0 else "")

                rows.append({
                    "股票":         f"{s['ticker']} {cached_name(s['ticker'])}",
                    "賣出日":       s["date"],
                    "賣出股數":     s["shares"],
                    "均成本":       fmt_price(s["avg_cost"]),
                    "賣出價":       fmt_price(s["sell_price"]),
                    "實現損益(元)": f"{s['realized_pnl']:+,.0f}" if has_cost else "—",
                    "實現報酬(%)":  fmt_pct(pnl_pct) if pnl_pct is not None else "—",
                    "報酬_num":     pnl_pct,
                    "賣出理由":     s["exit_reason"] or "—",
                    "備註":         note,
                })
            df = pd.DataFrame(rows).sort_values("賣出日", ascending=False)
            _show(df.drop(columns=["報酬_num"]), pnl_cols=["實現損益(元)", "實現報酬(%)"],
                  label_cols=["賣出理由"])

            if unmatched_total > 0:
                st.caption(t(
                    "共 {n} 股賣出在系統裡找不到對應的買入紀錄，"
                    "這部分**不計入**已實現損益（避免把找不到成本的部分誤算成利潤）。",
                    n=unmatched_total))

            st.divider()
            st.subheader(t("賣出理由統計"))
            stats_df = df.dropna(subset=["報酬_num"])
            if stats_df.empty:
                st.info(t("目前沒有找得到成本的賣出紀錄可統計"))
            else:
                stats = (stats_df.groupby("賣出理由")["報酬_num"]
                           .mean()
                           .reset_index())
                stats.columns = ["賣出理由","平均報酬(%)"]
                stats = stats.sort_values("平均報酬(%)", ascending=False)
                stats["平均報酬(%)"] = stats["平均報酬(%)"].map(lambda x: f"{x:+.2f}%")
                _show(stats, pnl_cols=["平均報酬(%)"], label_cols=["賣出理由"])

    # ── Tab 2：賣出後遺憾追蹤 ────────────────────────────
    with tab2:
        st.subheader(t("賣出後遺憾追蹤"))
        st.caption(t("賣出後大漲 → 你抱不住　｜　賣出後繼續跌 → 停損執行正確"))
        all_trades  = get_all_trades(user_id)
        sell_trades = [tr for tr in all_trades if tr["direction"] == "賣出"]
        if not sell_trades:
            st.info(t("還沒有賣出紀錄"))
        else:
            rows = []
            for tr in sell_trades:
                ticker    = tr["ticker"]
                sell_date = tr["date"]
                sell_px   = tr["price"]
                p30, p60  = get_price_after_sell(ticker, sell_date)
                chg30 = f"{(p30/sell_px-1)*100:+.1f}%" if p30 else t("資料不足")
                chg60 = f"{(p60/sell_px-1)*100:+.1f}%" if p60 else t("資料不足")
                verdict = "—"
                if p30:
                    d = (p30/sell_px-1)*100
                    verdict = t("😅 賣太早了" if d > 10 else
                                "✅ 停損正確" if d < -10 else "😐 差不多")
                rows.append({
                    "股票":       f"{ticker} {cached_name(ticker)}",
                    "賣出日":     sell_date,
                    "賣出價":     fmt_price(sell_px),
                    "30天後股價": fmt_price(p30) if p30 else "—",
                    "30天漲跌":   chg30,
                    "60天後股價": fmt_price(p60) if p60 else "—",
                    "60天漲跌":   chg60,
                    "判定":       verdict,
                })
            _show(pd.DataFrame(rows))

    # ── Tab 3：買賣理由統計 ──────────────────────────────
    with tab3:
        st.header(t("買賣理由統計"))
        rows_raw = get_reason_stats(user_id)
        if not rows_raw:
            st.info(t("還沒有足夠的買入紀錄"))
        else:
            result = []
            for reason, ticker, buy_price, shares, buy_date in rows_raw:
                cur = cached_price(ticker)
                if cur and buy_price:
                    result.append({
                        "買入理由": reason,
                        "股票":     f"{ticker} {cached_name(ticker)}",
                        "買入價":   round(float(buy_price), 2),
                        "現價":     round(float(cur), 2),
                        "損益(%)":  round((cur/buy_price-1)*100, 2),
                        "買入日":   buy_date,
                    })
            if result:
                df = pd.DataFrame(result)
                st.subheader(t("各買入理由平均報酬"))
                summary = df.groupby("買入理由")["損益(%)"].agg(["mean","count"]).reset_index()
                summary.columns = ["買入理由","平均損益(%)","筆數"]
                summary = summary.sort_values("平均損益(%)", ascending=False)
                summary["平均損益(%)"] = summary["平均損益(%)"].map(lambda x: f"{x:+.2f}%")
                _show(summary, pnl_cols=["平均損益(%)"], label_cols=["買入理由"])
                st.divider()
                rf_opts = ["全部"] + list(df["買入理由"].unique())
                rf_labels = {v: t(v) if isinstance(v, str) else str(v) for v in rf_opts}
                rf = st.selectbox(t("篩選明細"), rf_opts, format_func=rf_labels.get)
                fd = df if rf == "全部" else df[df["買入理由"] == rf]
                fd = fd.copy()
                fd["買入價"] = fd["買入價"].map(lambda x: f"{float(x):.2f}" if pd.notna(x) else "")
                fd["現價"]   = fd["現價"].map(lambda x: f"{float(x):.2f}" if pd.notna(x) else "")
                fd["損益(%)"] = fd["損益(%)"].map(lambda x: f"{x:+.2f}%")
                _show(fd, pnl_cols=["損益(%)"], label_cols=["買入理由"])

    # ── Tab 4：週報 ──────────────────────────────────────
    with tab4:
        st.header(t("週報"))
        today = date.today()

        week_options = {}
        for i in range(8):
            ref     = today - timedelta(weeks=i)
            w_start = ref - timedelta(days=ref.weekday())
            w_end   = w_start + timedelta(days=6)
            label   = (
                (t("本週") if i == 0 else t("上週") if i == 1 else t("{n}週前", n=i))
                + t("（{start} ～ {end}）", start=w_start, end=min(w_end, today))
            )
            week_options[label] = (w_start, min(w_end, today))

        sel_week             = st.selectbox(t("選擇區間"), list(week_options.keys()))
        week_start, week_end = week_options[sel_week]
        st.caption(t("統計區間：{start} ～ {end}", start=week_start, end=week_end))

        all_trades = get_all_trades(user_id)

        week_trades = [tr for tr in all_trades
                       if str(week_start) <= tr["date"] <= str(week_end)]
        week_sell   = [tr for tr in week_trades if tr["direction"] == "賣出"]
        week_buy    = [tr for tr in week_trades if tr["direction"] == "買入"]

        # FIFO 配對已實現損益，跟「監控中心」的持股成本算法（get_open_positions）一致
        week_realized = sum(
            r["realized_pnl"] for r in get_realized_sells(user_id, week_start, week_end)
        )

        w1, w2, w3 = st.columns(3)
        w1.metric(t("該週交易筆數"), t("{n} 筆", n=len(week_trades)))
        w2.metric(t("該週買入"), t("{n} 筆", n=len(week_buy)))
        w3.metric(t("該週賣出（已實現損益）"),
                  f"${week_realized:+,.0f}" if week_sell else "—",
                  delta=t("{n} 筆", n=len(week_sell)) if week_sell else None,
                  delta_color="off")

        st.divider()
        if not week_trades:
            st.info(t("這個區間沒有任何交易紀錄"))
        else:
            st.subheader(t("該週交易明細"))
            df_w = trades_to_df(week_trades)
            _show(df_w[["日期","股票","方向","價格","股數","買入理由","賣出理由"]],
                  dir_cols=["方向"], label_cols=["方向", "買入理由", "賣出理由"])

        st.divider()
        st.subheader(t("⚠️ 需要注意的持股"))
        st.caption(t("警示邏輯調整中，敬請期待"))
        positions_w = get_open_positions(user_id)
        if positions_w:
            warn_rows = []
            for pos_w in positions_w:
                ticker_w = pos_w[0]
                net_w    = pos_w[1]
                cost_w   = pos_w[2]
                buy_w    = pos_w[3]
                avg_w    = cost_w / buy_w if buy_w > 0 else 0
                cur_w    = cached_price(ticker_w)
                rs_w, _, _ = cached_rs(ticker_w)
                pnl_pct_w  = (cur_w / avg_w - 1) * 100 if cur_w and avg_w > 0 else None
                warn_rows.append({
                    "股票":     f"{ticker_w} {cached_name(ticker_w)}",
                    "損益(%)":  fmt_pct(pnl_pct_w),
                    "近60日RS": f"{rs_w:+.1f}%" if rs_w is not None else "N/A",
                })
            _show(pd.DataFrame(warn_rows))
