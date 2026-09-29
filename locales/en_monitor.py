"""views/monitor.py、stock_chart_widget.py、formatting.py：監控中心、K 線圖、技術圖表。"""

EN = {
    # ── 監控中心：摘要列 ──
    "持股檔數": "Holdings",
    "{n} 檔": "{n} stocks",
    "總成本": "Total cost",
    "總市值（估算）": "Market value (est.)",
    "預估損益（元）": "Unrealized P/L (NT$)",
    "整體報酬": "Total return",
    "持倉總覽": "Positions",
    "K線圖＋交易點位": "Candlestick + trade markers",
    # ── 持倉總覽 ──
    "目前沒有持倉，先去新增交易或匯入 CSV！": "No open positions yet. Add a trade or import a CSV to get started!",
    "有 {n} 筆買入紀錄缺少當日 0050 價格": "{n} buy records are missing the same-day 0050 price",
    "🔄 自動補抓": "🔄 Backfill automatically",
    "補抓完成！": "Backfill complete!",
    "0050={b:+.1f}%（你多賺 {d:.1f}%）": "0050={b:+.1f}% (you beat it by {d:.1f}%)",
    "0050={b:+.1f}%（你少賺 {d:.1f}%）": "0050={b:+.1f}% (you trailed by {d:.1f}%)",
    "持股(股)": "Shares",
    "損益(元)": "P/L (NT$)",
    "我的報酬(%)": "My return (%)",
    "若買0050": "vs. buying 0050",
    "近60日RS(%)": "60-day RS (%)",
    "**若買0050** = 同期買 0050 的報酬比較　｜　**近60日RS** = 個股 vs 0050 相對強度":
        "**vs. buying 0050** = your return compared with buying 0050 over the same period　｜　"
        "**60-day RS** = relative strength of the stock vs. 0050",
    "近 60 日相對走勢（起點=100）": "60-day relative performance (start = 100)",
    "0050（大盤）": "0050 (market)",
    "紅線=個股　藍虛線=0050　基準線100=起始點，高於100代表這段期間漲更多":
        "Red line = stock　Blue dotted = 0050　Baseline 100 = starting point; above 100 means it gained more over the period",
    "股價資料抓取失敗": "Failed to fetch price data",
    # ── K 線圖＋交易點位 ──
    "在 K 線上標出你的實際買賣點，直觀回顧進出場位置": "Your actual buys and sells plotted on the candlestick chart, so you can review your entries and exits",
    "請先執行：pip install plotly": "Please run: pip install plotly",
    "時間範圍": "Time range",
    "3個月": "3 months",
    "6個月": "6 months",
    "1年": "1 year",
    "2年": "2 years",
    "自訂": "Custom",
    "起始日": "Start date",
    "結束日": "End date",
    "顯示 EMA 均線": "Show EMA lines",
    "抓取 K 線資料...": "Fetching price data...",
    "K線": "Candles",
    "⚠️ 在 {start} 至 {end} 區間內找不到 {ticker} 的交易紀錄。": "⚠️ No trades found for {ticker} between {start} and {end}.",
    "K 線已載入，但此區間沒有買賣紀錄可標記": "Chart loaded, but there are no trades in this range to mark",
    "買入 {shares}股 @ {price:.2f}<br>理由：{reason}": "Buy {shares} sh @ {price:.2f}<br>Reason: {reason}",
    "賣出 {shares}股 @ {price:.2f}<br>理由：{reason}": "Sell {shares} sh @ {price:.2f}<br>Reason: {reason}",
    "買入(B)": "Buy (B)",
    "賣出(S)": "Sell (S)",
    "{ticker} {name}　K線圖": "{ticker} {name}　Candlestick chart",
    "此區間交易明細": "Trades in this range",
    # 交易明細欄位（formatting.TRADE_COL_LABELS 的中文欄名）
    # ── 技術圖表（stock_chart_widget.py） ──
    "📊 技術圖表分析": "📊 Technical chart",
    "K線 · 成交量 · KD(9) · RSI(5/10) · OBV｜滑鼠移動同步顯示當天數值":
        "Candles · Volume · KD(9) · RSI(5/10) · OBV | hover to see each day's values",
    "股票代號（例：2330、00631L、0050）": "Ticker (e.g. 2330, 00631L, 0050)",
    "輸入代號後按 Enter": "Type a ticker and press Enter",
    "查詢區間": "Period",
    "60 天": "60 days",
    "90 天": "90 days",
    "120 天": "120 days",
    "180 天": "180 days",
    "🔍 查詢": "🔍 Search",
    "👆 輸入股票代號開始分析": "👆 Enter a ticker to start",
    "下載 {ticker} 資料中...": "Downloading {ticker} data...",
    "❌ 無法取得 {ticker} 的資料": "❌ Could not fetch data for {ticker}",
    "開": "O",
    "高": "H",
    "低": "L",
    "收": "C",
    "量": "Vol",
    "5日": "5d",
    "10日": "10d",
    "🔴 K>80 超買紅點  🟢 K<20 超賣綠點  ｜  RSI 橘線=5日、紫線=10日  ｜  X 軸已過濾週末/假日":
        "🔴 K>80 overbought  🟢 K<20 oversold  |  RSI orange = 5-day, purple = 10-day  |  "
        "weekends/holidays removed from the X axis",
    "📖 指標說明": "📖 Indicator guide",
    # stock_chart_widget.INDICATOR_HELP（內容必須與原文完全一致）
    """
**KD（N=9）**
- 🔴 K>80 超買紅點；🟢 K<20 超賣綠點
- K 上穿 D = 黃金交叉；K 下穿 D = 死亡交叉

**RSI（5日 / 10日）**
- 橘色 RSI(5)：反應快，短線訊號靈敏
- 紫色 RSI(10)：較平滑，中線趨勢
- 兩線交叉可作為買賣參考

**OBV 能量潮**
- OBV 創新高 + 股價新高 = 健康；背離 = 警示
""": """
**KD (N=9)**
- 🔴 K>80 overbought; 🟢 K<20 oversold
- K crossing above D = golden cross; K crossing below D = death cross

**RSI (5-day / 10-day)**
- Orange RSI(5): reacts fast, sensitive to short-term signals
- Purple RSI(10): smoother, shows the medium-term trend
- Crossovers between the two lines can serve as buy/sell cues

**OBV (On-Balance Volume)**
- OBV making new highs together with price = healthy; divergence = warning
""",
}
