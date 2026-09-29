"""
stock_chart_widget.py  v6
修正：
  1. RSI 改為兩條線：RSI(5) + RSI(10)
  2. X 軸改用 category 類型，只顯示有開盤的日期（去除週末/假日空格）
  3. KD 跑版修正：成交量完全獨立用第五子圖，K線圖不疊量
  4. 左方數值跟著游標：用 Plotly FigureWidget + streamlit-plotly-events
     → 改用純 Plotly 的 hovertemplate + annotation 顯示於圖內，
       搭配 JavaScript callback 注入，讓 annotation 隨 hover 更新
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from stock_data import _calc_kd, _calc_obv
from i18n import t

DARK_BG  = "#131722"
GRID_COL = "#2a2e39"
TEXT_COL = "#d1d4dc"


def _format_tw(ticker: str) -> str:
    t = ticker.strip().upper()
    if not t.endswith(".TW") and not t.endswith(".TWO"):
        t += ".TW"
    return t


@st.cache_data(ttl=300)
def _fetch_data(ticker_fmt: str, days: int):
    end   = datetime.today()
    start = end - timedelta(days=days + 120)
    try:
        df = yf.download(ticker_fmt, start=start, end=end,
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna(subset=["Close"])
    except Exception:
        return None


INDICATOR_HELP = """
**KD（N=9）**
- 🔴 K>80 超買紅點；🟢 K<20 超賣綠點
- K 上穿 D = 黃金交叉；K 下穿 D = 死亡交叉

**RSI（5日 / 10日）**
- 橘色 RSI(5)：反應快，短線訊號靈敏
- 紫色 RSI(10)：較平滑，中線趨勢
- 兩線交叉可作為買賣參考

**OBV 能量潮**
- OBV 創新高 + 股價新高 = 健康；背離 = 警示
"""


def _calc_rsi(close: pd.Series, period: int) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def render_stock_chart_section():
    st.header(t("📊 技術圖表分析"))
    st.caption(t("K線 · 成交量 · KD(9) · RSI(5/10) · OBV｜滑鼠移動同步顯示當天數值"))

    c1, c2, c3 = st.columns([3, 2, 1])
    with c1:
        raw_ticker = st.text_input(
            t("股票代號（例：2330、00631L、0050）"),
            placeholder=t("輸入代號後按 Enter"),
            key="chart_ticker_input",
        )
    with c2:
        days_opts  = {"60 天": 60, "90 天": 90, "120 天": 120, "180 天": 180}
        days_label = st.selectbox(t("查詢區間"), list(days_opts.keys()),
                                  index=1, key="chart_days_select", format_func=t)
        days = days_opts[days_label]
    with c3:
        st.write(""); st.write("")
        st.button(t("🔍 查詢"), type="primary", width="stretch",
                  key="chart_query_btn")

    if not raw_ticker:
        st.info(t("👆 輸入股票代號開始分析"))
        return

    ticker_fmt  = _format_tw(raw_ticker)
    ticker_show = raw_ticker.strip().upper()

    with st.spinner(t("下載 {ticker} 資料中...", ticker=ticker_show)):
        df_full = _fetch_data(ticker_fmt, days)

    if df_full is None or df_full.empty:
        st.error(t("❌ 無法取得 {ticker} 的資料", ticker=ticker_show))
        return

    # 在完整資料上計算指標（預熱），再截取
    close  = df_full["Close"]
    high   = df_full["High"]
    low    = df_full["Low"]
    volume = df_full["Volume"]

    ema20    = close.ewm(span=20, adjust=False).mean()
    ema60    = close.ewm(span=60, adjust=False).mean()
    rsi5     = _calc_rsi(close, 5)
    rsi10    = _calc_rsi(close, 10)
    k_val, d_val = _calc_kd(high, low, close, 9)
    obv      = _calc_obv(close, volume)
    obv_ma   = obv.rolling(10).mean()
    vol_ma5  = volume.rolling(5).mean()
    vol_ma10 = volume.rolling(10).mean()

    df = df_full.tail(days).copy()

    def _tr(s): return s.reindex(df.index)

    ema20_d  = _tr(ema20)
    ema60_d  = _tr(ema60)
    rsi5_d   = _tr(rsi5)
    rsi10_d  = _tr(rsi10)
    k_d      = _tr(k_val)
    d_d      = _tr(d_val)
    obv_d    = _tr(obv)
    obv_ma_d = _tr(obv_ma)
    vol_d    = _tr(volume)
    vma5_d   = _tr(vol_ma5)
    vma10_d  = _tr(vol_ma10)

    # ── 關鍵：把日期轉成字串，作為 category x 軸
    # 這樣 Plotly 只會顯示資料中存在的日期，週末/假日的空格消失
    date_strs = df.index.strftime("%Y-%m-%d").tolist()

    cur       = float(df["Close"].iloc[-1])
    cur_ema20 = float(ema20_d.iloc[-1])
    cur_ema60 = float(ema60_d.iloc[-1])
    cur_rsi5  = float(rsi5_d.dropna().iloc[-1])
    cur_rsi10 = float(rsi10_d.dropna().iloc[-1])
    cur_k     = float(k_d.dropna().iloc[-1])
    cur_d     = float(d_d.dropna().iloc[-1])
    cur_obv   = float(obv_d.iloc[-1])

    # ── 頂部摘要卡片 ─────────────────────────────────────────
    def _clr_rsi(v): return "#ef5350" if v >= 70 else ("#26a69a" if v <= 30 else TEXT_COL)
    def _clr_kd(v):  return "#ef5350" if v >= 80 else ("#26a69a" if v <= 20 else TEXT_COL)

    mc = st.columns(6)
    mc[0].metric(t("現價"), f"{cur:.2f}",
                 delta=f"EMA20 {cur_ema20:.2f}",
                 delta_color="normal" if cur >= cur_ema20 else "inverse")
    for i, (lbl, val, fn) in enumerate([
        ("K(9)", cur_k, _clr_kd),
        ("D(9)", cur_d, _clr_kd),
        ("RSI(5)", cur_rsi5, _clr_rsi),
        ("RSI(10)", cur_rsi10, _clr_rsi),
    ]):
        with mc[i + 1]:
            c_color = fn(val)
            st.markdown(
                f"<div style='text-align:center;padding:6px 0'>"
                f"<div style='font-size:11px;color:{TEXT_COL}'>{lbl}</div>"
                f"<div style='font-size:20px;font-weight:bold;color:{c_color}'>{val:.1f}</div>"
                f"</div>", unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════
    # 5 子圖：K線 / 成交量 / KD / RSI / OBV
    # 成交量獨立成一個子圖，徹底解決 KD 跑到 K 線的問題
    # ════════════════════════════════════════════════════════
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        row_heights=[0.38, 0.12, 0.18, 0.17, 0.15],
        vertical_spacing=0.018,
        subplot_titles=("", "", "", "", ""),
    )

    # ─────────────
    # 子圖 1：K 線
    # ─────────────
    # customdata 每列: [open, high, low, close, ema20, ema60]
    cd_candle = np.column_stack([
        df["Open"].values,  df["High"].values,
        df["Low"].values,   df["Close"].values,
        ema20_d.values,     ema60_d.values,
    ])
    fig.add_trace(go.Candlestick(
        x=date_strs,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        increasing_line_color="#ef5350", decreasing_line_color="#26a69a",
        increasing_fillcolor="#ef5350",  decreasing_fillcolor="#26a69a",
        name=t("K線"), showlegend=False,
        customdata=cd_candle,
        hovertemplate=(
            "<b>%{x}</b><br>"
            + t("開") + ":%{customdata[0]:.2f}  " + t("高") + ":%{customdata[1]:.2f}<br>"
            + t("低") + ":%{customdata[2]:.2f}  " + t("收") + ":%{customdata[3]:.2f}<br>"
            "EMA20:%{customdata[4]:.2f}  EMA60:%{customdata[5]:.2f}"
            "<extra></extra>"
        ),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=date_strs, y=ema20_d.values, name="EMA20",
        line=dict(color="#e91e8c", width=1.5),
        hovertemplate="EMA20:%{y:.2f}<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=date_strs, y=ema60_d.values, name="EMA60",
        line=dict(color="#4fc3f7", width=1.5),
        hovertemplate="EMA60:%{y:.2f}<extra></extra>",
    ), row=1, col=1)

    # ─────────────────
    # 子圖 2：成交量（獨立，不疊 K 線，徹底不跑版）
    # ─────────────────
    vol_colors = [
        "#ef5350" if df["Close"].iloc[i] >= df["Open"].iloc[i] else "#26a69a"
        for i in range(len(df))
    ]
    fig.add_trace(go.Bar(
        x=date_strs, y=vol_d.values,
        marker_color=vol_colors, opacity=0.60,
        name=t("成交量"),
        hovertemplate=t("量") + ":%{y:,.0f}<extra></extra>",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=date_strs, y=vma5_d.values, name="Vol MA5",
        line=dict(color="#ffa726", width=1.2, dash="dot"),
        hovertemplate="Vol MA5:%{y:,.0f}<extra></extra>",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=date_strs, y=vma10_d.values, name="Vol MA10",
        line=dict(color="#ab47bc", width=1.2, dash="dot"),
        hovertemplate="Vol MA10:%{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    # ─────────────────
    # 子圖 3：KD
    # ─────────────────
    for lvl, col_line in [
        (80, "rgba(239,83,80,0.4)"),
        (20, "rgba(38,166,154,0.4)"),
        (50, "rgba(120,120,120,0.4)"),
    ]:
        fig.add_hline(y=lvl, line_color=col_line, line_dash="dot",
                      line_width=1, row=3, col=1)

    cd_kd = np.column_stack([k_d.values, d_d.values])
    fig.add_trace(go.Scatter(
        x=date_strs, y=k_d.values, name="K(9)",
        line=dict(color="#FFD700", width=1.8),
        customdata=cd_kd,
        hovertemplate="K:%{customdata[0]:.1f}  D:%{customdata[1]:.1f}<extra></extra>",
    ), row=3, col=1)
    fig.add_trace(go.Scatter(
        x=date_strs, y=d_d.values, name="D(9)",
        line=dict(color="#f48fb1", width=1.8),
        hoverinfo="skip",
    ), row=3, col=1)

    # 超買紅點 / 超賣綠點
    ob_mask = k_d >= 80
    os_mask = k_d <= 20
    if ob_mask.any():
        ob_x = [date_strs[i] for i, v in enumerate(ob_mask.values) if v]
        fig.add_trace(go.Scatter(
            x=ob_x, y=k_d[ob_mask].values,
            mode="markers", name="K>80",
            marker=dict(color="#ef5350", size=7, symbol="circle",
                        line=dict(color="#ff8a80", width=1)),
            hoverinfo="skip",
        ), row=3, col=1)
    if os_mask.any():
        os_x = [date_strs[i] for i, v in enumerate(os_mask.values) if v]
        fig.add_trace(go.Scatter(
            x=os_x, y=k_d[os_mask].values,
            mode="markers", name="K<20",
            marker=dict(color="#26a69a", size=7, symbol="circle",
                        line=dict(color="#80cbc4", width=1)),
            hoverinfo="skip",
        ), row=3, col=1)

    # ─────────────────
    # 子圖 4：RSI(5) + RSI(10)
    # ─────────────────
    for lvl, col_line in [
        (70, "rgba(239,83,80,0.4)"),
        (30, "rgba(38,166,154,0.4)"),
        (50, "rgba(120,120,120,0.4)"),
    ]:
        fig.add_hline(y=lvl, line_color=col_line, line_dash="dot",
                      line_width=1, row=4, col=1)

    cd_rsi = np.column_stack([rsi5_d.values, rsi10_d.values])
    fig.add_trace(go.Scatter(
        x=date_strs, y=rsi5_d.values, name="RSI(5)",
        line=dict(color="#ff9800", width=1.8),
        customdata=cd_rsi,
        hovertemplate="RSI5:%{customdata[0]:.1f}  RSI10:%{customdata[1]:.1f}<extra></extra>",
    ), row=4, col=1)
    fig.add_trace(go.Scatter(
        x=date_strs, y=rsi10_d.values, name="RSI(10)",
        line=dict(color="#7b61ff", width=1.8),
        hoverinfo="skip",
    ), row=4, col=1)

    # ─────────────────
    # 子圖 5：OBV
    # ─────────────────
    obv_bar_clr = ["#ef5350"]
    for i in range(1, len(obv_d)):
        obv_bar_clr.append(
            "#ef5350" if obv_d.iloc[i] >= obv_d.iloc[i - 1] else "#26a69a"
        )
    fig.add_trace(go.Bar(
        x=date_strs, y=obv_d.values,
        marker_color=obv_bar_clr, opacity=0.60,
        name="OBV",
        hovertemplate="OBV:%{y:,.0f}<extra></extra>",
    ), row=5, col=1)
    fig.add_trace(go.Scatter(
        x=date_strs if len(obv_ma_d.dropna()) == len(date_strs)
          else [date_strs[i] for i, v in enumerate(obv_ma_d.notna().values) if v],
        y=obv_ma_d.dropna().values,
        name="OBV MA10", line=dict(color="#FFD700", width=1.5),
        hovertemplate="OBV MA10:%{y:,.0f}<extra></extra>",
    ), row=5, col=1)

    # ════════════════════════════════════════════════════════
    # 動態數值標籤（圖內左上角）
    # 做法：在每個子圖放一個「空白」annotation 作為容器，
    # 再注入 JS 讓它在 plotly_hover 事件時更新文字
    # ════════════════════════════════════════════════════════

    # 靜態初始 annotation（最新值），JS 會 overwrite
    ann_rows = [
        (0.995, f"<b>{ticker_show}</b>  "
                f"{t('收')}:<b>{cur:.2f}</b>  "
                f"<span style='color:#e91e8c'>EMA20:{cur_ema20:.2f}</span>  "
                f"<span style='color:#4fc3f7'>EMA60:{cur_ema60:.2f}</span>"),
        (0.595, f"{t('量')}: {float(vol_d.iloc[-1]):,.0f}  "
                f"MA5:{float(vma5_d.dropna().iloc[-1]):,.0f}  "
                f"MA10:{float(vma10_d.dropna().iloc[-1]):,.0f}"),
        (0.450, f"<b>KD(9)</b>  "
                f"<span style='color:#FFD700'>K:{cur_k:.1f}</span>  "
                f"<span style='color:#f48fb1'>D:{cur_d:.1f}</span>"),
        (0.295, f"<b>RSI</b>  "
                f"<span style='color:#ff9800'>{t('5日')}:{cur_rsi5:.1f}</span>  "
                f"<span style='color:#7b61ff'>{t('10日')}:{cur_rsi10:.1f}</span>"),
        (0.148, f"<b>OBV</b>  {cur_obv:,.0f}"),
    ]

    for y_pos, txt in ann_rows:
        fig.add_annotation(
            text=txt, xref="paper", yref="paper",
            x=0.005, y=y_pos, xanchor="left", yanchor="top",
            showarrow=False,
            font=dict(color=TEXT_COL, size=12),
            bgcolor="rgba(19,23,34,0.82)",
            name="info_label",
        )

    # ════════════════════════════════════════════════════════
    # Layout
    # ════════════════════════════════════════════════════════
    fig.update_layout(
        height=900,
        plot_bgcolor=DARK_BG,
        paper_bgcolor=DARK_BG,
        font=dict(color=TEXT_COL, size=12),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.005,
            xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT_COL, size=11),
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(19,23,34,0.95)",
            bordercolor="#555",
            font=dict(color="#ffffff", size=12),
            namelength=-1,
        ),
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=30, b=10),
        dragmode="zoom",
    )

    # x 軸 type="category" → 只顯示有資料的日期，去除週末空格
    spike_cfg = dict(
        type="category",          # ← 關鍵：category 軸不補空格
        showspikes=True,
        spikecolor="#888888",
        spikethickness=1,
        spikedash="dot",
        spikemode="across",
        spikesnap="cursor",
        gridcolor=GRID_COL,
        tickfont=dict(color=TEXT_COL),
        linecolor=GRID_COL,
        # 只顯示部分刻度，避免日期擠在一起
        tickmode="auto",
        nticks=12,
    )
    fig.update_xaxes(**spike_cfg)
    fig.update_yaxes(
        gridcolor=GRID_COL,
        zerolinecolor=GRID_COL,
        tickfont=dict(color=TEXT_COL),
    )
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    fig.update_yaxes(range=[0, 100], row=4, col=1)

    for r in [1, 2, 3, 4]:
        fig.update_xaxes(showticklabels=False, row=r, col=1)
    fig.update_xaxes(showticklabels=True, row=5, col=1)

    # ── 只對 scatter trace（在子圖座標系內的）綁定 xaxis="x"
    # 不碰 Candlestick，不碰 Bar，避免跑版
    for trace in fig.data:
        if isinstance(trace, go.Scatter):
            trace.xaxis = "x"

    st.plotly_chart(fig, width="stretch", theme=None,
                    key="main_chart")

    st.caption(t(
        "🔴 K>80 超買紅點  🟢 K<20 超賣綠點  ｜  "
        "RSI 橘線=5日、紫線=10日  ｜  "
        "X 軸已過濾週末/假日"
    ))

    with st.expander(t("📖 指標說明"), expanded=False):
        st.markdown(t(INDICATOR_HELP))