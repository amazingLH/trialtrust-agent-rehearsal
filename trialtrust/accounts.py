"""Local SQLite accounts; opaque revocable sessions and browser registration binding.

The browser marker limits a browser profile, not a physical device. It is never
an authentication factor. Account passwords and recovery codes never reach logs.
"""
from __future__ import annotations

import hashlib
import errno
import logging
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from uuid import uuid4

import bcrypt
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


SESSION_SECONDS = 8 * 3600
DEVICE_SECONDS = 365 * 86400
COOKIE = "trialtrust_account"
DEVICE_COOKIE = "trialtrust_browser"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(strict=True, min_length=3, max_length=32)
    password: str = Field(strict=True, min_length=10, max_length=72)

    @field_validator("username")
    @classmethod
    def username_format(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", value):
            raise ValueError("用户名需为3—32位字母、数字或下划线")
        return value

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码UTF-8编码不能超过72字节")
        return value


class Registration(Credentials):
    confirm_password: str = Field(strict=True, max_length=72)
    import_history: StrictBool = False

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("两次密码不一致")
        return self


class Recovery(Credentials):
    recovery_code: str = Field(strict=True, min_length=30, max_length=100)
    confirm_password: str = Field(strict=True, max_length=72)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("两次密码不一致")
        return self


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(strict=True, min_length=1, max_length=72)
    new_password: str = Field(strict=True, min_length=10, max_length=72)

    @field_validator("current_password", "new_password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码不能超过72字节")
        return value


class Accounts:
    def __init__(self, store):
        self.store = store
        self.boot_id = str(uuid4())
        self.file_modes_managed = False
        # sqlite.backup makes a transactionally consistent private snapshot.
        if store.path.exists() and store.path.stat().st_size:
            backup = store.root / "backups"
            backup.mkdir(mode=0o700, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            target = backup / ("before-start-" + stamp + ".sqlite")
            if not target.exists():
                with store.connect() as src, sqlite3.connect(target) as dst:
                    src.backup(dst)
                self.protect_file(target)
            for old in sorted(backup.glob("before-start-*.sqlite"))[:-3]:
                old.unlink()
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS account_users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL,
                    username_key TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
                    recovery_hash TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS account_sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    expires REAL NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS account_session_user ON account_sessions(user_id);
                CREATE TABLE IF NOT EXISTS browser_devices (
                    token_hash TEXT PRIMARY KEY, user_id TEXT UNIQUE, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS auth_limits (
                    key TEXT PRIMARY KEY, hits INTEGER NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS storage_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO storage_metadata VALUES ('storage_id',?)", (str(uuid4()),))
        self.protect_file(store.path)
        # Unknown usernames still incur the same bcrypt verification work.
        self.dummy_hash = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt(rounds=12))

    def protect_file(self, path):
        try:
            path.chmod(0o600)
        except OSError as exc:
            # Managed mounts can support normal SQLite I/O but reject Unix
            # mode changes. Their access policy remains platform-controlled;
            # no database/backup is exposed through an application file route.
            if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP}:
                raise
            self.file_modes_managed = True
            logging.getLogger("trialtrust.storage").warning("Mounted file permissions are managed by the hosting platform")

    @staticmethod
    def managed(request):
        return getattr(request.app.state, "studio_ui", False)

    def token(self, request):
        header = request.headers.get("x-trialtrust-account") if self.managed(request) else None
        return header or request.cookies.get(COOKIE)

    def device_token(self, request):
        header = request.headers.get("x-trialtrust-browser") if self.managed(request) else None
        return header or request.cookies.get(DEVICE_COOKIE)

    def current(self, request):
        token = self.token(request)
        if not token or len(token) > 100:
            return None
        with self.store.connect() as db:
            row = db.execute("""SELECT u.id,u.username FROM account_users u
                JOIN account_sessions s ON s.user_id=u.id
                WHERE s.token_hash=? AND s.expires>?""", (digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def require(self, request):
        user = self.current(request)
        if not user:
            raise HTTPException(401, "请先登录试托账号")
        return user

    def limit(self, key, maximum, seconds):
        now = time.time()
        blocked = False
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM auth_limits WHERE expires<=?", (now,))
            row = db.execute("SELECT hits FROM auth_limits WHERE key=?", (key,)).fetchone()
            if row and row[0] >= maximum:
                blocked = True
            else:
                db.execute("""INSERT INTO auth_limits VALUES (?,1,?)
                    ON CONFLICT(key) DO UPDATE SET hits=hits+1""", (key, now + seconds))
        if blocked:
            raise HTTPException(429, "操作过于频繁，请稍后再试", headers={"Retry-After": str(seconds)})

    def request_limit(self, request, operation, maximum=20, seconds=900):
        host = request.client.host if request.client else "unknown"
        self.limit(operation + ":" + digest(host), maximum, seconds)

    def set_cookie(self, request, response, name, value, age):
        import os
        secure = request.url.scheme == "https" or os.environ.get("TRIALTRUST_PUBLIC_ORIGIN", "").startswith("https://")
        response.set_cookie(name, value, httponly=True, secure=secure,
                            samesite="none" if secure and self.managed(request) else "strict", max_age=age)

    def bootstrap(self, request, response):
        user = self.current(request)
        device = self.device_token(request)
        with self.store.connect() as db:
            row = db.execute("SELECT user_id FROM browser_devices WHERE token_hash=?",
                             (digest(device),)).fetchone() if device and len(device) <= 100 else None
        if row is None:
            self.request_limit(request, "browser-bootstrap", 60, 3600)
            device = secrets.token_urlsafe(32)
            with self.store.connect() as db:
                db.execute("INSERT INTO browser_devices VALUES (?,NULL,?)", (digest(device), time.time()))
            self.set_cookie(request, response, DEVICE_COOKIE, device, DEVICE_SECONDS)
        legacy = request.headers.get("x-trialtrust-session") if self.managed(request) else None
        legacy = self.store.owner(legacy or request.cookies.get("trialtrust_session"))
        result = {"authenticated": bool(user), "user": user,
                  "browser_registered": bool(row and row[0]), "legacy_available": bool(legacy),
                  "device_scope": "browser_profile_not_physical_device"}
        if self.managed(request):
            result["browser_token"] = device
        return result

    def issue(self, request, response, user_id, db):
        token = secrets.token_urlsafe(32)
        now = time.time()
        db.execute("DELETE FROM account_sessions WHERE expires<=?", (now,))
        db.execute("INSERT INTO account_sessions VALUES (?,?,?,?)", (digest(token), user_id, now + SESSION_SECONDS, now))
        self.set_cookie(request, response, COOKIE, token, SESSION_SECONDS)
        return {"account_token": token} if self.managed(request) else {}

    def register(self, body, request, response):
        self.request_limit(request, "register", 5)
        device = self.device_token(request)
        if not device or len(device) > 100:
            raise HTTPException(409, "请刷新登录页面后注册")
        with self.store.connect() as db:
            row = db.execute("SELECT user_id FROM browser_devices WHERE token_hash=?", (digest(device),)).fetchone()
        if row is None or row[0]:
            raise HTTPException(409, "此浏览器已注册过账号，请使用已有账号登录" if row else "请刷新登录页面后注册")
        password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt(rounds=12)).decode()
        recovery = secrets.token_urlsafe(32)
        user_id = "account:" + str(uuid4())
        legacy_token = request.headers.get("x-trialtrust-session") if self.managed(request) else None
        legacy_token = legacy_token or request.cookies.get("trialtrust_session")
        imported = 0
        try:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                bound = db.execute("SELECT user_id FROM browser_devices WHERE token_hash=?", (digest(device),)).fetchone()
                if not bound or bound[0]:
                    raise HTTPException(409, "此浏览器已注册过账号，请使用已有账号登录")
                db.execute("INSERT INTO account_users VALUES (?,?,?,?,?,?)", (user_id, body.username,
                    body.username.casefold(), password_hash, digest(recovery), time.time()))
                db.execute("UPDATE browser_devices SET user_id=? WHERE token_hash=?", (user_id, digest(device)))
                if body.import_history and legacy_token:
                    old_owner = digest(legacy_token)
                    valid = db.execute("SELECT 1 FROM sessions WHERE token_hash=? AND expires>?", (old_owner, time.time())).fetchone()
                    if valid:
                        if db.execute("SELECT 1 FROM runs WHERE owner=? AND status='running'", (old_owner,)).fetchone():
                            raise HTTPException(409, "旧彩排仍在运行，请完成后再注册并关联")
                        imported = db.execute("UPDATE conversations SET owner=? WHERE owner=?", (user_id, old_owner)).rowcount
                        db.execute("UPDATE runs SET owner=? WHERE owner=?", (user_id, old_owner))
                        db.execute("DELETE FROM sessions WHERE token_hash=?", (old_owner,))
                result = self.issue(request, response, user_id, db)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "用户名不可用或此浏览器已注册，请更换名称或登录已有账号") from None
        return {**result, "user": {"id": user_id, "username": body.username},
                "recovery_code": recovery, "imported_conversations": imported}

    def login(self, body, request, response):
        self.request_limit(request, "login", 30)
        self.limit("login-user:" + digest(body.username.casefold()), 15, 900)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM account_users WHERE username_key=?", (body.username.casefold(),)).fetchone()
        valid = bcrypt.checkpw(body.password.encode(), row["password_hash"].encode() if row else self.dummy_hash)
        if not row or not valid:
            raise HTTPException(401, "用户名或密码不正确")
        with self.store.connect() as db:
            # Re-check the credential version so a concurrent password reset wins.
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM account_users WHERE id=? AND password_hash=?", (row["id"], row["password_hash"])).fetchone():
                raise HTTPException(401, "凭据已更新，请重新登录")
            result = self.issue(request, response, row["id"], db)
        return {**result, "user": {"id": row["id"], "username": row["username"]}}

    def logout(self, request, response):
        token = self.token(request)
        if token:
            with self.store.connect() as db:
                db.execute("DELETE FROM account_sessions WHERE token_hash=?", (digest(token),))
        response.delete_cookie(COOKIE)
        return {"logged_out": True}

    def recover(self, body, request):
        self.request_limit(request, "recover", 5)
        self.limit("recover-user:" + digest(body.username.casefold()), 5, 900)
        replacement = secrets.token_urlsafe(32)
        new_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt(rounds=12)).decode()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,recovery_hash FROM account_users WHERE username_key=?", (body.username.casefold(),)).fetchone()
            if not row or not secrets.compare_digest(row["recovery_hash"], digest(body.recovery_code)):
                raise HTTPException(401, "用户名或恢复码不正确")
            db.execute("UPDATE account_users SET password_hash=?,recovery_hash=? WHERE id=?", (new_hash, digest(replacement), row["id"]))
            db.execute("DELETE FROM account_sessions WHERE user_id=?", (row["id"],))
        return {"password_changed": True, "recovery_code": replacement}

    def change_password(self, body, request):
        user = self.require(request)
        self.request_limit(request, "password", 8)
        with self.store.connect() as db:
            row = db.execute("SELECT password_hash FROM account_users WHERE id=?", (user["id"],)).fetchone()
        if not bcrypt.checkpw(body.current_password.encode(), row[0].encode()):
            raise HTTPException(401, "当前密码不正确")
        new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt(rounds=12)).decode()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM account_users WHERE id=? AND password_hash=?", (user["id"], row[0])).fetchone():
                raise HTTPException(409, "凭据已变化，请重新登录")
            db.execute("UPDATE account_users SET password_hash=? WHERE id=?", (new_hash, user["id"]))
            db.execute("DELETE FROM account_sessions WHERE user_id=?", (user["id"],))
        return {"password_changed": True}

    def storage_status(self, request):
        self.require(request)
        with self.store.connect() as db:
            storage_id = db.execute("SELECT value FROM storage_metadata WHERE key='storage_id'").fetchone()[0]
        return {"database": "sqlite", "storage_id": storage_id, "boot_id": self.boot_id,
                "startup_backup_exists": any((self.store.root / "backups").glob("*.sqlite")),
                "file_permissions_managed_by_platform": self.file_modes_managed}


def register_account_routes(app, accounts):
    @app.post("/api/auth/bootstrap")
    def bootstrap(request: Request, response: Response):
        return accounts.bootstrap(request, response)

    @app.post("/api/auth/register", status_code=201)
    def register(body: Registration, request: Request, response: Response):
        return accounts.register(body, request, response)

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        return accounts.login(body, request, response)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        return accounts.logout(request, response)

    @app.post("/api/auth/recover")
    def recover(body: Recovery, request: Request):
        return accounts.recover(body, request)

    @app.post("/api/auth/password")
    def password(body: PasswordChange, request: Request):
        return accounts.change_password(body, request)

    @app.get("/api/account/storage")
    def storage(request: Request):
        return accounts.storage_status(request)
