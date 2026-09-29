"""
views/admin.py
帳號管理頁面（僅 admin 角色可見）
"""
import pandas as pd
import streamlit as st

from auth import (
    list_users, create_user, update_user_active,
    reset_password, delete_user, get_trade_count,
)
from i18n import t, t_cols


def _role_label(role: str) -> str:
    return t("管理員") if role == "admin" else t("一般用戶")


def _status_label(active) -> str:
    return t("啟用") if active else t("停用")


def render(current_user: dict) -> None:
    if current_user.get("role") != "admin":
        st.error(t("您沒有管理員權限"))
        return

    st.header(t("帳號管理"))

    tab_list, tab_add, tab_pwd, tab_del = st.tabs([
        t("用戶列表"), t("新增用戶"), t("重設密碼"), t("刪除用戶")
    ])

    # ── 用戶列表 ──────────────────────────────────────────
    with tab_list:
        users = list_users()
        if not users:
            st.info(t("目前沒有任何用戶"))
        else:
            df = pd.DataFrame(users)
            df["role_label"]   = df["role"].map(_role_label)
            df["status_label"] = df["is_active"].map(_status_label)
            df["last_login"]   = df["last_login"].fillna(t("從未登入"))
            disp = df[["username", "display_name", "role_label", "status_label",
                        "created_at", "last_login"]].rename(columns={
                "username":     "帳號",
                "display_name": "顯示名稱",
                "role_label":   "角色",
                "status_label": "狀態",
                "created_at":   "建立時間",
                "last_login":   "最後登入",
            })
            st.dataframe(t_cols(disp), width="stretch", hide_index=True)

        st.divider()
        st.subheader(t("啟用 / 停用帳號"))
        non_admin = [u for u in users if u["username"] != current_user["username"]]
        if not non_admin:
            st.info(t("沒有其他用戶可管理"))
        else:
            toggle_user = st.selectbox(
                t("選擇帳號"),
                [u["username"] for u in non_admin],
                format_func=lambda x: next(
                    f"{u['username']} ({u['display_name']}, {_status_label(u['is_active'])})"
                    for u in non_admin if u["username"] == x
                ),
                key="toggle_user_sel",
            )
            selected = next((u for u in non_admin if u["username"] == toggle_user), None)
            if selected:
                new_state = not selected["is_active"]
                btn_label = t("停用此帳號") if selected["is_active"] else t("啟用此帳號")
                btn_type  = "secondary" if selected["is_active"] else "primary"
                if st.button(btn_label, type=btn_type, key="toggle_btn"):
                    update_user_active(toggle_user, new_state)
                    st.success(t("已停用 {user}", user=toggle_user) if not new_state
                               else t("已啟用 {user}", user=toggle_user))
                    st.rerun()

    # ── 新增用戶 ──────────────────────────────────────────
    with tab_add:
        with st.form("add_user_form"):
            n_username     = st.text_input(t("帳號（英文、不可更改）"))
            n_display_name = st.text_input(t("顯示名稱"))
            n_role         = st.selectbox(t("角色"), ["user", "admin"], format_func=_role_label)
            n_password     = st.text_input(t("初始密碼"), type="password")
            n_confirm      = st.text_input(t("確認密碼"), type="password")
            submitted      = st.form_submit_button(t("建立帳號"), type="primary", width="stretch")

            if submitted:
                if not n_username or not n_display_name:
                    st.error(t("帳號和顯示名稱不可為空"))
                elif len(n_password) < 6:
                    st.error(t("密碼至少 6 個字元"))
                elif n_password != n_confirm:
                    st.error(t("兩次密碼不一致"))
                else:
                    ok = create_user(n_username.strip(), n_display_name.strip(),
                                     n_password, role=n_role)
                    if ok:
                        st.success(t("帳號 {user} 建立成功！", user=n_username))
                    else:
                        st.error(t("帳號已存在，請換一個名稱"))

    # ── 重設密碼 ──────────────────────────────────────────
    with tab_pwd:
        users = list_users()
        all_usernames = [u["username"] for u in users]
        if not all_usernames:
            st.info(t("沒有任何用戶"))
        else:
            with st.form("reset_pwd_form"):
                r_user    = st.selectbox(t("選擇帳號"), all_usernames,
                                          format_func=lambda x: next(
                                              f"{u['username']} ({u['display_name']})"
                                              for u in users if u["username"] == x
                                          ))
                r_new_pwd = st.text_input(t("新密碼"), type="password")
                r_confirm = st.text_input(t("確認新密碼"), type="password")
                submitted = st.form_submit_button(t("重設密碼"), type="primary", width="stretch")

                if submitted:
                    if len(r_new_pwd) < 6:
                        st.error(t("密碼至少 6 個字元"))
                    elif r_new_pwd != r_confirm:
                        st.error(t("兩次密碼不一致"))
                    else:
                        reset_password(r_user, r_new_pwd)
                        st.success(t("已重設 {user} 的密碼", user=r_user))

    # ── 刪除用戶 ──────────────────────────────────────────
    with tab_del:
        users = list_users()
        deletable = [u for u in users if u["role"] != "admin"]
        if not deletable:
            st.info(t("沒有可刪除的用戶（admin 帳號不可刪除）"))
        else:
            d_user = st.selectbox(t("選擇要刪除的帳號"), [u["username"] for u in deletable],
                                   format_func=lambda x: next(
                                       f"{u['username']} ({u['display_name']})"
                                       for u in deletable if u["username"] == x
                                   ),
                                   key="del_user_sel")
            if d_user:
                trade_cnt = get_trade_count(d_user)
                if trade_cnt > 0:
                    st.warning(t(
                        "此帳號有 **{n}** 筆交易紀錄。刪除後這些紀錄不會自動刪除，但將無法透過任何帳號存取。",
                        n=trade_cnt,
                    ))
                confirm = st.checkbox(t("我確認要刪除帳號 {user}", user=d_user), key="del_confirm")
                if st.button(t("確認刪除"), type="secondary", disabled=not confirm, key="del_exec"):
                    delete_user(d_user)
                    st.success(t("已刪除帳號 {user}", user=d_user))
                    st.rerun()
