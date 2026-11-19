"""Account management and guarded project operations."""

import sqlite3
from datetime import datetime, timezone
from hashlib import sha256

import streamlit as st

from src.accounts import DevelopmentStore, InvalidSession, ServiceError, configured_store
from src.brand import brand_banner
from src.i18n import tr, translator
from src.workspace_state import clear, restore, snapshot


def get_store():
    try:
        return configured_store()
    except (ServiceError, OSError, sqlite3.Error):
        st.warning(tr("账户服务暂不可用。"))
        return None


def navigate(page):
    st.session_state["next_page"] = page
    st.rerun()


def show_failure(error):
    if isinstance(error, InvalidSession):
        st.session_state.pop("auth_token", None)
        clear(st.session_state)
    st.error(tr(str(error)) if isinstance(error, ServiceError) else tr("操作失败，请稍后重试。"))


def account_page():
    brand_banner()
    st.subheader(tr("账户"))
    store = get_store()
    if store is None:
        st.info(tr("账户服务尚未配置。游客仍可运行分析和导出文件。"))
    elif isinstance(store, DevelopmentStore):
        st.info(tr("开发账户模式。请勿在公共部署中启用。"))
    token = st.session_state.get("auth_token")
    if store and token:
        try:
            profile = store.profile(token)
            st.write(profile["email"])
            if st.button(tr("退出登录")):
                try:
                    store.logout(token)
                finally:
                    st.session_state.pop("auth_token", None)
                    clear(st.session_state)
                navigate("首页")
            if st.checkbox(tr("确认永久删除账户和项目")) and st.button(tr("删除账户"), type="secondary"):
                store.delete_account(token)
                st.session_state.pop("auth_token", None)
                clear(st.session_state)
                navigate("首页")
            return
        except (ServiceError, sqlite3.Error, OSError) as exc:
            show_failure(exc)
    if store:
        mode = st.radio(tr("账户操作"), ("登录", "注册", "忘记密码"), format_func=translator(), horizontal=True, key="account_action")
        if mode == "忘记密码" and isinstance(store, DevelopmentStore):
            st.info(tr("开发模式不发送密码重置邮件。"))
        else:
            try:
                if mode in ("登录", "注册"):
                    with st.form("credentials", clear_on_submit=True):
                        email = st.text_input(tr("电子邮箱"), max_chars=254)
                        password = st.text_input(tr("密码"), type="password", max_chars=256)
                        submitted = st.form_submit_button(tr(mode))
                    if submitted:
                        if mode == "注册":
                            store.register(email, password)
                            if isinstance(store, DevelopmentStore):
                                st.session_state["auth_token"] = store.login(email, password)
                                navigate("我的项目")
                            st.success(tr("请查收确认邮件，然后登录。"))
                        else:
                            st.session_state["auth_token"] = store.login(email, password)
                            navigate("我的项目")
                else:
                    with st.form("recovery", clear_on_submit=True):
                        email = st.text_input(tr("电子邮箱"), max_chars=254)
                        if st.form_submit_button(tr("发送重置邮件")):
                            store.recover(email)
                            st.success(tr("如账户可用，请查看重置邮件。"))
                    with st.form("change_password", clear_on_submit=True):
                        code = st.text_input(tr("邮件中的重置凭证"), type="password", max_chars=1024)
                        password = st.text_input(tr("新密码"), type="password", max_chars=256)
                        if st.form_submit_button(tr("设置新密码")):
                            store.reset_password(code, password)
                            st.success(tr("密码已更新，请登录。"))
            except (ServiceError, sqlite3.Error, OSError) as exc:
                show_failure(exc)
    if st.button(tr("继续以游客身份使用")):
        navigate("首页")


def save_button():
    if st.button(tr("保存项目"), key="go_to_save"):
        navigate("我的项目" if st.session_state.get("auth_token") else "账户")


def project_fields():
    session = st.session_state
    stages = [label for key, label in (("fasta_result", "FASTA"), ("blast_result", "BLAST"),
                                      ("pairwise_record", "Alignment")) if session.get(key)]
    return (session.get("project_name", "").strip(), session.get("project_species", "").strip(),
            session.get("project_target", "").strip(), " / ".join(stages))


def save_workspace(store, token, allow_create):
    project_id = st.session_state.get("workspace_id")
    if not project_id and not allow_create:
        return
    fields = project_fields()
    document = snapshot(st.session_state)
    fingerprint = sha256(repr(fields).encode() + document.encode()).hexdigest()
    if project_id and fingerprint == st.session_state.get("workspace_digest"):
        return
    st.session_state["workspace_id"] = store.save(token, project_id, fields, document)
    st.session_state["workspace_digest"] = fingerprint
    st.session_state["workspace_saved_at"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


@st.fragment(run_every=120)
def autosave(store, token):
    try:
        if st.session_state.get("workspace_auto"):
            save_workspace(store, token, False)
        if st.session_state.get("workspace_saved_at"):
            st.caption(f'{tr("最近保存")} · {st.session_state["workspace_saved_at"]}')
    except (ServiceError, sqlite3.Error, OSError, ValueError) as exc:
        show_failure(exc)


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if isinstance(value, int) else value


def workspace_page():
    st.title(tr("我的项目"))
    store, token = get_store(), st.session_state.get("auth_token")
    if not store or not token:
        st.info(tr("登录后可保存当前分析。登录过程会保留游客分析。"))
        if st.button(tr("前往登录")):
            navigate("账户")
        return
    try:
        rows = store.list_projects(token)
        search = st.text_input(tr("搜索项目"), max_chars=200)
        shown = [row for row in rows if search.casefold() in
                 " ".join(row[key] for key in ("name", "species", "target")).casefold()]
        if shown:
            names = {"name": "项目名称", "species": "研究物种", "target": "目标基因或基因家族",
                     "state": "分析状态", "created_at": "创建时间", "updated_at": "修改时间"}
            st.dataframe([{tr(name): timestamp(row[key]) if key.endswith("_at") else row[key]
                          for key, name in names.items()} for row in shown], hide_index=True)
            selected = st.selectbox(tr("选择项目"), shown, format_func=lambda row: row["name"])
            confirmed = st.checkbox(tr("打开项目将替换当前分析"))
            if st.button(tr("打开项目"), disabled=not confirmed):
                row = store.load(token, selected["id"])
                state = restore(row["payload"])
                st.session_state["workspace_pending"] = (row, state)
                navigate("我的项目")
            updated_name = st.text_input(tr("重命名为"), max_chars=200)
            if st.button(tr("重命名项目"), disabled=not updated_name.strip()):
                store.rename(token, selected["id"], updated_name.strip())
                if selected["id"] == st.session_state.get("workspace_id"):
                    # Apply before the editor widget is rendered on the next run.
                    st.session_state["project_name"] = updated_name.strip()
                st.rerun()
            if st.checkbox(tr("确认永久删除所选项目")) and st.button(tr("删除项目")):
                store.delete(token, selected["id"])
                if selected["id"] == st.session_state.get("workspace_id"):
                    st.session_state.pop("workspace_id", None)
                st.rerun()
        if st.button(tr("将当前分析另存为新项目")):
            st.session_state.pop("workspace_id", None)
            st.session_state.pop("workspace_saved_at", None)
        for key, label, initial in (
            ("project_name", "项目名称", "项目名称"),
            ("project_species", "研究物种", "研究物种"),
            ("project_target", "目标基因或基因家族", "目标基因或基因家族"),
        ):
            if key not in st.session_state:
                st.session_state[key] = st.session_state.get(f"research_{initial}", "")[:200]
            st.text_input(tr(label), max_chars=200, key=key)
        if st.button(tr("保存当前分析"), type="primary"):
            save_workspace(store, token, True)
            st.success(tr("项目已保存。"))
        st.checkbox(tr("每两分钟自动保存已创建的项目"), key="workspace_auto")
        autosave(store, token)
    except (ServiceError, sqlite3.Error, OSError, ValueError, TypeError, KeyError) as exc:
        show_failure(exc)
