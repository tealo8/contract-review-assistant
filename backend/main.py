from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import time
import threading
import zipfile
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from backend.database import db, utc_now, verify_password
from backend.document_parser.parser import clause_diff, extract_clauses, parse_document
from backend.llm_audit.auditor import DISCLAIMER, audit_contract
from backend.rag_engine.store import KnowledgeStore
from backend.report_export.exporter import build_markdown, build_pdf

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE_PATH = Path("data_storage") / "contract_files"
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-this-secret")
security = HTTPBearer(auto_error=False)
app = FastAPI(title="合同智能审查助手", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
db.init()
store = KnowledgeStore(db)
runtime_clients: dict[str, dict[str, float | bool]] = {}
runtime_lock = threading.Lock()
runtime_client_seen = False
RUNTIME_GRACE_SECONDS = 6
RUNTIME_HEARTBEAT_TIMEOUT_SECONDS = 12


def token_for(user: dict[str, Any]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
    payload = json.dumps({"sub": user["id"], "username": user["username"], "role": user["role"], "exp": int(time.time()) + 8 * 3600}, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    message = f"{header}.{encoded}"
    signature = base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(), message.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{message}.{signature}"


def user_from_token(credentials: HTTPAuthorizationCredentials | None) -> dict[str, Any]:
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        header, encoded, signature = credentials.credentials.split(".", 2)
        message = f"{header}.{encoded}"
        expected = base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(), message.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError
        user = db.user_by_id(int(payload["sub"]))
        if not user:
            raise ValueError
        if not user.get("enable", 1):
            raise HTTPException(status_code=403, detail="账号已被禁用")
        return user
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="登录令牌无效")


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict[str, Any]:
    return user_from_token(credentials)


def require_roles(*roles: str):
    def dependency(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="当前角色无权执行此操作")
        return user
    return dependency


class LoginPayload(BaseModel):
    username: str
    password: str


class ProjectPayload(BaseModel):
    project_name: str = Field(min_length=1, max_length=100)


class RulePayload(BaseModel):
    rule_name: str = Field(min_length=1, max_length=100)
    rule_content: str = Field(min_length=1, max_length=500)
    rule_type: Literal["num", "regex", "keyword"]
    enable: bool = True
    risk_level: Literal["高", "中", "低"] = "中"
    description: str = ""


class RuleUpdate(BaseModel):
    rule_name: str | None = None
    rule_content: str | None = None
    rule_type: Literal["num", "regex", "keyword"] | None = None
    enable: bool | None = None
    risk_level: Literal["高", "中", "低"] | None = None
    description: str | None = None


class ReviewPayload(BaseModel):
    legal_review_status: Literal["属实", "不属实", "确认风险", "误判", "部分成立"]
    legal_comment: str = Field(default="", max_length=1000)


class ContractReviewDecision(ReviewPayload):
    risk_id: int


class ContractReviewPayload(BaseModel):
    decisions: list[ContractReviewDecision] = Field(min_length=1)


class KnowledgePayload(BaseModel):
    category: Literal["law", "enterprise_spec"]
    title: str
    content: str
    reference_no: str
    enable: bool = True


class KnowledgeUpdate(BaseModel):
    category: Literal["law", "enterprise_spec"] | None = None
    title: str | None = None
    content: str | None = None
    reference_no: str | None = None
    enable: bool | None = None


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["uploader", "legal_reviewer", "admin"]


class AdminUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    role: Literal["uploader", "legal_reviewer", "admin"] | None = None
    enable: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class SystemConfigPayload(BaseModel):
    llm_api_url: str = Field(min_length=1, max_length=500)
    chroma_host: str = Field(min_length=1, max_length=200)
    chroma_port: str = Field(min_length=1, max_length=10)
    chroma_collection: str = Field(min_length=1, max_length=100)
    upload_storage_path: str = Field(min_length=1, max_length=500)
    ai_risk_threshold: str = Field(pattern=r"^(0(?:\.\d+)?|1(?:\.0+)?)$")


class RuntimeClientPayload(BaseModel):
    client_id: str = Field(min_length=8, max_length=100)


admin_router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_roles("admin"))],
)


@app.on_event("startup")
def startup() -> None:
    db.init()
    laws_path = BASE_DIR / "knowledge_base" / "civil_law_contract.json"
    rules_path = BASE_DIR / "knowledge_base" / "enterprise_rule_sample.json"
    try:
        laws = json.loads(laws_path.read_text(encoding="utf-8")) if laws_path.exists() else []
        rules = json.loads(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else []
        store.ensure_seed(laws, rules)
        if not db.list_rules():
            rules_seed = json.loads((BASE_DIR / "knowledge_base" / "rules.json").read_text(encoding="utf-8"))
            for rule in rules_seed:
                db.create_rule((rule["rule_name"], rule["rule_content"], rule["rule_type"], int(rule.get("enable", 1)), rule.get("description", ""), utc_now()))
        store.sync_all()
    except (OSError, json.JSONDecodeError):
        pass


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "contract-review-assistant"}


@app.post("/api/runtime/heartbeat")
def runtime_heartbeat(payload: RuntimeClientPayload):
    global runtime_client_seen
    with runtime_lock:
        runtime_client_seen = True
        runtime_clients[payload.client_id] = {"last_seen": time.monotonic(), "closing": False}
    return {"status": "active"}


@app.post("/api/runtime/page-closed")
def runtime_page_closed(payload: RuntimeClientPayload):
    global runtime_client_seen
    now = time.monotonic()
    with runtime_lock:
        runtime_client_seen = True
        runtime_clients[payload.client_id] = {"last_seen": now, "closing": True}
    return {"status": "closing", "grace_seconds": RUNTIME_GRACE_SECONDS}


@app.get("/api/runtime/status")
def runtime_status():
    now = time.monotonic()
    with runtime_lock:
        stale = [
            client_id
            for client_id, state in runtime_clients.items()
            if now - float(state["last_seen"]) > (RUNTIME_GRACE_SECONDS if state["closing"] else RUNTIME_HEARTBEAT_TIMEOUT_SECONDS)
        ]
        for client_id in stale:
            runtime_clients.pop(client_id, None)
        active = sum(1 for state in runtime_clients.values() if not state["closing"])
        grace = sum(1 for state in runtime_clients.values() if state["closing"])
    return {"client_seen": runtime_client_seen, "active_clients": active, "closing_clients": grace, "shutdown_requested": runtime_client_seen and active == 0 and grace == 0}


@app.post("/api/auth/login")
def login(payload: LoginPayload):
    user = db.user_by_username(payload.username)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.get("enable", 1):
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")
    return {"access_token": token_for(user), "token_type": "bearer", "user": {"id": user["id"], "username": user["username"], "display_name": user.get("display_name") or user["username"], "role": user["role"]}}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(current_user)):
    return {"id": user["id"], "username": user["username"], "display_name": user.get("display_name") or user["username"], "role": user["role"]}


@app.get("/api/projects")
def projects(_: dict[str, Any] = Depends(current_user)):
    return db.list_projects()


@app.post("/api/projects")
def create_project(payload: ProjectPayload, _: dict[str, Any] = Depends(require_roles("admin", "legal_reviewer"))):
    return db.create_project(payload.project_name)


@app.get("/api/contracts")
def contracts(
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default="", max_length=100),
    status_filter: str = Query(default="", alias="status", max_length=30),
    user: dict[str, Any] = Depends(current_user),
):
    if page is None and not search and not status_filter:
        return db.list_contracts(user)
    return db.page_contracts(user, page or 1, page_size, search.strip(), status_filter.strip())


def assert_contract_access(contract_id: int, user: dict[str, Any]) -> dict[str, Any]:
    contract = db.contract(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    if user["role"] == "uploader" and contract["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该合同")
    return contract


def configured_storage_dir() -> Path:
    config = db.system_config().get("upload_storage_path", {}).get("value", DEFAULT_STORAGE_PATH.as_posix())
    configured = Path(config)
    if configured.is_absolute() or ".." in configured.parts:
        configured = DEFAULT_STORAGE_PATH
    resolved = (BASE_DIR / configured).resolve()
    if not resolved.is_relative_to(BASE_DIR):
        resolved = (BASE_DIR / DEFAULT_STORAGE_PATH).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def stored_contract_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


def validate_upload_content(filename: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".md"}:
        raise HTTPException(status_code=400, detail="仅支持 PDF、DOCX、TXT、MD 文件")
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件不能为空")
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail=f"文件不能超过 {MAX_UPLOAD // 1024 // 1024}MB")
    if suffix == ".pdf" and not raw.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="PDF 文件签名无效，已拦截可疑文件")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = set(archive.namelist())
                unpacked_size = sum(item.file_size for item in archive.infolist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise ValueError
                if unpacked_size > MAX_UPLOAD * 5:
                    raise HTTPException(status_code=413, detail="DOCX 解压体积异常，已拦截可疑文件")
        except HTTPException:
            raise
        except (zipfile.BadZipFile, ValueError):
            raise HTTPException(status_code=400, detail="DOCX 文件结构无效，已拦截可疑文件")
    if suffix in {".txt", ".md"} and b"\x00" in raw:
        raise HTTPException(status_code=400, detail="文本文件包含异常二进制内容")
    return suffix


@app.post("/api/contracts/upload")
async def upload_contract(project_id: int = Query(...), file: UploadFile = File(...), user: dict[str, Any] = Depends(current_user)):
    project = next((p for p in db.list_projects() if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    raw = await file.read()
    validate_upload_content(file.filename, raw)
    safe_name = f"{secrets.token_hex(8)}_{Path(file.filename).name.replace('..', '_')}"
    target = configured_storage_dir() / safe_name
    target.write_bytes(raw)
    existing = [c for c in db.list_contracts({"role": "admin", "id": -1}) if c["contract_name"] == Path(file.filename).stem]
    version = f"v{len(existing) + 1}"
    stored_path = target.relative_to(BASE_DIR).as_posix()
    contract_id = db.create_contract((project_id, user["id"], Path(file.filename).stem, version, stored_path, "上传中", utc_now(), None), user["id"])
    try:
        db.set_contract_status(contract_id, "解析中", operator_id=user["id"])
        text = parse_document(target)
        clauses = extract_clauses(text)
        db.replace_clauses(contract_id, clauses)
        db.set_contract_status(contract_id, "待审查", operator_id=user["id"])
        return {"contract_id": contract_id, "contract": db.contract(contract_id), "message": "上传成功，等待 AI 审查"}
    except Exception as exc:
        db.set_contract_status(contract_id, "解析失败", str(exc), user["id"])
        return JSONResponse(status_code=422, content={"contract_id": contract_id, "message": "文档解析失败，原始文件已保留，可重新解析", "detail": str(exc)})


@app.get("/api/contracts/{contract_id}")
def contract_detail(contract_id: int, user: dict[str, Any] = Depends(current_user)):
    contract = assert_contract_access(contract_id, user)
    try:
        contract["original_text"] = parse_document(stored_contract_path(contract["file_path"]))
    except Exception:
        contract["original_text"] = ""
    return contract


@app.post("/api/contracts/{contract_id}/parse")
def reparse(contract_id: int, user: dict[str, Any] = Depends(current_user)):
    contract = assert_contract_access(contract_id, user)
    try:
        db.set_contract_status(contract_id, "解析中", operator_id=user["id"])
        clauses = extract_clauses(parse_document(stored_contract_path(contract["file_path"])))
        db.replace_clauses(contract_id, clauses)
        db.set_contract_status(contract_id, "待审查", None, user["id"])
        return db.contract(contract_id)
    except Exception as exc:
        db.set_contract_status(contract_id, "解析失败", str(exc), user["id"])
        raise HTTPException(status_code=422, detail=f"解析失败：{exc}")


@app.post("/api/contracts/{contract_id}/audit")
def run_audit(contract_id: int, user: dict[str, Any] = Depends(current_user)):
    contract = assert_contract_access(contract_id, user)
    if contract.get("parse_error"):
        raise HTTPException(status_code=422, detail="文档尚未解析成功，请先重新解析")
    try:
        text = parse_document(stored_contract_path(contract["file_path"]))
        results, warnings = audit_contract(text, contract["clauses"], db.list_rules(False), store)
        db.replace_audits(contract_id, results)
        db.set_contract_status(contract_id, "AI 审查完成", operator_id=user["id"])
        if results:
            db.set_contract_status(contract_id, "待法务复核", operator_id=user["id"])
        return {"contract": db.contract(contract_id), "warnings": warnings, "disclaimer": DISCLAIMER}
    except TimeoutError:
        db.set_contract_status(contract_id, "AI 审查完成", operator_id=user["id"])
        raise HTTPException(status_code=504, detail="部分条款审查未完成，请重新执行审查")


@app.get("/api/contracts/{contract_id}/report")
def report(contract_id: int, format: Literal["pdf", "md"] = "pdf", user: dict[str, Any] = Depends(current_user)):
    contract = assert_contract_access(contract_id, user)
    if format == "md":
        return Response(build_markdown(contract), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=contract-{contract_id}-report.md"})
    try:
        content = build_pdf(contract)
        return Response(content, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=contract-{contract_id}-report.pdf"})
    except Exception:
        return Response(build_markdown(contract), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=contract-{contract_id}-report.md"})


@app.post("/api/contracts/compare")
def compare_contracts(old_id: int, new_id: int, user: dict[str, Any] = Depends(current_user)):
    old = assert_contract_access(old_id, user)
    new = assert_contract_access(new_id, user)
    return {"old_contract_id": old_id, "new_contract_id": new_id, "changes": clause_diff(old["clauses"], new["clauses"]), "message": "仅变更条款需要重新审查"}


@app.get("/api/rules")
def rules(_: dict[str, Any] = Depends(current_user)):
    return db.list_rules()


@app.post("/api/rules")
def create_rule(payload: RulePayload, _: dict[str, Any] = Depends(require_roles("admin"))):
    return db.create_rule((payload.rule_name, payload.rule_content, payload.rule_type, int(payload.enable), payload.description, utc_now()))


@app.patch("/api/rules/{rule_id}")
def update_rule(rule_id: int, payload: RuleUpdate, _: dict[str, Any] = Depends(require_roles("admin"))):
    result = db.update_rule(rule_id, payload.model_dump(exclude_none=True))
    if not result:
        raise HTTPException(status_code=404, detail="规则不存在")
    return result


@app.get("/api/knowledge")
def knowledge(_: dict[str, Any] = Depends(require_roles("admin", "legal_reviewer"))):
    return db.list_knowledge()


@app.post("/api/knowledge")
def create_knowledge(payload: KnowledgePayload, _: dict[str, Any] = Depends(require_roles("admin"))):
    return db.create_knowledge((payload.category, payload.title, payload.content, payload.reference_no, utc_now()))


@app.post("/api/audit-results/{result_id}/review")
def review(result_id: int, payload: ReviewPayload, reviewer: dict[str, Any] = Depends(require_roles("admin", "legal_reviewer"))):
    result = db.review_result(result_id, payload.legal_review_status, payload.legal_comment, reviewer["id"])
    if not result:
        raise HTTPException(status_code=404, detail="审查结果不存在")
    return result


@app.post("/api/contracts/{contract_id}/review/complete")
def complete_contract_review(
    contract_id: int,
    payload: ContractReviewPayload,
    reviewer: dict[str, Any] = Depends(require_roles("admin", "legal_reviewer")),
):
    assert_contract_access(contract_id, reviewer)
    try:
        contract = db.complete_contract_review(
            contract_id,
            [decision.model_dump() for decision in payload.decisions],
            reviewer["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    return {"message": "法务复核已完成", "contract": contract}


@app.get("/api/users")
def users(_: dict[str, Any] = Depends(require_roles("admin"))):
    return db.list_users()


@app.post("/api/users")
def create_user(payload: dict[str, Any], _: dict[str, Any] = Depends(require_roles("admin"))):
    if payload.get("role") not in {"uploader", "legal_reviewer", "admin"}:
        raise HTTPException(status_code=400, detail="角色无效")
    try:
        return db.create_user(payload["username"], payload["password"], payload["role"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"用户创建失败：{exc}")


@admin_router.get("/rules")
def admin_rules(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100)):
    return db.admin_rules(page, page_size)


@admin_router.post("/rules", status_code=status.HTTP_201_CREATED)
def admin_create_rule(payload: RulePayload):
    return db.create_rule((payload.rule_name, payload.rule_content, payload.rule_type, int(payload.enable), payload.risk_level, payload.description, utc_now()))


@admin_router.put("/rules/{rule_id}")
def admin_update_rule(rule_id: int, payload: RuleUpdate):
    result = db.update_rule(rule_id, payload.model_dump(exclude_none=True))
    if not result:
        raise HTTPException(status_code=404, detail="规则不存在")
    return result


@admin_router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_rule(rule_id: int):
    if not db.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="规则不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/knowledge")
def admin_knowledge(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    category: Literal["law", "enterprise_spec"] | None = None,
):
    return db.admin_knowledge(page, page_size, category)


@admin_router.post("/knowledge", status_code=status.HTTP_201_CREATED)
def admin_create_knowledge(payload: KnowledgePayload):
    item = db.create_knowledge((payload.category, payload.title, payload.content, payload.reference_no, int(payload.enable), utc_now()))
    store.sync_item(item)
    return item


@admin_router.put("/knowledge/{knowledge_id}")
def admin_update_knowledge(knowledge_id: int, payload: KnowledgeUpdate):
    result = db.update_knowledge(knowledge_id, payload.model_dump(exclude_none=True))
    if not result:
        raise HTTPException(status_code=404, detail="知识库条目不存在")
    store.sync_item(result)
    return result


@admin_router.delete("/knowledge/{knowledge_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_knowledge(knowledge_id: int):
    if not db.update_knowledge(knowledge_id, {}):
        raise HTTPException(status_code=404, detail="知识库条目不存在")
    store.delete_item(knowledge_id)
    if not db.delete_knowledge(knowledge_id):
        raise HTTPException(status_code=404, detail="知识库条目不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/users")
def admin_users(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100)):
    return db.admin_users(page, page_size)


@admin_router.post("/users", status_code=status.HTTP_201_CREATED)
def admin_create_user(payload: AdminUserCreate):
    try:
        return db.create_user(payload.username, payload.password, payload.role, payload.display_name)
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="用户名已存在")
        raise HTTPException(status_code=400, detail="用户创建失败")


@admin_router.put("/users/{user_id}")
def admin_update_user(user_id: int, payload: AdminUserUpdate, admin_user: dict[str, Any] = Depends(current_user)):
    target = db.user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    values = payload.model_dump(exclude_none=True)
    if user_id == admin_user["id"] and (values.get("enable") is False or values.get("role") not in (None, "admin")):
        raise HTTPException(status_code=400, detail="不能禁用当前账号或移除自身管理员角色")
    removes_last_admin = target["role"] == "admin" and target.get("enable", 1) and (values.get("enable") is False or values.get("role") not in (None, "admin"))
    if removes_last_admin and db.enabled_admin_count() <= 1:
        raise HTTPException(status_code=400, detail="系统至少需要保留一个启用的管理员账号")
    return db.update_user(user_id, values)


@admin_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_user(user_id: int, admin_user: dict[str, Any] = Depends(current_user)):
    target = db.user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user_id == admin_user["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    if target["role"] == "admin" and target.get("enable", 1) and db.enabled_admin_count() <= 1:
        raise HTTPException(status_code=400, detail="系统至少需要保留一个启用的管理员账号")
    try:
        deleted = db.delete_user(user_id)
    except Exception:
        raise HTTPException(status_code=409, detail="该用户已有业务数据，不能直接删除，可改为禁用账号")
    if not deleted:
        raise HTTPException(status_code=404, detail="用户不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/config")
def admin_config():
    config = db.system_config()
    return {
        "config": {key: item["value"] for key, item in config.items()},
        "descriptions": {key: item["desc"] for key, item in config.items()},
    }


@admin_router.put("/config")
def admin_update_config(payload: SystemConfigPayload):
    if not payload.chroma_port.isdigit() or not 1 <= int(payload.chroma_port) <= 65535:
        raise HTTPException(status_code=422, detail="Chroma 端口必须在 1 到 65535 之间")
    storage_path = Path(payload.upload_storage_path)
    if storage_path.is_absolute() or ".." in storage_path.parts:
        raise HTTPException(status_code=422, detail="上传文件存储路径必须是项目内相对路径")
    updated = db.update_system_config(payload.model_dump())
    store.reset_chroma_connection()
    synced = store.sync_all()
    return {
        "message": "系统参数保存成功",
        "config": {key: item["value"] for key, item in updated.items()},
        "vector_sync": {"synced": synced, "fallback": not synced, "detail": store.last_sync_error},
    }


app.include_router(admin_router)


frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        requested = frontend_dir / path
        if path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(frontend_dir / "index.html")
