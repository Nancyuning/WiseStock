"""views/analytics.py：績效回顧（已出清持股、賣出後遺憾追蹤、買賣理由統計、週報）。"""

EN = {
    # 分頁
    "📤 已出清持股": "📤 Closed positions",
    "📊 賣出後遺憾追蹤": "📊 Post-sale regret tracker",
    "買賣理由統計": "Trade reason stats",
    "📝 週報": "📝 Weekly report",
    # 已出清持股
    "還沒有任何賣出紀錄": "No sell trades yet",
    "⚠️ {n} 股找不到對應買入紀錄（可能是使用本 app 前的庫存），不計入損益":
        "⚠️ {n} shares have no matching buy record (possibly held before using this app); excluded from P/L",
    "共 {n} 股賣出在系統裡找不到對應的買入紀錄，這部分**不計入**已實現損益（避免把找不到成本的部分誤算成利潤）。":
        "{n} sold shares have no matching buy record in the system. They are **excluded** from realized P/L "
        "(so shares with unknown cost are not counted as profit).",
    "賣出理由統計": "Sell reason stats",
    "目前沒有找得到成本的賣出紀錄可統計": "No sell trades with a known cost basis to analyze yet",
    # 賣出後遺憾追蹤
    "賣出後遺憾追蹤": "Post-sale regret tracker",
    "賣出後大漲 → 你抱不住　｜　賣出後繼續跌 → 停損執行正確":
        "Rallied after you sold → you sold too early　|　Kept falling → your exit was right",
    "還沒有賣出紀錄": "No sell trades yet",
    "😅 賣太早了": "😅 Sold too early",
    "✅ 停損正確": "✅ Good exit",
    "😐 差不多": "😐 About even",
    # 買賣理由統計
    "還沒有足夠的買入紀錄": "Not enough buy trades yet",
    "各買入理由平均報酬": "Average return by buy reason",
    "篩選明細": "Filter details",
    # 週報
    "週報": "Weekly report",
    "本週": "This week",
    "上週": "Last week",
    "{n}週前": "{n} weeks ago",
    "（{start} ～ {end}）": " ({start} – {end})",
    "選擇區間": "Select period",
    "統計區間：{start} ～ {end}": "Period: {start} – {end}",
    "該週交易筆數": "Trades this week",
    "該週買入": "Buys this week",
    "該週賣出（已實現損益）": "Sells this week (realized P/L)",
    "{n} 筆": "{n} trades",
    "這個區間沒有任何交易紀錄": "No trades in this period",
    "該週交易明細": "Trades this week",
    "⚠️ 需要注意的持股": "⚠️ Holdings to watch",
    "警示邏輯調整中，敬請期待": "Alert rules are being refined — coming soon",
    # 表格欄位
    "賣出日": "Sell date",
    "賣出股數": "Shares sold",
    "賣出價": "Sell price",
    "實現損益(元)": "Realized P/L (NT$)",
    "實現報酬(%)": "Realized return (%)",
    "平均報酬(%)": "Avg return (%)",
    "30天後股價": "Price after 30d",
    "30天漲跌": "30d change",
    "60天後股價": "Price after 60d",
    "60天漲跌": "60d change",
    "判定": "Verdict",
    "買入價": "Buy price",
    "損益(%)": "P/L (%)",
    "買入日": "Buy date",
    "平均損益(%)": "Avg P/L (%)",
    "筆數": "Count",
    "近60日RS": "60d RS",
}
