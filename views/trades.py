"""
views/trades.py
紀錄維護 — 手動新增、批次匯入 CSV、所有交易紀錄管理

驗證與存檔邏輯在 services/trade_service.py，這裡只負責畫面。
"""
import pandas as pd
import streamlit as st
from datetime import date

from database import get_all_trades, delete_trade, update_trade
from formatting import color_dir, trades_to_df
from services import trade_service

MARKET_CONDITION_OPTIONS = ["高位（接近52週高點）", "中位（正常區間）", "低位（回調整理）", "恐慌（大跌中）"]
BUY_REASON_OPTIONS = ["技術面突破", "基本面看好", "法人買超", "定期定額", "看新聞/聽消息", "其他"]
SELL_REASON_OPTIONS = [
    "停損觸發（原始防線失守）",
    "達標獲利（到目標價）",
    "邏輯消失（買進理由不再成立）",
    "換股操作（找到更好的標的）",
    "其他",
]


def render(cached_market, user_id: str = "admin", readonly: bool = False):
    """readonly=True（Demo 訪客）時只顯示紀錄列表，新增/匯入/編輯/刪除全部隱藏。"""
    if readonly:
        st.info("👀 Demo 模式：交易紀錄為虛構範例，新增、匯入、編輯、刪除功能已停用。")
        tab3 = st.container()
    else:
        tab_manual, tab_csv, tab3 = st.tabs(["✏️ 手動新增單筆", "⬆️ 批次匯入 CSV", "📋 交易紀錄"])

    if not readonly:
        # ── 手動新增 ──────────────────────────────────────────
        with tab_manual:
            with st.spinner("判斷大盤位階..."):
                market_label, market_price, pct_from_high = cached_market()
            if market_price:
                st.info(f"**今日大盤：** {market_label}　｜　0050 現價 {market_price}　｜　距52週高點 {pct_from_high}%")

            direction = st.radio("買賣方向", ["買入","賣出"], horizontal=True, key="manual_dir")

            with st.form("trade_form"):
                col1, col2 = st.columns(2)
                with col1:
                    trade_date = st.date_input("交易日期", value=date.today())
                    ticker     = st.text_input("股票代號（例如：0050、2330、00981A）")
                    price      = st.number_input("成交價格（元）", min_value=0.0, step=0.01, format="%.2f")
                    shares     = st.number_input("股數（零股直接填）", min_value=1, step=1)
                with col2:
                    auto_idx = next((i for i, o in enumerate(MARKET_CONDITION_OPTIONS)
                                     if market_label and market_label[:2] in o), 1)
                    market_cond  = st.selectbox("當時大盤位階（自動判斷）", MARKET_CONDITION_OPTIONS, index=auto_idx)
                    stop_loss    = st.number_input("停損價（元，選填）",  min_value=0.0, step=0.01, format="%.2f")
                    target_price = st.number_input("目標價（元，選填）",  min_value=0.0, step=0.01, format="%.2f")

                    if direction == "買入":
                        reason = st.selectbox("買入理由", BUY_REASON_OPTIONS)
                        estimated_eps = st.number_input("預估今年 EPS（元，選填）",
                            min_value=0.0, step=0.1, format="%.2f",
                            help="填入後自動計算 Forward P/E")
                        exit_reason = None
                    else:
                        exit_reason = st.selectbox("賣出理由", SELL_REASON_OPTIONS)
                        reason = estimated_eps = None

                notes     = st.text_area("備註（選填）")
                submitted = st.form_submit_button("✅ 儲存這筆交易", width="stretch")

                if submitted:
                    result = trade_service.create_trade(
                        date=trade_date, ticker=ticker, direction=direction,
                        price=price, shares=shares, reason=reason, exit_reason=exit_reason,
                        market_condition=market_cond, stop_loss=stop_loss,
                        target_price=target_price, estimated_eps=estimated_eps,
                        notes=notes, user_id=user_id,
                    )
                    if not result["ok"]:
                        for err in result["errors"]:
                            st.error(err)
                    else:
                        total = result["total"]
                        msg = f"✅ {direction} {result['ticker']} {shares}股 @ {price:.2f}（合計 {total:,.0f} 元）"
                        if result["bench_price"]:
                            msg += f"\n當日 0050：{result['bench_price']} 元"
                        if result["forward_pe"]:
                            msg += f"\nForward P/E：{result['forward_pe']}x"
                        st.success(msg)
                        st.balloons()

        # ── 批次匯入 CSV ─────────────────────────────────────
        with tab_csv:
            st.markdown("""
    #### 格式說明
    | 欄位 | 必填 | 說明 |
    |------|------|------|
    | `date` | ✅ | 日期，支援 `2024-01-15` 或 `2024/01/15` |
    | `ticker` | ✅ | 代號，如 `0050`、`00981A` |
    | `direction` | ✅ | `買入` 或 `賣出` |
    | `price` | ✅ | 成交價格（支援 `2,500` 含逗號格式） |
    | `shares` | ✅ | 股數 |
    | `reason` | ❌ | 買入理由 |
    | `exit_reason` | ❌ | 賣出理由 |
    | `stop_loss` | ❌ | 停損價 |
    | `target_price` | ❌ | 目標價 |
    | `notes` | ❌ | 備註 |
            """)
            template = (
                "date,ticker,direction,price,shares,reason,exit_reason,stop_loss,target_price,notes\n"
                "2024-01-15,0050,買入,185.5,100,定期定額,,,\n"
                "2024-06-01,00981A,買入,15.2,1000,技術面突破,,,\n"
                "2024-08-01,0050,賣出,200,100,,達標獲利（到目標價）,,\n"
            )
            st.download_button("⬇️ 下載 CSV 模板", data=template,
                               file_name="trades_template.csv", mime="text/csv")

            uploaded_csv = st.file_uploader("上傳 CSV 檔案", type=["csv"], key="csv_uploader")
            if uploaded_csv:
                try:
                    df_csv = pd.read_csv(uploaded_csv, dtype={"ticker": str})
                    v = trade_service.validate_csv_rows(df_csv)

                    if v["missing_cols"]:
                        st.error(f"缺少必要欄位：{v['missing_cols']}")
                        return

                    if not v["bad_direction"].empty:
                        st.error("direction 欄位有誤（只接受「買入」或「賣出」）：")
                        st.dataframe(v["bad_direction"][["date","ticker","direction"]], hide_index=True)
                        return

                    if not v["bad_ticker"].empty:
                        st.warning(f"以下 {len(v['bad_ticker'])} 筆代號格式可能有誤，請確認：")
                        st.dataframe(v["bad_ticker"][["date","ticker"]], hide_index=True)
                        if not st.checkbox("確認代號正確，忽略警告", key="ignore_tk2"):
                            return

                    if not v["bad_price"].empty:
                        st.error("以下幾筆價格有問題：")
                        st.dataframe(v["bad_price"][["date","ticker","price"]], hide_index=True)
                        return

                    df_clean = v["clean"]
                    st.success(f"✅ 驗證通過，共 {len(df_clean)} 筆，預覽如下：")
                    st.dataframe(df_clean, width="stretch", hide_index=True)

                    auto_bench2 = st.checkbox("自動補抓買入當天 0050 價格（較慢）",
                                              value=True, key="auto_bench2")
                    if st.button("✅ 確認匯入", type="primary", width="stretch",
                                 key="confirm_import2"):
                        prog2 = st.progress(0, text="匯入中...") if auto_bench2 else None
                        on_progress = (
                            (lambda done, total: prog2.progress(done/total, text=f"{done}/{total}"))
                            if prog2 else None
                        )
                        count = trade_service.import_csv_trades(
                            df_clean, user_id=user_id, auto_bench=auto_bench2,
                            on_progress=on_progress,
                        )
                        if prog2:
                            prog2.empty()
                        st.success(f"🎉 成功匯入 {count} 筆！")
                        st.balloons()
                except Exception as e_csv:
                    st.error(f"讀取失敗：{e_csv}")

    # ── 所有交易紀錄 ─────────────────────────────────────
    with tab3:
        st.header("所有交易紀錄")
        trades = get_all_trades(user_id)

        if not trades:
            st.info("還沒有任何交易紀錄")
        else:
            df = trades_to_df(trades)
            df["_price_num"]  = pd.to_numeric(df["價格"].str.replace(",",""), errors="coerce")
            df["_shares_num"] = pd.to_numeric(df["股數"], errors="coerce")
            df["合計(元)"] = (df["_price_num"] * df["_shares_num"]).map(
                lambda x: f"{x:,.0f}" if pd.notna(x) else "")

            col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
            with col_f1:
                search_kw = st.text_input("🔍 搜尋股票代號或名稱", placeholder="例如：0050、台積電")
            with col_f2:
                dir_filter = st.selectbox("方向", ["全部","買入","賣出"])
            with col_f3:
                reason_filter = st.selectbox("理由篩選", ["全部"] +
                    list(df["買入理由"].dropna().unique()) +
                    list(df["賣出理由"].dropna().unique()))

            mask = pd.Series([True] * len(df))
            if search_kw:
                mask &= df["股票"].str.contains(search_kw, case=False, na=False)
            if dir_filter != "全部":
                mask &= df["方向"] == dir_filter
            if reason_filter != "全部":
                mask &= (df["買入理由"] == reason_filter) | (df["賣出理由"] == reason_filter)

            df_show = df[mask].copy()
            st.caption(f"共 {len(df_show)} 筆（總計 {len(df)} 筆）")
            disp = ["日期","股票","方向","價格","股數","合計(元)","買入理由","賣出理由",
                    "大盤位階","停損價","目標價","預估EPS","當日0050價","備註"]
            st.dataframe(df_show[disp].style.map(color_dir, subset=["方向"]),
                        width="stretch", hide_index=True)
            csv_out = df_show[disp].to_csv(index=False, encoding="utf-8-sig")
            st.download_button("⬇️ 匯出 CSV", data=csv_out,
                               file_name=f"trades_{date.today()}.csv", mime="text/csv")

            st.divider()

            def build_trade_options(trade_list, kw=""):
                opts = {}
                kw = kw.strip().lower()
                for t in trade_list:
                    label = (f"{t['date']}　{t['direction']}　{t['ticker']}　"
                             f"{t['price']}元　{t['shares']}股")
                    if not kw or kw in label.lower():
                        opts[label] = t["id"]
                return opts

            if readonly:
                return

            tab_edit, tab_del = st.tabs(["✏️ 編輯紀錄", "🗑️ 刪除紀錄"])

            with tab_edit:
                edit_kw   = st.text_input("🔍 搜尋要編輯的紀錄（輸入代號、日期或方向）", key="edit_kw")
                edit_opts = build_trade_options(trades, edit_kw)
                if not edit_opts:
                    st.info("沒有符合條件的紀錄")
                else:
                    sel_label_e = st.selectbox("選擇紀錄", list(edit_opts.keys()), key="edit_sel")
                    sel_id_e    = edit_opts[sel_label_e]
                    orig = next(t for t in trades if t["id"] == sel_id_e)
                    O = dict(orig)

                    with st.form("edit_form"):
                        ec1, ec2 = st.columns(2)
                        with ec1:
                            e_date   = st.date_input("日期", value=pd.to_datetime(O["date"]).date())
                            e_ticker = st.text_input("股票代號", value=O["ticker"] or "")
                            e_dir    = st.selectbox("方向", ["買入","賣出"],
                                index=0 if O["direction"]=="買入" else 1)
                            e_price  = st.number_input("成交價格",
                                value=float(O["price"] or 0), step=0.01, format="%.2f")
                            e_shares = st.number_input("股數",
                                value=int(O["shares"] or 0), min_value=1, step=1)
                        with ec2:
                            mc_idx = next((i for i, m in enumerate(MARKET_CONDITION_OPTIONS)
                                        if O["market_condition"] and O["market_condition"] in m), 1)
                            e_mc  = st.selectbox("大盤位階", MARKET_CONDITION_OPTIONS, index=mc_idx)
                            e_sl  = st.number_input("停損價", value=float(O["stop_loss"] or 0), step=0.01, format="%.2f")
                            e_tp  = st.number_input("目標價", value=float(O["target_price"] or 0), step=0.01, format="%.2f")
                            e_eps = st.number_input("預估EPS", value=float(O["estimated_eps"] or 0), step=0.01, format="%.2f")
                            r_idx = next((i for i, r in enumerate(BUY_REASON_OPTIONS)
                                        if O["reason"] and O["reason"]==r), 0)
                            e_reason = st.selectbox("買入理由", BUY_REASON_OPTIONS, index=r_idx)
                            exit_opts = SELL_REASON_OPTIONS + [""]
                            ex_idx = next((i for i, r in enumerate(exit_opts)
                                        if O["exit_reason"] and O["exit_reason"]==r), 5)
                            e_exit = st.selectbox("賣出理由", exit_opts, index=ex_idx)
                        e_notes = st.text_area("備註", value=O["notes"] or "")
                        saved   = st.form_submit_button("💾 儲存修改", width="stretch", type="primary")
                        if saved:
                            update_trade(
                                trade_id=sel_id_e,
                                date=str(e_date), ticker=e_ticker, direction=e_dir,
                                price=e_price, shares=e_shares,
                                reason=e_reason if e_dir=="買入" else None,
                                exit_reason=e_exit if e_exit else None,
                                market_condition=e_mc,
                                stop_loss=e_sl   if e_sl  > 0 else None,
                                target_price=e_tp if e_tp > 0 else None,
                                estimated_eps=e_eps if e_eps > 0 else None,
                                notes=e_notes, user_id=user_id,
                            )
                            st.success("✅ 已儲存修改！")
                            st.rerun()

            with tab_del:
                del_kw   = st.text_input("🔍 搜尋要刪除的紀錄（輸入代號、日期或方向）", key="del_kw")
                del_opts = build_trade_options(trades, del_kw)
                if not del_opts:
                    st.info("沒有符合條件的紀錄")
                else:
                    sel_label_d = st.selectbox("選擇紀錄", list(del_opts.keys()), key="del_sel")
                    sel_id_d    = del_opts[sel_label_d]
                    st.warning("確定要刪除這筆紀錄嗎？此操作無法復原。")
                    if st.button("🗑️ 確認刪除", type="secondary"):
                        delete_trade(sel_id_d, user_id=user_id)
                        st.success("已刪除")
                        st.rerun()
