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
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .cli import run_trial
from .provider import TokenLedger, Bailian
from .scenarios import CASE_LABELS, RunSpec
from .compiler import CompileRequest, compile_stand_in
from .suite import run_suite, build_suite_graph
from .catalog import public_catalog
from .skill_runtime import discover
from .request_analysis import AnalysisRequest, analyze


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: StrictBool


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
            row = db.execute("SELECT * FROM runs WHERE id=? AND owner=?", (run_id, owner)).fetchone()
        if not row:
            raise HTTPException(404, "未找到这次试托")
        return dict(row)

    def update(self, run_id, **fields):
        if not fields.keys() <= {"status", "stage", "report", "error", "reviewed"}:
            raise ValueError("Invalid storage field")
        with self.connect() as db:
            db.execute("UPDATE runs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                       [*fields.values(), run_id])

    def create(self, owner, spec, kind="trial"):
        run_id = str(uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM runs WHERE status='running'").fetchone()[0] >= 2:
                raise HTTPException(429, "当前有两次试运行，请稍后再试")
            if db.execute("SELECT COUNT(*) FROM runs WHERE owner=? AND created>?",
                          (owner, time.time() - 86400)).fetchone()[0] >= 20:
                raise HTTPException(429, "今天的试运行次数已达上限")
            db.execute("INSERT INTO runs(id,owner,spec,status,stage,created,kind) VALUES (?,?,?,?,?,?,?)",
                       (run_id, owner, spec.model_dump_json(), "running", "正在准备合成条件", time.time(), kind))
        return run_id


def create_app(root: Path | None = None, enable_live: bool | None = None, runner=run_trial):
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
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def require_owner(request):
        token = request.headers.get("x-trialtrust-session") if getattr(app.state, "studio_ui", False) else None
        owner = store.owner(token or request.cookies.get("trialtrust_session"))
        if not owner:
            raise HTTPException(401, "当前会话已失效，请刷新页面")
        return owner

    def public(row, full=False):
        result = {k: row[k] for k in ("id", "status", "stage", "created", "reviewed", "error", "kind")}
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

    @app.get("/")
    def index():
        return FileResponse(assets / "index.html")

    @app.get('/api/workbench', response_class=HTMLResponse)
    def direct_workbench():
        # Single source of truth: identical UI, session ownership and budgets.
        return HTMLResponse((assets/'index.html').read_text(encoding='utf-8')
                            .replace('"/assets/', '"/api/workbench-assets/'))

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
            raise HTTPException(422,str(exc)) from None
        except Exception:
            raise HTTPException(502,'分析未完成，请保留输入后重试；未生成试运行结论。') from None

    @app.post("/api/session")
    def session(request: Request, response: Response):
        studio_ui = getattr(app.state, "studio_ui", False)
        token = request.headers.get("x-trialtrust-session") if studio_ui else None
        token = token or request.cookies.get("trialtrust_session")
        if not store.owner(token):
            token = store.new_session()
            response.set_cookie("trialtrust_session", token, httponly=True,
                                secure=request.url.scheme == "https" or bool(public_origin and public_origin.startswith("https://")),
                                samesite="strict", max_age=86400)
        result = {"live_enabled": live_enabled, "cases": CASE_LABELS,
                  "limit": "仅测试自有合成场景；不连接真实商家或第三方智能体"}
        # ModelScope embeds a different-site iframe. Strict cookies may be
        # blocked there. This short-lived anonymous capability is sent only to
        # this same-origin client, never an account credential or URL parameter.
        if studio_ui:
            result["session_token"] = token
        return result

    @app.get("/api/trials")
    def list_trials(request: Request):
        owner = require_owner(request)
        with store.connect() as db:
            rows = db.execute("SELECT * FROM runs WHERE owner=? ORDER BY created DESC LIMIT 20", (owner,)).fetchall()
        return [public(dict(row)) for row in rows]

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
        run_id = store.create(owner, spec, kind)
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
            current = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if current["status"] not in {"failed", "interrupted"}:
                raise HTTPException(409, "只有中断或失败的试运行可以继续")
            if db.execute("SELECT COUNT(*) FROM runs WHERE status='running'").fetchone()[0] >= 2:
                raise HTTPException(429, "当前有两次试运行，请稍后再试")
            db.execute("UPDATE runs SET status='running',stage='正在读取已有检查点',error=NULL WHERE id=?", (run_id,))
        background_tasks.add_task(work, run_id, RunSpec.model_validate_json(row["spec"]), True, row["kind"])
        return {"id": run_id}

    return app


app = create_app()
