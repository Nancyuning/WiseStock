"""views/trades.py、views/admin.py、services/trade_service.py：交易紀錄維護與帳號管理。"""

EN = {
    # ── 交易紀錄：分頁與共用 ────────────────────────────────
    "👀 Demo 模式：交易紀錄為虛構範例，新增、匯入、編輯、刪除功能已停用。":
        "👀 Demo mode: these trades are fictional; adding, importing, editing and deleting are disabled.",
    "✏️ 手動新增單筆": "✏️ Add a trade",
    "⬆️ 批次匯入 CSV": "⬆️ Import CSV",
    "📋 交易紀錄": "📋 Trade history",
    "所有交易紀錄": "All trades",

    # ── 手動新增 ────────────────────────────────────────────
    "判斷大盤位階...": "Checking market level...",
    "**今日大盤：** {label}　｜　0050 現價 {price}　｜　距52週高點 {pct}%":
        "**Market today:** {label}　|　0050 price {price}　|　{pct}% from 52-week high",
    "買賣方向": "Side",
    "交易日期": "Trade date",
    "股票代號（例如：0050、2330、00981A）": "Ticker (e.g. 0050, 2330, 00981A)",
    "成交價格（元）": "Price (TWD)",
    "股數（零股直接填）": "Shares (odd lots allowed)",
    "當時大盤位階（自動判斷）": "Market level at the time (auto-detected)",
    "停損價（元，選填）": "Stop-loss price (TWD, optional)",
    "目標價（元，選填）": "Target price (TWD, optional)",
    "預估今年 EPS（元，選填）": "Estimated EPS this year (TWD, optional)",
    "填入後自動計算 Forward P/E": "Used to calculate forward P/E",
    "備註（選填）": "Notes (optional)",
    "✅ 儲存這筆交易": "✅ Save trade",
    "✅ {direction} {ticker} {shares}股 @ {price}（合計 {total} 元）":
        "✅ {direction} {ticker} {shares} shares @ {price} (total TWD {total})",
    "當日 0050：{price} 元": "0050 on that day: TWD {price}",
    "Forward P/E：{pe}x": "Forward P/E: {pe}x",
    "請輸入股票代號": "Please enter a ticker",
    "請輸入成交價格": "Please enter a price",
    "請輸入股數": "Please enter the number of shares",

    # ── CSV 匯入 ────────────────────────────────────────────
    """
#### 格式說明
| 欄位 | 必填 | 說明 |
|------|------|------|
| `date` | ✅ | 日期，支援 `2024-01-15` 或 `2024/01/15` |
| `ticker` | ✅ | 代號，如 `0050`、`00981A` |
| `direction` | ✅ | `買入` 或 `賣出`（也接受 `Buy` / `Sell`） |
| `price` | ✅ | 成交價格（支援 `2,500` 含逗號格式） |
| `shares` | ✅ | 股數 |
| `reason` | ❌ | 買入理由 |
| `exit_reason` | ❌ | 賣出理由 |
| `stop_loss` | ❌ | 停損價 |
| `target_price` | ❌ | 目標價 |
| `notes` | ❌ | 備註 |
""": """
#### CSV format
| Column | Required | Description |
|------|------|------|
| `date` | ✅ | Date, `2024-01-15` or `2024/01/15` |
| `ticker` | ✅ | Ticker, e.g. `0050`, `00981A` |
| `direction` | ✅ | `Buy` or `Sell` |
| `price` | ✅ | Price (thousands separators like `2,500` are fine) |
| `shares` | ✅ | Number of shares |
| `reason` | ❌ | Buy reason (e.g. `Dollar-cost averaging`) |
| `exit_reason` | ❌ | Sell reason (e.g. `Target reached`) |
| `stop_loss` | ❌ | Stop-loss price |
| `target_price` | ❌ | Target price |
| `notes` | ❌ | Notes |
""",
    "⬇️ 下載 CSV 模板": "⬇️ Download CSV template",
    "上傳 CSV 檔案": "Upload CSV file",
    "缺少必要欄位：{cols}": "Missing required columns: {cols}",
    "direction 欄位有誤（只接受「買入」或「賣出」）：": "Invalid direction values (only Buy or Sell are accepted):",
    "以下 {n} 筆代號格式可能有誤，請確認：": "{n} row(s) have tickers that look invalid. Please check:",
    "確認代號正確，忽略警告": "Tickers are correct, ignore the warning",
    "以下幾筆價格有問題：": "These rows have invalid prices:",
    "✅ 驗證通過，共 {n} 筆，預覽如下：": "✅ Validation passed: {n} row(s). Preview:",
    "自動補抓買入當天 0050 價格（較慢）": "Fetch the 0050 price on each buy date (slower)",
    "✅ 確認匯入": "✅ Import",
    "匯入中...": "Importing...",
    "🎉 成功匯入 {n} 筆！": "🎉 Imported {n} trade(s)!",
    "讀取失敗：{error}": "Could not read the file: {error}",

    # ── 交易紀錄列表 ────────────────────────────────────────
    "🔍 搜尋股票代號或名稱": "🔍 Search by ticker or name",
    "例如：0050、台積電": "e.g. 0050, 2330",
    "理由篩選": "Reason",
    "共 {n} 筆（總計 {total} 筆）": "Showing {n} of {total}",
    "⬇️ 匯出 CSV": "⬇️ Export CSV",
    "合計(元)": "Total (TWD)",

    # ── 編輯 / 刪除 ────────────────────────────────────────
    "✏️ 編輯紀錄": "✏️ Edit",
    "🗑️ 刪除紀錄": "🗑️ Delete",
    "🔍 搜尋要編輯的紀錄（輸入代號、日期或方向）": "🔍 Find the trade to edit (ticker, date or side)",
    "🔍 搜尋要刪除的紀錄（輸入代號、日期或方向）": "🔍 Find the trade to delete (ticker, date or side)",
    "沒有符合條件的紀錄": "No matching trades",
    "選擇紀錄": "Select trade",
    "{date}　{direction}　{ticker}　{price}元　{shares}股": "{date}　{direction}　{ticker}　TWD {price}　{shares} shares",
    "股票代號": "Ticker",
    "成交價格": "Price",
    "💾 儲存修改": "💾 Save changes",
    "✅ 已儲存修改！": "✅ Changes saved!",
    "確定要刪除這筆紀錄嗎？此操作無法復原。": "Delete this trade? This cannot be undone.",
    "🗑️ 確認刪除": "🗑️ Delete",
    "已刪除": "Deleted",

    # ── 帳號管理 ────────────────────────────────────────────
    "您沒有管理員權限": "You don't have administrator access",
    "用戶列表": "Users",
    "新增用戶": "Add user",
    "重設密碼": "Reset password",
    "刪除用戶": "Delete user",
    "目前沒有任何用戶": "No users yet",
    "啟用": "Active",
    "停用": "Disabled",
    "從未登入": "Never",
    "顯示名稱": "Display name",
    "角色": "Role",
    "狀態": "Status",
    "最後登入": "Last sign-in",
    "啟用 / 停用帳號": "Enable / disable accounts",
    "沒有其他用戶可管理": "No other users to manage",
    "選擇帳號": "Select user",
    "停用此帳號": "Disable this account",
    "啟用此帳號": "Enable this account",
    "已停用 {user}": "Disabled {user}",
    "已啟用 {user}": "Enabled {user}",
    "帳號（英文、不可更改）": "Username (letters/numbers, cannot be changed)",
    "初始密碼": "Initial password",
    "確認密碼": "Confirm password",
    "建立帳號": "Create account",
    "帳號和顯示名稱不可為空": "Username and display name are required",
    "密碼至少 6 個字元": "Password must be at least 6 characters",
    "帳號 {user} 建立成功！": "Account {user} created!",
    "帳號已存在，請換一個名稱": "That username is taken. Please choose another",
    "沒有任何用戶": "No users",
    "新密碼": "New password",
    "已重設 {user} 的密碼": "Password reset for {user}",
    "沒有可刪除的用戶（admin 帳號不可刪除）": "No users to delete (admin accounts cannot be deleted)",
    "選擇要刪除的帳號": "Select the account to delete",
    "此帳號有 **{n}** 筆交易紀錄。刪除後這些紀錄不會自動刪除，但將無法透過任何帳號存取。":
        "This account has **{n}** trade(s). They won't be deleted, but no account will be able to access them.",
    "我確認要刪除帳號 {user}": "I confirm deleting account {user}",
    "確認刪除": "Delete",
    "已刪除帳號 {user}": "Deleted account {user}",
}
