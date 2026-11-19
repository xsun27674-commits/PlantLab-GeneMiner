"""Authentication and owner-scoped persistence backends."""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

MAX_PROJECT_BYTES = 32 * 1024 * 1024
SESSION_TTL = 12 * 60 * 60


class ServiceError(Exception):
    pass


class InvalidSession(ServiceError):
    pass


def validate_credentials(email, password):
    if len(email) > 254 or "@" not in email or len(password) < 12 or len(password) > 256:
        raise ServiceError("电子邮箱无效，或密码长度不在 12–256 字符范围内。")


def digest(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


SUPABASE_HTTP = build_opener(NoRedirect)


class DevelopmentStore:
    """Explicitly enabled server-side development store, backed by a real file."""

    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch(mode=0o600, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, salt BLOB NOT NULL, hash BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    expiry INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, species TEXT NOT NULL, target TEXT NOT NULL, state TEXT NOT NULL,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, payload TEXT NOT NULL
                );
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, email, password):
        validate_credentials(email, password)
        salt = secrets.token_bytes(32)
        try:
            with self.connection() as db:
                db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?)",
                           (str(uuid4()), email.strip().casefold(), salt, digest(password, salt)))
        except sqlite3.IntegrityError as exc:
            raise ServiceError("无法注册此邮箱。") from exc

    def login(self, email, password):
        if len(email) > 254 or len(password) > 256:
            raise ServiceError("邮箱或密码不正确。")
        with self.connection() as db:
            account = db.execute("SELECT * FROM accounts WHERE email=?", (email.strip().casefold(),)).fetchone()
            salt = account["salt"] if account else bytes(32)
            expected = account["hash"] if account else bytes(32)
            if not hmac.compare_digest(digest(password, salt), expected) or not account:
                raise ServiceError("邮箱或密码不正确。")
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expiry <= ?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                       (self.token_hash(token), account["id"], int(time.time()) + SESSION_TTL))
            return token

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def owner(self, db, token):
        row = db.execute("""
            SELECT a.id, a.email FROM accounts a JOIN sessions s ON a.id=s.owner
            WHERE s.token=? AND s.expiry>?""", (self.token_hash(token), int(time.time()))).fetchone()
        if not row:
            raise InvalidSession("会话已失效，请重新登录。")
        return dict(row)

    def profile(self, token):
        with self.connection() as db:
            return self.owner(db, token)

    def logout(self, token):
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (self.token_hash(token),))

    def delete_account(self, token):
        with self.connection() as db:
            db.execute("DELETE FROM accounts WHERE id=?", (self.owner(db, token)["id"],))

    def list_projects(self, token):
        with self.connection() as db:
            return [dict(row) for row in db.execute("""
                SELECT id,name,species,target,state,created_at,updated_at FROM projects
                WHERE owner=? ORDER BY updated_at DESC""", (self.owner(db, token)["id"],))]

    def load(self, token, project_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM projects WHERE owner=? AND id=?",
                             (self.owner(db, token)["id"], project_id)).fetchone()
            if row is None:
                raise ServiceError("找不到项目。")
            return dict(row)

    def save(self, token, project_id, fields, payload):
        validate_project(fields, payload)
        timestamp = int(time.time())
        with self.connection() as db:
            owner = self.owner(db, token)["id"]
            if project_id is None:
                project_id = str(uuid4())
                db.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (project_id, owner, *fields, timestamp, timestamp, payload))
            else:
                found = db.execute("""
                    UPDATE projects SET name=?, species=?, target=?, state=?, updated_at=?, payload=?
                    WHERE owner=? AND id=?""", (*fields, timestamp, payload, owner, project_id))
                if not found.rowcount:
                    raise ServiceError("找不到项目。")
        return project_id

    def rename(self, token, project_id, name):
        validate_project((name, "", "", ""), "")
        with self.connection() as db:
            found = db.execute("UPDATE projects SET name=?,updated_at=? WHERE owner=? AND id=?",
                               (name, int(time.time()), self.owner(db, token)["id"], project_id))
            if not found.rowcount:
                raise ServiceError("找不到项目。")

    def delete(self, token, project_id):
        with self.connection() as db:
            db.execute("DELETE FROM projects WHERE owner=? AND id=?", (self.owner(db, token)["id"], project_id))


def validate_project(fields, payload):
    if not fields[0].strip() or any(len(field) > 200 for field in fields):
        raise ServiceError("项目名称不能为空，元数据每项不得超过 200 字符。")
    if len(payload.encode()) > MAX_PROJECT_BYTES:
        raise ServiceError("项目超过 32 MB 保存上限。请拆分数据后重试。")


class SupabaseStore:
    """Use Supabase Auth and end-user JWTs. PostgreSQL owns the authorization decision."""

    def __init__(self, endpoint, public_key):
        parts = urlsplit(endpoint)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ServiceError("Supabase 需配置有效的 HTTPS 地址。")
        self.endpoint = endpoint.rstrip("/")
        if public_key.startswith("sb_secret_"):
            raise ServiceError("Supabase 只接受公开客户端密钥。")
        try:
            from base64 import urlsafe_b64decode
            encoded = public_key.split(".")[1]
            role = json.loads(urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))).get("role")
        except (ValueError, IndexError):
            role = None
        if role == "service_role":
            raise ServiceError("Supabase 只接受公开客户端密钥。")
        self.public_key = public_key

    def request(self, method, path, token=None, body=None, representation=False):
        headers = {"apikey": self.public_key, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if representation:
            headers["Prefer"] = "return=representation"
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request = Request(self.endpoint + path, data=data, headers=headers, method=method)
        try:
            with SUPABASE_HTTP.open(request, timeout=20) as response:
                raw = response.read(MAX_PROJECT_BYTES + 2 * 1024 * 1024)
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            if exc.code == 401 and token:
                raise InvalidSession("会话已失效，请重新登录。") from None
            raise ServiceError("服务未完成请求，请检查输入或稍后重试。") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise ServiceError("暂时无法连接账户或项目服务。") from None

    def register(self, email, password):
        validate_credentials(email, password)
        self.request("POST", "/auth/v1/signup", body={"email": email, "password": password})

    def login(self, email, password):
        if len(email) > 254 or len(password) > 256:
            raise ServiceError("邮箱或密码不正确。")
        return self.request("POST", "/auth/v1/token?grant_type=password",
                            body={"email": email, "password": password})["access_token"]

    def recover(self, email):
        if len(email) > 254 or "@" not in email:
            raise ServiceError("请输入有效的电子邮箱。")
        self.request("POST", "/auth/v1/recover", body={"email": email})

    def reset_password(self, token_hash, password):
        validate_credentials("recovery@example.invalid", password)
        if not token_hash or len(token_hash) > 1024:
            raise ServiceError("请输入有效的重置凭证。")
        verified = self.request("POST", "/auth/v1/verify", body={"type": "recovery", "token_hash": token_hash})
        self.request("PUT", "/auth/v1/user", verified["access_token"], {"password": password})

    def logout(self, token):
        self.request("POST", "/auth/v1/logout?scope=local", token)

    def profile(self, token):
        profile = self.request("GET", "/auth/v1/user", token)
        metadata = profile.get("user_metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        return {"id": profile["id"], "email": profile["email"],
                "nickname": metadata.get("nickname") or metadata.get("full_name") or metadata.get("name"),
                "avatar_url": metadata.get("avatar_url")}

    def delete_account(self, token):
        self.request("POST", "/rest/v1/rpc/delete_geneminer_account", token, {})

    @staticmethod
    def project_path(project_id=None, **query):
        if project_id is not None:
            query["id"] = f"eq.{project_id}"
        return "/rest/v1/geneminer_projects?" + urlencode(query)

    def list_projects(self, token):
        return self.request("GET", self.project_path(select="id,name,species,target,state,created_at,updated_at",
                                                    order="updated_at.desc"), token)

    def load(self, token, project_id):
        rows = self.request("GET", self.project_path(project_id, limit=1), token)
        if not rows:
            raise ServiceError("找不到项目。")
        return rows[0]

    def save(self, token, project_id, fields, payload):
        validate_project(fields, payload)
        body = dict(zip(("name", "species", "target", "state"), fields))
        body["payload"] = payload
        rows = self.request("POST" if project_id is None else "PATCH",
                            self.project_path(project_id, select="id"), token, body, True)
        if not rows:
            raise ServiceError("找不到项目。")
        return rows[0]["id"]

    def rename(self, token, project_id, name):
        validate_project((name, "", "", ""), "")
        if not self.request("PATCH", self.project_path(project_id, select="id"), token, {"name": name}, True):
            raise ServiceError("找不到项目。")

    def delete(self, token, project_id):
        self.request("DELETE", self.project_path(project_id), token)


def configured_store():
    endpoint = os.environ.get("GENEMINER_SUPABASE_URL")
    public_key = os.environ.get("GENEMINER_SUPABASE_PUBLIC_KEY")
    development_path = os.environ.get("GENEMINER_DEV_DB")
    if endpoint or public_key:
        if not (endpoint and public_key):
            raise ServiceError("账户服务配置不完整。")
        return SupabaseStore(endpoint, public_key)
    if development_path:
        return DevelopmentStore(development_path)
    return None
