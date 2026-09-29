"""views/research.py（市場研究：市場掃描 / 個股分析 / 技術圖表）與 services/scoring.py（買賣點評分）。"""

EN = {
    # 子分頁
    "市場掃描": "Market scan",
    "個股分析": "Stock analysis",
    "技術圖表": "Charts",

    # 個股分析
    "### 🔍 個股深度分析": "### 🔍 Stock deep dive",
    "輸入股票代號，一次查看技術面評分、籌碼面分析": "Enter a ticker to see its technical score and shareholder analysis in one place",
    "輸入股票代號（例如 2330）": "Enter a ticker (e.g. 2330)",
    "股票代號，例如 2330": "Ticker, e.g. 2330",
    "深度分析": "Analyze",
    "👆 請輸入股票代號開始分析": "👆 Enter a ticker to start",
    "### 📊 買賣點評分": "### 📊 Entry / exit score",
    "計算技術指標...": "Calculating technical indicators...",
    "#### 📈 買點評分": "#### 📈 Entry score",
    "買點分數": "Entry score",
    "#### 📤 賣點評分": "#### 📤 Exit score",
    "賣點風險分": "Exit risk score",
    "⚠️ 評分只反映技術面，不代表未來必然漲跌。停損紀律永遠優先於評分。":
        "⚠️ Scores reflect technicals only and do not predict future prices. "
        "Stop-loss discipline always comes before any score.",
    "無法取得技術指標資料": "Unable to fetch technical indicator data",

    # 評分表欄位（services/scoring.py rows 的 key）
    "條件": "Condition",
    "結果": "Result",
    "得分": "Points",
    "說明": "Details",
    "觸發": "Triggered",
    "風險分": "Risk points",
    "⚠️ 是": "⚠️ Yes",
    "✅ 否": "✅ No",

    # 買點條件
    "RSI 未過熱（<{v}）": "RSI not overbought (<{v})",
    "RSI 未過冷（>{v}）": "RSI not oversold (>{v})",
    "股價站上 EMA20": "Price above EMA20",
    "現價{cur:.2f} vs EMA20={ema20:.2f}": "Price {cur:.2f} vs EMA20={ema20:.2f}",
    "均線多頭排列（EMA20>EMA60>EMA120）": "Bullish MA alignment (EMA20>EMA60>EMA120)",
    "近60日跑贏0050（RS>0）": "Outperformed 0050 over 60 days (RS>0)",
    "距52週高點有空間（<{v}%）": "Room below 52-week high (<{v}%)",
    "距高點{pct:.1f}%": "{pct:.1f}% from high",
    "布林通道位置適中（{lo}%~{hi}%）": "Mid Bollinger Band position ({lo}%–{hi}%)",
    "布林位置{pct:.0f}%": "Bollinger position {pct:.0f}%",

    # 賣點條件
    "RSI 過熱（>{v}）": "RSI overbought (>{v})",
    "接近52週高點（距高點<{v}%）": "Near 52-week high (within {v}%)",
    "短均線跌破長均線（EMA20<EMA60）": "Short MA below long MA (EMA20<EMA60)",
    "布林上緣（>{v}%）": "Upper Bollinger Band (>{v}%)",
    "近60日跑輸0050（RS<0）": "Underperformed 0050 over 60 days (RS<0)",
    "股價跌破 EMA20": "Price below EMA20",

    # 等級
    "A　條件優秀": "A　Excellent setup",
    "B　條件尚可": "B　Decent setup",
    "C　條件普通": "C　Average setup",
    "D　條件不佳": "D　Weak setup",
    "🟢 高風險　多個賣點訊號觸發": "🟢 High risk　multiple exit signals triggered",
    "🟡 中風險　部分賣點條件出現": "🟡 Medium risk　some exit conditions present",
    "🟠 低風險　少數條件觸發": "🟠 Low risk　few conditions triggered",
    "🔴 現在不是明顯賣點": "🔴 Not a clear exit point right now",

    # 籌碼面
    "### 💼 籌碼面分析": "### 💼 Shareholder analysis",
    "##### ⚙️ 大戶/散戶閾值設定": "##### ⚙️ Large / small holder thresholds",
    "**大戶持股 ≥ X 張**": "**Large holders: ≥ X lots**",
    "大戶閾值": "Large holder threshold",
    "**散戶持股 ＜ Y 張**": "**Small holders: < Y lots**",
    "散戶閾值": "Small holder threshold",
    "💡 當前設定：大戶 ≥ {whale} 張、散戶 < {retail} 張":
        "💡 Current setting: large holders ≥ {whale} lots, small holders < {retail} lots",
    "載入籌碼資料...": "Loading shareholder data...",
    "⏳ 抓取 {ticker} 集保資料...": "⏳ Fetching TDCC shareholding data for {ticker}...",
    "❌ 查詢失敗：{err}": "❌ Query failed: {err}",
    "⚠️ 無 {ticker} 集保資料": "⚠️ No TDCC data for {ticker}",
    "無集保資料": "No TDCC data",
    "❌ 分析失敗": "❌ Analysis failed",
    "分析失敗": "Analysis failed",

    # 市場資料載入警告
    "上市": "TWSE",
    "上櫃": "TPEx",
    "[指數] 使用 {d}": "[Index] Using {d}",
    "[指數] {err}": "[Index] {err}",
    "[{label}] 使用 {d}": "[{label}] Using {d}",
    "[法人] 使用 {d}": "[Institutional] Using {d}",
    "[法人] {err}": "[Institutional] {err}",
    "[漲停] {err}": "[Limit-up] {err}",
    "⚠️ {n} 則警告": "⚠️ {n} warnings",

    # HTML 元件
    "❌ 找不到 market_radar_ui.html": "❌ market_radar_ui.html not found",
    "❌ HTML 渲染失敗：{err}": "❌ Failed to render HTML: {err}",
    "🔍 查看錯誤詳情": "🔍 Error details",

    # 市場掃描 / 側邊欄
    "### 📡 類股熱點": "### 📡 Sector heatmap",
    "查詢日期": "Date",
    "🗓️ 休市日，顯示 {date}": "🗓️ Market closed, showing {date}",
    "載入市場資料...": "Loading market data...",
    "加權指數": "TAIEX",
    "上漲": "Advancers",
    "下跌": "Decliners",
    "### 📊 今日焦點": "### 📊 Today's highlights",
    "選擇焦點類型": "Highlight type",
    "漲停股": "Limit-up stocks",
    "法人買賣超": "Institutional net buy/sell",
}
