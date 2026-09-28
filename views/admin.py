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


def render(current_user: dict) -> None:
    if current_user.get("role") != "admin":
        st.error("您沒有管理員權限")
        return

    st.header("帳號管理")

    tab_list, tab_add, tab_pwd, tab_del = st.tabs([
        "用戶列表", "新增用戶", "重設密碼", "刪除用戶"
    ])

    # ── 用戶列表 ──────────────────────────────────────────
    with tab_list:
        users = list_users()
        if not users:
            st.info("目前沒有任何用戶")
        else:
            df = pd.DataFrame(users)
            df["role_label"]   = df["role"].map({"admin": "管理員", "user": "一般用戶"})
            df["status_label"] = df["is_active"].map({1: "啟用", 0: "停用"})
            df["last_login"]   = df["last_login"].fillna("從未登入")
            disp = df[["username", "display_name", "role_label", "status_label",
                        "created_at", "last_login"]].rename(columns={
                "username":     "帳號",
                "display_name": "顯示名稱",
                "role_label":   "角色",
                "status_label": "狀態",
                "created_at":   "建立時間",
                "last_login":   "最後登入",
            })
            st.dataframe(disp, width="stretch", hide_index=True)

        st.divider()
        st.subheader("啟用 / 停用帳號")
        non_admin = [u for u in users if u["username"] != current_user["username"]]
        if not non_admin:
            st.info("沒有其他用戶可管理")
        else:
            toggle_user = st.selectbox(
                "選擇帳號",
                [u["username"] for u in non_admin],
                format_func=lambda x: next(
                    f"{u['username']} ({u['display_name']}, {'啟用' if u['is_active'] else '停用'})"
                    for u in non_admin if u["username"] == x
                ),
                key="toggle_user_sel",
            )
            selected = next((u for u in non_admin if u["username"] == toggle_user), None)
            if selected:
                new_state = not selected["is_active"]
                btn_label = "停用此帳號" if selected["is_active"] else "啟用此帳號"
                btn_type  = "secondary" if selected["is_active"] else "primary"
                if st.button(btn_label, type=btn_type, key="toggle_btn"):
                    update_user_active(toggle_user, new_state)
                    st.success(f"已{'停用' if not new_state else '啟用'} {toggle_user}")
                    st.rerun()

    # ── 新增用戶 ──────────────────────────────────────────
    with tab_add:
        with st.form("add_user_form"):
            n_username     = st.text_input("帳號（英文、不可更改）")
            n_display_name = st.text_input("顯示名稱")
            n_role         = st.selectbox("角色", ["user", "admin"],
                                          format_func=lambda x: "管理員" if x == "admin" else "一般用戶")
            n_password     = st.text_input("初始密碼", type="password")
            n_confirm      = st.text_input("確認密碼", type="password")
            submitted      = st.form_submit_button("建立帳號", type="primary", width="stretch")

            if submitted:
                if not n_username or not n_display_name:
                    st.error("帳號和顯示名稱不可為空")
                elif len(n_password) < 6:
                    st.error("密碼至少 6 個字元")
                elif n_password != n_confirm:
                    st.error("兩次密碼不一致")
                else:
                    ok = create_user(n_username.strip(), n_display_name.strip(),
                                     n_password, role=n_role)
                    if ok:
                        st.success(f"帳號 {n_username} 建立成功！")
                    else:
                        st.error("帳號已存在，請換一個名稱")

    # ── 重設密碼 ──────────────────────────────────────────
    with tab_pwd:
        users = list_users()
        all_usernames = [u["username"] for u in users]
        if not all_usernames:
            st.info("沒有任何用戶")
        else:
            with st.form("reset_pwd_form"):
                r_user    = st.selectbox("選擇帳號", all_usernames,
                                          format_func=lambda x: next(
                                              f"{u['username']} ({u['display_name']})"
                                              for u in users if u["username"] == x
                                          ))
                r_new_pwd = st.text_input("新密碼", type="password")
                r_confirm = st.text_input("確認新密碼", type="password")
                submitted = st.form_submit_button("重設密碼", type="primary", width="stretch")

                if submitted:
                    if len(r_new_pwd) < 6:
                        st.error("密碼至少 6 個字元")
                    elif r_new_pwd != r_confirm:
                        st.error("兩次密碼不一致")
                    else:
                        reset_password(r_user, r_new_pwd)
                        st.success(f"已重設 {r_user} 的密碼")

    # ── 刪除用戶 ──────────────────────────────────────────
    with tab_del:
        users = list_users()
        deletable = [u for u in users if u["role"] != "admin"]
        if not deletable:
            st.info("沒有可刪除的用戶（admin 帳號不可刪除）")
        else:
            d_user = st.selectbox("選擇要刪除的帳號", [u["username"] for u in deletable],
                                   format_func=lambda x: next(
                                       f"{u['username']} ({u['display_name']})"
                                       for u in deletable if u["username"] == x
                                   ),
                                   key="del_user_sel")
            if d_user:
                trade_cnt = get_trade_count(d_user)
                if trade_cnt > 0:
                    st.warning(
                        f"此帳號有 **{trade_cnt}** 筆交易紀錄。"
                        "刪除後這些紀錄不會自動刪除，但將無法透過任何帳號存取。"
                    )
                confirm = st.checkbox(f"我確認要刪除帳號 {d_user}", key="del_confirm")
                if st.button("確認刪除", type="secondary", disabled=not confirm, key="del_exec"):
                    delete_user(d_user)
                    st.success(f"已刪除帳號 {d_user}")
                    st.rerun()
