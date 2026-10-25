"""Small single-process preview service with owner-scoped anonymous sessions.

Live model calls are off unless TRIALTRUST_ENABLE_LIVE=1 is set by the operator.
This service exposes only owned synthetic fixtures, never arbitrary agent URLs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import secrets
import sqlite3
import time
import threading
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .cli import run_trial
from .provider import TokenLedger, Bailian
from .scenarios import CASE_LABELS, RunSpec
from .compiler import CompileRequest, compile_stand_in
from .suite import run_suite, build_suite_graph
from .catalog import public_catalog
from .skill_runtime import discover
from .request_analysis import AnalysisRequest, analyze
from .ui_assets import versioned_html


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: StrictBool


class ConversationTitle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(strict=True, min_length=1, max_length=60)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("会话名称需为1—60个可见字符")
        return value


class ConversationDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: StrictBool


class Store:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.root, self.path = root, root / "web.sqlite"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires REAL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, owner TEXT, spec TEXT, status TEXT,
                    stage TEXT, report TEXT, error TEXT, created REAL, reviewed INTEGER);
            """)
            if "kind" not in {row[1] for row in db.execute("PRAGMA table_info(runs)")}:
                db.execute("ALTER TABLE runs ADD COLUMN kind TEXT NOT NULL DEFAULT 'trial'")
            if "conversation_id" not in {row[1] for row in db.execute("PRAGMA table_info(runs)")}:
                db.execute("ALTER TABLE runs ADD COLUMN conversation_id TEXT")
            columns={row[1] for row in db.execute("PRAGMA table_info(runs)")}
            for column,definition in [("title","TEXT"),("deleted","INTEGER NOT NULL DEFAULT 0"),("revision","INTEGER NOT NULL DEFAULT 0")]:
                if column not in columns:
                    db.execute(f"ALTER TABLE runs ADD COLUMN {column} {definition}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(owner, updated);
                CREATE INDEX IF NOT EXISTS runs_conversation ON runs(owner, conversation_id, created);
            """)

            if "deleted" not in {row[1] for row in db.execute("PRAGMA table_info(conversations)")}:
                db.execute("ALTER TABLE conversations ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def owner(self, token: str | None):
        if not token:
            return None
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("SELECT expires FROM sessions WHERE token_hash=?", (hashed,)).fetchone()
        return hashed if row and row["expires"] > time.time() else None

    def new_session(self):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), time.time() + 86400))
        return token

    def owned(self, run_id, owner):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=? AND owner=? AND deleted=0 AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.id=runs.conversation_id AND c.owner=runs.owner AND c.deleted=1)", (run_id, owner)).fetchone()
        if not row:
            raise HTTPException(404, "未找到这次试托")
        return dict(row)

    def conversation(self, conversation_id, owner):
        with self.connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=? AND owner=? AND deleted=0",
                             (conversation_id, owner)).fetchone()
        if not row:
            raise HTTPException(404, "未找到这个会话")
        return dict(row)

    def conversations(self, owner):
        with self.connect() as db:
            # Group older, unassigned records lazily, under their original owner.
            # This is idempotent and preserves reports and graph checkpoints.
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT MIN(created),MAX(created) FROM runs WHERE owner=? AND conversation_id IS NULL AND deleted=0",
                             (owner,)).fetchone()
            if old[0] is not None:
                legacy = str(uuid4())
                db.execute("INSERT INTO conversations(id,owner,title,created,updated) VALUES (?,?,?,?,?)",
                           (legacy, owner, "历史彩排", old[0], old[1]))
                db.execute("UPDATE runs SET conversation_id=? WHERE owner=? AND conversation_id IS NULL AND deleted=0",
                           (legacy, owner))
            rows = db.execute("""SELECT c.id,c.title,c.created,c.updated,COUNT(r.id) AS run_count
                FROM conversations c LEFT JOIN runs r ON r.conversation_id=c.id AND r.owner=c.owner AND r.deleted=0
                WHERE c.owner=? AND c.deleted=0 GROUP BY c.id ORDER BY c.updated DESC,c.id LIMIT 100""", (owner,)).fetchall()
        return [dict(row) for row in rows]

    def new_conversation(self, owner):
        conversation_id, now = str(uuid4()), time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM conversations WHERE owner=?", (owner,)).fetchone()[0] >= 100:
                raise HTTPException(429, "当前浏览器身份的会话数已达上限")
            db.execute("INSERT INTO conversations(id,owner,title,created,updated) VALUES (?,?,?,?,?)",
                       (conversation_id, owner, "新会话", now, now))
        return self.conversation(conversation_id, owner)

    def change_conversation(self, conversation_id, owner, title=None, expected_updated=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,updated FROM conversations WHERE id=? AND owner=? AND deleted=0",
                             (conversation_id, owner)).fetchone()
            if not row:
                raise HTTPException(404, "未找到这个会话")
            if expected_updated is not None and row["updated"] != expected_updated:
                raise HTTPException(409, "会话已发生变化，请关闭弹窗后重新选择操作")
            if db.execute("SELECT 1 FROM runs WHERE conversation_id=? AND owner=? AND status='running'",
                          (conversation_id, owner)).fetchone():
                raise HTTPException(409, "这个会话仍有彩排进行中，请完成后再操作")
            if title is None:
                # Keep tombstones and usage rows so deletion cannot reset quotas.
                # All owner-facing reads and writes exclude deleted conversations.
                db.execute("UPDATE conversations SET deleted=1,updated=? WHERE id=? AND owner=?",
                           (time.time(), conversation_id, owner))
                return {"deleted": True}
            db.execute("UPDATE conversations SET title=?,updated=? WHERE id=? AND owner=?",
                       (title, time.time(), conversation_id, owner))
            return {"id": conversation_id, "title": title}

    def change_run(self, run_id, owner, *, title=None, expected_revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM runs WHERE id=? AND owner=? AND deleted=0 AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.id=runs.conversation_id AND c.owner=runs.owner AND c.deleted=1)",(run_id,owner)).fetchone()
            if not row:
                raise HTTPException(404,"未找到这条彩排记录")
            if row['status']=='running':
                raise HTTPException(409,"这次彩排仍在进行，请完成后再操作")
            if row['revision']!=expected_revision:
                raise HTTPException(409,"记录已发生变化，请关闭弹窗后重新选择操作")
            if title is None:
                # Keep the report, checkpoints and quota accounting as tombstones.
                db.execute("UPDATE runs SET deleted=1,revision=revision+1 WHERE id=? AND owner=?",(run_id,owner))
            else:
                db.execute("UPDATE runs SET title=?,revision=revision+1 WHERE id=? AND owner=?",(title,run_id,owner))
            db.execute("UPDATE conversations SET updated=? WHERE id=? AND owner=?",(time.time(),row['conversation_id'],owner))
            return {'id':run_id,'title':title,'revision':row['revision']+1,'deleted':title is None}

    def update(self, run_id, **fields):
        if not fields.keys() <= {"status", "stage", "report", "error", "reviewed"}:
            raise ValueError("Invalid storage field")
        with self.connect() as db:
            db.execute("UPDATE runs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                       [*fields.values(), run_id])

    def create(self, owner, spec, kind="trial", conversation_id=None):
        if conversation_id is None:
            previous = self.conversations(owner)
            conversation_id = previous[0]["id"] if previous else self.new_conversation(owner)["id"]
        run_id = str(uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            conversation = db.execute("SELECT * FROM conversations WHERE id=? AND owner=? AND deleted=0",
                                      (conversation_id, owner)).fetchone()
            if not conversation:
                raise HTTPException(404, "未找到这个会话")
            if db.execute("SELECT COUNT(*) FROM runs WHERE status='running'").fetchone()[0] >= 2:
                raise HTTPException(429, "当前有两次试运行，请稍后再试")
            if db.execute("SELECT COUNT(*) FROM runs WHERE owner=? AND created>?",
                          (owner, time.time() - 86400)).fetchone()[0] >= 20:
                raise HTTPException(429, "今天的试运行次数已达上限")
            now = time.time()
            db.execute("INSERT INTO runs(id,owner,spec,status,stage,created,kind,conversation_id) VALUES (?,?,?,?,?,?,?,?)",
                       (run_id, owner, spec.model_dump_json(), "running", "正在准备合成条件", now, kind, conversation_id))
            title = spec.mandate().label
            db.execute("UPDATE conversations SET updated=?,title=CASE WHEN title='新会话' AND updated=created THEN ? ELSE title END WHERE id=? AND owner=?",
                       (now, title, conversation_id, owner))
        return run_id


def create_app(root: Path | None = None, enable_live: bool | None = None, runner=run_trial, *, require_accounts: bool = True):
    root = root or Path(os.environ.get("TRIALTRUST_RUNTIME", "runtime/web"))
    store = Store(root)
    live_enabled = enable_live if enable_live is not None else os.environ.get("TRIALTRUST_ENABLE_LIVE") == "1"
    ledger = TokenLedger(root.parent / "usage.sqlite")
    review_locks = defaultdict(threading.Lock)

    @asynccontextmanager
    async def lifespan(app):
        # A single-process service: interrupted jobs stay visible, never auto-retry.
        with store.connect() as db:
            db.execute("UPDATE runs SET status='interrupted',stage='服务重启，本次运行未完成' WHERE status='running'")
        yield

    app = FastAPI(title="试托", lifespan=lifespan, docs_url=None, redoc_url=None)
    from .accounts import Accounts, register_account_routes
    accounts = Accounts(store) if require_accounts else None
    app.state.accounts = accounts

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith('/api/auth/'):
            # FastAPI's default validation includes submitted input. Never echo passwords.
            return JSONResponse({'detail': '请检查填写内容：用户名3—32位字母/数字/下划线；密码至少10个字符、UTF-8不超过72字节，两次密码需一致。'}, status_code=422)
        from fastapi.exception_handlers import request_validation_exception_handler
        return await request_validation_exception_handler(request, exc)
    allowed_hosts = [host.strip() for host in os.environ.get("TRIALTRUST_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host.strip()]
    public_origin = os.environ.get("TRIALTRUST_PUBLIC_ORIGIN")
    rejected_hosts = set()
    app.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=allowed_hosts)
    assets = Path(__file__).parent / "web"
    # Some Windows registry mappings label .js as text/plain. nosniff correctly
    # blocks that response, so set the executable script MIME type explicitly.
    mimetypes.add_type("text/javascript", ".js")
    app.mount("/assets", StaticFiles(directory=assets), name="assets")
    # A lightweight HTML entry independent of Gradio's own asset namespace.
    # ModelScope may still wrap browser navigation in its official portal.
    app.mount('/api/workbench-assets', StaticFiles(directory=assets), name='workbench_assets')

    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            if request.headers.get("x-trialtrust-client") != "web":
                return Response("同源客户端标记缺失", status_code=403)
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            # Some hosted gateways replace Host with their internal service name.
            # Accept only the operator's one explicit public origin, never an
            # arbitrary client-supplied X-Forwarded-Host value.
            if origin and origin not in {expected, public_origin}:
                return Response("不接受跨站请求", status_code=403)
        public_path = (request.url.path in {'/api/workbench', '/api/session'}
                       or request.url.path.startswith(('/api/auth/', '/api/workbench-assets/')))
        if accounts and request.url.path.startswith('/api/') and not public_path and not accounts.current(request):
            response = JSONResponse({'detail': '请先登录试托账号'}, status_code=401)
        else:
            response = await call_next(request)
        if response.status_code == 400 and request.url.hostname not in allowed_hosts and len(rejected_hosts) < 8:
            hostname = request.url.hostname
            if hostname not in rejected_hosts:
                rejected_hosts.add(hostname)
                logging.getLogger("trialtrust.gateway").warning("Gateway host rejected: %r", hostname)
        response.headers["X-Content-Type-Options"] = "nosniff"
        studio_ui = getattr(app.state, "studio_ui", False)
        direct_ui = request.url.path == '/api/workbench'
        if not studio_ui:
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if studio_ui:
            # Managed Gradio supplies its own frontend; restrict framing to the
            # actual portal, without applying standalone script rules to Gradio.
            response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://modelscope.cn https://www.modelscope.cn"
            if direct_ui:
                response.headers['Content-Security-Policy'] = (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; connect-src 'self'; "
                    "frame-ancestors 'self' https://modelscope.cn https://www.modelscope.cn")
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path == '/' or request.url.path.startswith(("/api/", "/assets/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    def require_owner(request):
        if accounts:
            return accounts.require(request)['id']
        token = request.headers.get("x-trialtrust-session") if getattr(app.state, "studio_ui", False) else None
        owner = store.owner(token or request.cookies.get("trialtrust_session"))
        if not owner:
            raise HTTPException(401, "当前会话已失效，请刷新页面")
        return owner

    def public(row, full=False):
        result = {k: row[k] for k in ("id", "status", "stage", "created", "reviewed", "error", "kind", "conversation_id", "title", "revision")}
        result["conditions"] = json.loads(row["spec"])
        if full and row["report"]:
            result["report"] = json.loads(row["report"])
        return result

    def work(run_id, spec, resume=False, kind="trial"):
        stages = {"assistant": "智能体已返回一步决策", "tools": "已核对工具结果与授权",
                  "report": "独立核验已完成", "__interrupt__": "等待你审阅试托记录",
                  "design": "设计智能体已提出一个变化", "baseline": "原始条件已试完，正在试变化条件",
                  "changed": "两次执行已完成，正在交叉审阅", "audit": "审阅事实已与记录独立核对"}
        try:
            execute = run_suite if kind == "suite" else runner
            report = execute(root / run_id, spec=spec, thread_id=run_id, ledger=ledger,
                            dense_model="qwen3.7-text-embedding-flash" if spec.dense else None,
                            resume=resume,
                            on_progress=lambda node: store.update(run_id, stage=stages.get(node, "正在整理结果")))
            already_reviewed = isinstance(report.get("human_reviewed"), bool)
            store.update(run_id, status="reviewed" if already_reviewed else "waiting_review",
                         reviewed=int(report["human_reviewed"]) if already_reviewed else None,
                         stage="已恢复已审阅结果" if already_reviewed else "试运行已停在人工审阅处",
                         report=json.dumps(report, ensure_ascii=False), error=None)
        except Exception as exc:
            # Never send a provider traceback or response payload to the browser.
            message = "本次试运行未完成，已有检查点已保留。"
            if isinstance(exc, RuntimeError) and "token budget reached" in str(exc):
                message = "项目token预算已到上限，未继续调用模型。"
            if isinstance(exc, RuntimeError) and "money budget reached" in str(exc):
                message = "项目估算费用预算已到上限，未继续调用模型。"
            store.update(run_id, status="failed", stage="试运行已停止", error=message)

    def page_html(prefix):
        content = {path.name: path.read_bytes() for path in assets.iterdir()
                   if path.suffix in {'.js', '.css'}}
        return versioned_html((assets/'index.html').read_text(encoding='utf-8'), content, prefix)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(page_html('/assets/'))

    @app.get('/api/workbench', response_class=HTMLResponse)
    def direct_workbench():
        # Single source of truth: identical UI, session ownership and budgets.
        return HTMLResponse(page_html('/api/workbench-assets/'))

    @app.get("/health")
    def health():
        return {"status": "ok", "synthetic_only": True}

    @app.get('/api/catalog')
    def catalog():
        return public_catalog()

    @app.get('/api/skills')
    def skills():
        return {'runtime':'trusted-skills-v1','skills':discover(),
                'boundary':'只加载随应用发布的白名单技能，不执行上传的脚本或任意代码。'}

    @app.post('/api/analyze')
    def analyze_request(body: AnalysisRequest, request: Request):
        require_owner(request)
        if body.use_model and not live_enabled:
            raise HTTPException(403,'真实模型分析尚未启用；可先选择规则分析')
        try:
            provider=Bailian(ledger.for_run('analysis-'+str(uuid4()))) if body.use_model else None
            result = analyze(body,provider)
            if provider:
                result['usage'] = provider.ledger.summary(run_only=True)
            return result
        except ValueError as exc:
            message=str(exc)
            if message in {'请先检查并确认这段文字已去除个人资料',
                           '替身仍含可识别的手机号、邮箱或身份证格式，请先在本地替换',
                           '真实模型尚未启用'}:
                raise HTTPException(422,message) from None
            raise HTTPException(502,'需求检查暂未完成，请稍后重试。') from None
        except Exception:
            raise HTTPException(502,'需求检查暂未完成，请稍后重试。') from None

    @app.post("/api/session")
    def session(request: Request, response: Response):
        if accounts:
            user = accounts.current(request)
            return {"authenticated": bool(user), "user": user, "auth_required": True,
                    "live_enabled": live_enabled,
                    "studio_url": os.environ.get("TRIALTRUST_STUDIO_URL", "https://www.modelscope.cn/studios/L666H666Better/trialtrust"),
                    "cases": CASE_LABELS, "limit": "仅测试自有合成场景；不连接真实商家或第三方智能体"}
        studio_ui = getattr(app.state, "studio_ui", False)
        token = request.headers.get("x-trialtrust-session") if studio_ui else None
        token = token or request.cookies.get("trialtrust_session")
        if not store.owner(token):
            token = store.new_session()
            response.set_cookie("trialtrust_session", token, httponly=True,
                                secure=request.url.scheme == "https" or bool(public_origin and public_origin.startswith("https://")),
                                samesite="strict", max_age=86400)
        result = {"live_enabled": live_enabled, "studio_url": os.environ.get("TRIALTRUST_STUDIO_URL", "https://www.modelscope.cn/studios/L666H666Better/trialtrust"), "cases": CASE_LABELS,
                  "limit": "仅测试自有合成场景；不连接真实商家或第三方智能体"}
        # ModelScope embeds a different-site iframe. Strict cookies may be
        # blocked there. This short-lived anonymous capability is sent only to
        # this same-origin client, never an account credential or URL parameter.
        if studio_ui:
            result["session_token"] = token
        return result

    @app.get("/api/trials")
    def list_trials(request: Request, conversation_id: str | None = None):
        owner = require_owner(request)
        if conversation_id:
            store.conversation(conversation_id, owner)
        with store.connect() as db:
            if conversation_id:
                rows = db.execute("SELECT * FROM runs WHERE owner=? AND deleted=0 AND conversation_id=? ORDER BY created DESC LIMIT 100",
                                  (owner, conversation_id)).fetchall()
            else:
                rows = db.execute("SELECT * FROM runs WHERE owner=? AND deleted=0 AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.id=runs.conversation_id AND c.owner=runs.owner AND c.deleted=1) ORDER BY created DESC LIMIT 20", (owner,)).fetchall()
        return [public(dict(row)) for row in rows]

    @app.get("/api/conversations")
    def list_conversations(request: Request):
        return store.conversations(require_owner(request))

    from .conversation_actions import register_conversation_actions
    register_conversation_actions(app, store, require_owner)
    from .run_actions import register_run_actions
    register_run_actions(app,store,require_owner,review_locks)

    @app.post("/api/conversations", status_code=201)
    def new_conversation(request: Request):
        return store.new_conversation(require_owner(request))

    @app.post("/api/conversations/{conversation_id}/rename")
    @app.patch("/api/conversations/{conversation_id}")
    def rename_conversation(conversation_id: str, body: ConversationTitle, request: Request):
        return store.change_conversation(conversation_id, require_owner(request), title=body.title)

    @app.delete("/api/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str, request: Request):
        return store.change_conversation(conversation_id, require_owner(request))

    @app.post("/api/conversations/{conversation_id}/delete")
    def delete_conversation_compatible(conversation_id: str, body: ConversationDeletion, request: Request):
        owner = require_owner(request)
        if not body.confirmed:
            raise HTTPException(409, "请先确认删除这个会话")
        return store.change_conversation(conversation_id, owner)

    @app.post("/api/trials", status_code=202)
    def start(spec: RunSpec, request: Request, background_tasks: BackgroundTasks):
        return start_run(spec, request, background_tasks)

    @app.post("/api/suites", status_code=202)
    def start_suite(spec: RunSpec, request: Request, background_tasks: BackgroundTasks):
        if spec.case != "baseline":
            raise HTTPException(422, "对照试托从原始条件开始，只改变一个测试条件")
        return start_run(spec, request, background_tasks, "suite")

    def start_run(spec, request, background_tasks, kind="trial"):
        owner = require_owner(request)
        if not spec.confirmed:
            raise HTTPException(409, "请先核对并确认本次场景、数量、服务方式和预算")
        if spec.agent == "live" and not live_enabled:
            raise HTTPException(403, "运营者尚未启用真实模型调用")
        if spec.dense and spec.agent != "live":
            raise HTTPException(422, "离线演示不会调用向量模型")
        conversation_id = request.headers.get("x-trialtrust-conversation")
        run_id = store.create(owner, spec, kind, conversation_id=conversation_id)
        background_tasks.add_task(work, run_id, spec, False, kind)
        return {"id": run_id}

    @app.post("/api/compile")
    def compile_task(body: CompileRequest, request: Request):
        require_owner(request)
        try:
            return compile_stand_in(body.stand_in_text)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/api/trials/{run_id}")
    def detail(run_id: str, request: Request):
        return public(store.owned(run_id, require_owner(request)), full=True)

    @app.get("/api/trials/{run_id}/export")
    def export(run_id: str, request: Request):
        row = store.owned(run_id, require_owner(request))
        if not row["report"]:
            raise HTTPException(409, "还没有可导出的结果")
        return Response(row["report"], media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="trialtrust-report.json"'})

    @app.post("/api/trials/{run_id}/review")
    def review(run_id: str, body: Review, request: Request):
        with review_locks[run_id]:
            return record_review(run_id, body, request)

    def record_review(run_id, body, request):
        row = store.owned(run_id, require_owner(request))
        if row["status"] == "reviewed":
            if bool(row["reviewed"]) != body.accepted:
                raise HTTPException(409, "本次审阅已记录；请新建试托来改变条件")
            return {"status": "reviewed", "accepted": body.accepted}
        if row["status"] != "waiting_review":
            raise HTTPException(409, "本次试运行尚未到审阅阶段")
        # Resume the real graph interrupt with a provider that cannot incur costs.
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.types import Command
        from .cli import ScriptedDemo
        from .retrieval import EvidenceIndex
        from .scenarios import make_world
        from .workflow import build_graph
        spec = RunSpec.model_validate_json(row["spec"])
        sources, world, _ = make_world(spec)
        with SqliteSaver.from_conn_string(str(root / run_id / "checkpoints.sqlite")) as saver:
            if row["kind"] == "suite":
                class ReviewOnly:
                    def chat(self, *args, **kwargs):
                        raise RuntimeError("Model calls prohibited while recording human review")
                graph = build_suite_graph(root / run_id, run_id, spec, ledger, saver, role_provider=ReviewOnly())
            else:
                graph = build_graph(ScriptedDemo(), EvidenceIndex(sources), world, saver)
            config = {"configurable": {"thread_id": run_id}}
            snapshot = graph.get_state(config)
            if snapshot.next == ("human_review",):
                graph.invoke(Command(resume=body.accepted), config)
            elif snapshot.next == () and snapshot.values.get("human_reviewed") is body.accepted:
                pass  # recover a crash after graph commit but before updating run metadata
            else:
                raise HTTPException(409, "检查点状态与审阅阶段不一致")
            graph_report = dict(graph.get_state(config).values["report"])
        report = {**json.loads(row["report"]), **graph_report}
        report.update(awaiting_human_review=False, human_reviewed=body.accepted)
        store.update(run_id, status="reviewed", reviewed=int(body.accepted), stage="你的审阅决定已记录；不会预约或付款",
                     report=json.dumps(report, ensure_ascii=False))
        return {"status": "reviewed", "accepted": body.accepted}

    @app.post("/api/trials/{run_id}/resume", status_code=202)
    def resume(run_id: str, request: Request, background_tasks: BackgroundTasks):
        row = store.owned(run_id, require_owner(request))
        if RunSpec.model_validate_json(row["spec"]).agent == "live" and not live_enabled:
            raise HTTPException(403, "真实模型调用当前未启用")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT r.status FROM runs r JOIN conversations c ON c.id=r.conversation_id AND c.owner=r.owner WHERE r.id=? AND r.owner=? AND r.deleted=0 AND c.deleted=0", (run_id, require_owner(request))).fetchone()
            if not current:
                raise HTTPException(404, "未找到这次试托")
            if current["status"] not in {"failed", "interrupted"}:
                raise HTTPException(409, "只有中断或失败的试运行可以继续")
            if db.execute("SELECT COUNT(*) FROM runs WHERE status='running'").fetchone()[0] >= 2:
                raise HTTPException(429, "当前有两次试运行，请稍后再试")
            db.execute("UPDATE runs SET status='running',stage='正在读取已有检查点',error=NULL WHERE id=?", (run_id,))
        background_tasks.add_task(work, run_id, RunSpec.model_validate_json(row["spec"]), True, row["kind"])
        return {"id": run_id}

    if accounts:
        register_account_routes(app, accounts)
    return app


app = create_app()
