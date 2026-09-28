"""
app.py — 台股追蹤平台　唯一入口
啟動方式：streamlit run app.py

架構：
  app.py          ← 此檔，只負責：page config / 快取 / 共用工具 / 導覽
  views/
    monitor.py    ← 監控中心
    research.py   ← 市場研究（技術分析 + 市場雷達）
    trades.py     ← 紀錄維護
    analytics.py  ← 績效回顧
    admin.py      ← 帳號管理（管理員專用）
  auth.py         ← 帳號認證
  database.py     ← trades.db（交易紀錄）
  market_radar_db.py  ← market_radar.db（集保歷史）
  stock_data.py       ← yfinance API
  market_radar_data.py ← TWSE / 集保 API
  data/           ← 所有 .db 與快取，統一存放
"""

from pathlib import Path
import streamlit as st
from streamlit_option_menu import option_menu

# ── 確保 data/ 存在 ──────────────────────────────────────
Path("data").mkdir(exist_ok=True)

# ── DB 初始化 ─────────────────────────────────────────────
from auth import init_auth_db, verify_password, update_last_login, reset_password as auth_reset_password
from demo import demo_enabled, demo_user, is_demo, ensure_demo_trades
init_auth_db()

from database import init_db
init_db()

from market_radar_db import init_db as radar_init_db
radar_init_db()

# ── 頁面基本設定 ──────────────────────────────────────────
st.set_page_config(page_title="台股追蹤平台", page_icon="📈", layout="wide")

# ── 全域 CSS ──────────────────────────────────────────────
st.markdown("""
<style>
html, body, [class*="st-"] { font-size: 15px; }
.stDataFrame div[data-testid="stTable"] { font-size: 14px !important; }
button[data-baseweb="tab"] p { font-size: 16px !important; font-weight: 500; }
.stSidebar .stMarkdown { font-size: 15px; }
.stSelectbox label p, .stTextInput label p {
    font-size: 15px !important; font-weight: bold;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# 登入頁
# ══════════════════════════════════════════════════════════
def _render_login():
    st.title("📈 台股追蹤平台")
    st.caption("請先登入")
    st.divider()

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("帳號")
            password = st.text_input("密碼", type="password")
            submitted = st.form_submit_button("登入", width="stretch", type="primary")

        if submitted:
            user = verify_password(username, password)
            if user:
                update_last_login(user["username"])
                st.session_state["user"] = user
                st.rerun()
            else:
                st.error("帳號或密碼錯誤，或帳號已停用")

        if demo_enabled():
            st.markdown("<div style='text-align:center;color:#888;margin:8px 0'>或</div>",
                        unsafe_allow_html=True)
            if st.button("👀 以訪客身分瀏覽 Demo", width="stretch"):
                ensure_demo_trades()
                st.session_state["user"] = demo_user()
                st.rerun()
            st.caption("Demo 使用虛構的交易紀錄，所有修改功能皆已停用。")


if "user" not in st.session_state:
    _render_login()
    st.stop()

user     = st.session_state["user"]
user_id  = user["username"]
readonly = is_demo(user)

# ── 清除舊版快取（首次運行新版時）────────────────────────
if "v2_cache_cleared" not in st.session_state:
    st.cache_data.clear()
    st.session_state.v2_cache_cleared = True

st.title("📈 台股追蹤平台")
st.caption("v2.0　監控 · 研究 · 紀錄 · 回顧")

# ── 導覽列 ────────────────────────────────────────────────
pages = ["監控中心", "市場研究", "紀錄維護", "績效回顧"]
icons = ["speedometer2", "search", "database-fill-gear", "graph-up-arrow"]
if user["role"] == "admin":
    pages.append("帳號管理")
    icons.append("people-fill")

selected_main = option_menu(
    menu_title=None,
    options=pages,
    icons=icons,
    orientation="horizontal",
    styles={
        "container": {"padding": "0!important", "background-color": "transparent"},
        "nav-link":  {"font-size": "16px", "text-align": "center"},
    }
)

# ── Sidebar ───────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"**{user['display_name']}**")
    st.caption({"admin": "管理員", "demo": "Demo 訪客（唯讀）"}.get(user["role"], "一般用戶"))

    if st.button("登出", width="stretch"):
        del st.session_state["user"]
        st.rerun()

    if not readonly:
        st.divider()
        st.header("修改密碼")
        with st.form("change_pwd_form"):
            old_pwd  = st.text_input("目前密碼", type="password")
            new_pwd  = st.text_input("新密碼（至少 6 字元）", type="password")
            new_pwd2 = st.text_input("確認新密碼", type="password")
            pwd_btn  = st.form_submit_button("更新密碼", width="stretch")
        if pwd_btn:
            from auth import verify_password as _vp
            if not _vp(user_id, old_pwd):
                st.sidebar.error("目前密碼錯誤")
            elif len(new_pwd) < 6:
                st.sidebar.error("新密碼至少 6 個字元")
            elif new_pwd != new_pwd2:
                st.sidebar.error("兩次密碼不一致")
            else:
                auth_reset_password(user_id, new_pwd)
                st.sidebar.success("密碼已更新")

    st.divider()
    st.header("🛠️ 系統管理")
    if st.button("🗑️ 清除快取", help="清除所有股票名稱、價格等快取資料"):
        st.cache_data.clear()
        st.success("✅ 快取已清除！")
        st.rerun()

    st.divider()
    st.caption("本工具僅供個人交易紀錄與研究使用，所有數據與指標不構成任何投資建議，投資盈虧請自行負責。")

# ══════════════════════════════════════════════════════════
# 共用快取函式
# ══════════════════════════════════════════════════════════
from stock_data import (
    get_current_price, get_relative_strength, get_price_history,
    get_stock_name, get_market_level, get_price_on_date,
    get_price_after_sell, stress_test, calc_forward_pe,
    check_stock_health, get_market_risk_score, check_stock_signals,
)

@st.cache_data(ttl=3600, show_spinner=False)
def cached_name(ticker):
    """取得股票中文名稱 - v2.0"""
    return get_stock_name(ticker)

@st.cache_data(ttl=300)
def cached_price(t):   return get_current_price(t)

@st.cache_data(ttl=300)
def cached_rs(t):      return get_relative_strength(t)

@st.cache_data(ttl=300)
def cached_hist(t):    return get_price_history(t)

@st.cache_data(ttl=3600)
def cached_market(d=None): return get_market_level(d)

# ══════════════════════════════════════════════════════════
# 路由
# ══════════════════════════════════════════════════════════
if selected_main == "監控中心":
    from views.monitor import render as render_monitor
    render_monitor(
        cached_name=cached_name,
        cached_price=cached_price,
        cached_rs=cached_rs,
        cached_hist=cached_hist,
        user_id=user_id,
        readonly=readonly,
    )

elif selected_main == "市場研究":
    from views.research import render as render_research
    render_research(
        cached_name=cached_name,
        cached_price=cached_price,
        user_id=user_id,
    )

elif selected_main == "紀錄維護":
    from views.trades import render as render_trades
    render_trades(
        cached_market=cached_market,
        user_id=user_id,
        readonly=readonly,
    )

elif selected_main == "績效回顧":
    from views.analytics import render as render_analytics
    render_analytics(
        cached_name=cached_name,
        cached_price=cached_price,
        cached_rs=cached_rs,
        get_price_after_sell=get_price_after_sell,
        user_id=user_id,
    )

elif selected_main == "帳號管理":
    from views.admin import render as render_admin
    render_admin(current_user=user)
