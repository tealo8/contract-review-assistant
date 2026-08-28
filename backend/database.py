from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import bcrypt

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data_storage"
DB_PATH = Path(os.getenv("CONTRACT_REVIEW_DB", str(DATA_DIR / "contract_review.db")))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash new and reset passwords with bcrypt; salt is retained for API compatibility."""
    del salt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, encoded: str) -> bool:
    if encoded.startswith("$2"):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), encoded.encode("ascii"))
        except (ValueError, TypeError):
            return False
    try:
        _, rounds, salt_hex, digest_hex = encoded.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS user (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('uploader','legal_reviewer','admin')),
                    display_name TEXT NOT NULL DEFAULT '',
                    enable INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL,
                    create_time TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contract (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES project(id),
                    user_id INTEGER NOT NULL REFERENCES user(id),
                    contract_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '待审查',
                    upload_time TEXT NOT NULL,
                    parse_error TEXT
                );
                CREATE TABLE IF NOT EXISTS contract_status_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contract_id INTEGER NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    operator_id INTEGER REFERENCES user(id),
                    operated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contract_clause (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contract_id INTEGER NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
                    clause_type TEXT NOT NULL,
                    clause_content TEXT NOT NULL,
                    UNIQUE(contract_id, clause_type)
                );
                CREATE TABLE IF NOT EXISTS audit_result (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contract_id INTEGER NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
                    clause_type TEXT,
                    risk_level TEXT NOT NULL,
                    risk_desc TEXT NOT NULL,
                    source_reference TEXT NOT NULL,
                    suggestion TEXT NOT NULL,
                    legal_review_status TEXT DEFAULT '待复核',
                    legal_comment TEXT,
                    source_type TEXT NOT NULL DEFAULT 'reference',
                    source_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS business_rule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_name TEXT NOT NULL,
                    rule_content TEXT NOT NULL,
                    rule_type TEXT NOT NULL CHECK(rule_type IN ('num','regex','keyword')),
                    enable INTEGER NOT NULL DEFAULT 1,
                    risk_level TEXT NOT NULL DEFAULT '中',
                    description TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_item (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL CHECK(category IN ('law','enterprise_spec')),
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reference_no TEXT NOT NULL,
                    enable INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    desc TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_contract_user ON contract(user_id);
                CREATE INDEX IF NOT EXISTS idx_audit_contract ON audit_result(contract_id);
                CREATE INDEX IF NOT EXISTS idx_contract_status ON contract_status_log(contract_id, operated_at);
                """
            )
            self._ensure_column(db, "user", "display_name", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "user", "enable", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(db, "business_rule", "risk_level", "TEXT NOT NULL DEFAULT '中'")
            self._ensure_column(db, "knowledge_item", "enable", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(db, "audit_result", "source_type", "TEXT NOT NULL DEFAULT 'reference'")
            self._ensure_column(db, "audit_result", "source_id", "TEXT")
            db.execute(
                """
                INSERT INTO contract_status_log(contract_id, status, operator_id, operated_at)
                SELECT c.id, c.status, c.user_id, c.upload_time
                FROM contract c
                WHERE NOT EXISTS (
                    SELECT 1 FROM contract_status_log l WHERE l.contract_id = c.id
                )
                """
            )
            db.execute(
                """
                UPDATE user
                SET display_name = CASE username
                    WHEN 'admin' THEN '系统管理员'
                    WHEN 'legal' THEN '法务审核员'
                    WHEN 'uploader' THEN '合同上传员'
                    ELSE username
                END
                WHERE display_name IS NULL OR TRIM(display_name) = ''
                """
            )
            existing = db.execute("SELECT COUNT(*) AS n FROM user").fetchone()["n"]
            if not existing:
                for username, password, role, display_name in (
                    ("admin", "Admin123!", "admin", "系统管理员"),
                    ("legal", "legal123", "legal_reviewer", "法务审核员"),
                    ("uploader", "uploader123", "uploader", "合同上传员"),
                ):
                    db.execute(
                        "INSERT INTO user(username,password_hash,role,display_name,enable,created_at) VALUES(?,?,?,?,1,?)",
                        (username, hash_password(password), role, display_name, utc_now()),
                    )
            else:
                admin = db.execute("SELECT id,password_hash FROM user WHERE username='admin'").fetchone()
                if admin and verify_password("admin123", admin["password_hash"]):
                    db.execute("UPDATE user SET password_hash=?,display_name=COALESCE(NULLIF(display_name,''),'系统管理员'),enable=1 WHERE id=?", (hash_password("Admin123!"), admin["id"]))
            if db.execute("SELECT COUNT(*) AS n FROM project").fetchone()["n"] == 0:
                db.execute("INSERT INTO project(project_name,create_time) VALUES(?,?)", ("演示合同审查项目", utc_now()))
            defaults = (
                ("llm_api_url", "http://localhost:8000/v1", "LLM 模型服务 API 地址"),
                ("chroma_host", "localhost", "Chroma 向量库主机"),
                ("chroma_port", "8001", "Chroma 向量库端口"),
                ("chroma_collection", "contract_knowledge", "Chroma 集合名称"),
                ("upload_storage_path", "./data_storage/contract_files", "上传文件存储路径"),
                ("ai_risk_threshold", "0.70", "AI 风险默认阈值"),
            )
            db.executemany("INSERT OR IGNORE INTO system_config(key,value,desc) VALUES(?,?,?)", defaults)

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.connect() as db:
            return self.row(db.execute("SELECT * FROM user WHERE username=?", (username,)).fetchone())

    def user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            return self.row(db.execute("SELECT * FROM user WHERE id=?", (user_id,)).fetchone())

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,username,display_name,role,enable,created_at FROM user ORDER BY id")]

    def create_user(self, username: str, password: str, role: str, display_name: str = "") -> dict[str, Any]:
        with self.connect() as db:
            cur = db.execute("INSERT INTO user(username,password_hash,role,display_name,enable,created_at) VALUES(?,?,?,?,1,?)", (username, hash_password(password), role, display_name or username, utc_now()))
            return self.row(db.execute("SELECT id,username,display_name,role,enable,created_at FROM user WHERE id=?", (cur.lastrowid,)).fetchone()) or {}

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM project ORDER BY id DESC")]

    def create_project(self, name: str) -> dict[str, Any]:
        with self.connect() as db:
            cur = db.execute("INSERT INTO project(project_name,create_time) VALUES(?,?)", (name, utc_now()))
            return self.row(db.execute("SELECT * FROM project WHERE id=?", (cur.lastrowid,)).fetchone()) or {}

    def create_contract(self, values: tuple[Any, ...], operator_id: int | None = None) -> int:
        with self.connect() as db:
            cur = db.execute("INSERT INTO contract(project_id,user_id,contract_name,version,file_path,status,upload_time,parse_error) VALUES(?,?,?,?,?,?,?,?)", values)
            db.execute(
                "INSERT INTO contract_status_log(contract_id,status,operator_id,operated_at) VALUES(?,?,?,?)",
                (cur.lastrowid, values[5], operator_id, utc_now()),
            )
            return int(cur.lastrowid)

    def contract(self, contract_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT c.*, p.project_name, u.username FROM contract c JOIN project p ON p.id=c.project_id JOIN user u ON u.id=c.user_id WHERE c.id=?", (contract_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["clauses"] = [dict(r) for r in db.execute("SELECT * FROM contract_clause WHERE contract_id=? ORDER BY id", (contract_id,))]
            result["audit_results"] = [dict(r) for r in db.execute("SELECT * FROM audit_result WHERE contract_id=? ORDER BY id", (contract_id,))]
            result["status_history"] = [dict(r) for r in db.execute(
                """
                SELECT l.id,l.status,l.operated_at,u.username AS operator
                FROM contract_status_log l
                LEFT JOIN user u ON u.id=l.operator_id
                WHERE l.contract_id=? ORDER BY l.id
                """,
                (contract_id,),
            )]
            return result

    def list_contracts(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        with self.connect() as db:
            sql = "SELECT c.*, p.project_name, u.username FROM contract c JOIN project p ON p.id=c.project_id JOIN user u ON u.id=c.user_id"
            args: tuple[Any, ...] = ()
            if user["role"] == "uploader":
                sql += " WHERE c.user_id=?"
                args = (user["id"],)
            sql += " ORDER BY c.upload_time DESC"
            return [dict(r) for r in db.execute(sql, args)]

    def page_contracts(self, user: dict[str, Any], page: int, page_size: int, search: str = "", status: str = "") -> dict[str, Any]:
        with self.connect() as db:
            conditions: list[str] = []
            args: list[Any] = []
            if user["role"] == "uploader":
                conditions.append("c.user_id=?")
                args.append(user["id"])
            if search:
                conditions.append("(c.contract_name LIKE ? OR p.project_name LIKE ? OR u.username LIKE ?)")
                term = f"%{search}%"
                args.extend((term, term, term))
            if status:
                conditions.append("c.status=?")
                args.append(status)
            where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
            joins = " FROM contract c JOIN project p ON p.id=c.project_id JOIN user u ON u.id=c.user_id"
            total = int(db.execute(f"SELECT COUNT(*) n{joins}{where}", args).fetchone()["n"])
            rows = list(db.execute(
                f"SELECT c.*,p.project_name,u.username{joins}{where} ORDER BY c.upload_time DESC LIMIT ? OFFSET ?",
                (*args, page_size, (page - 1) * page_size),
            ))
            return self._page_result(rows, total, page, page_size)

    def set_contract_status(self, contract_id: int, status: str, parse_error: str | None = None, operator_id: int | None = None) -> None:
        with self.connect() as db:
            previous = db.execute("SELECT status FROM contract WHERE id=?", (contract_id,)).fetchone()
            db.execute("UPDATE contract SET status=?,parse_error=? WHERE id=?", (status, parse_error, contract_id))
            if previous and previous["status"] != status:
                db.execute(
                    "INSERT INTO contract_status_log(contract_id,status,operator_id,operated_at) VALUES(?,?,?,?)",
                    (contract_id, status, operator_id, utc_now()),
                )

    def replace_clauses(self, contract_id: int, clauses: list[dict[str, str]]) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM contract_clause WHERE contract_id=?", (contract_id,))
            db.executemany("INSERT INTO contract_clause(contract_id,clause_type,clause_content) VALUES(?,?,?)", [(contract_id, c["clause_type"], c["clause_content"]) for c in clauses])

    def replace_audits(self, contract_id: int, results: list[dict[str, Any]]) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM audit_result WHERE contract_id=?", (contract_id,))
            db.executemany("INSERT INTO audit_result(contract_id,clause_type,risk_level,risk_desc,source_reference,suggestion,legal_review_status,source_type,source_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", [
                (contract_id, r.get("clause_type"), r["risk_level"], r["risk_desc"], r["source_reference"], r["suggestion"], r.get("legal_review_status", "待复核"), r.get("source_type", "reference"), str(r.get("source_id", "")) or None, utc_now()) for r in results
            ])

    def audit_result(self, result_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            return self.row(db.execute("SELECT * FROM audit_result WHERE id=?", (result_id,)).fetchone())

    def review_result(self, result_id: int, status: str, comment: str, operator_id: int | None = None) -> dict[str, Any] | None:
        with self.connect() as db:
            db.execute("UPDATE audit_result SET legal_review_status=?,legal_comment=? WHERE id=?", (status, comment, result_id))
            row = db.execute("SELECT contract_id FROM audit_result WHERE id=?", (result_id,)).fetchone()
            if row:
                pending = db.execute("SELECT COUNT(*) n FROM audit_result WHERE contract_id=? AND legal_review_status='待复核'", (row["contract_id"],)).fetchone()["n"]
                next_status = "复核完成" if pending == 0 else "法务复核中"
                previous = db.execute("SELECT status FROM contract WHERE id=?", (row["contract_id"],)).fetchone()
                db.execute("UPDATE contract SET status=? WHERE id=?", (next_status, row["contract_id"]))
                if previous and previous["status"] != next_status:
                    db.execute("INSERT INTO contract_status_log(contract_id,status,operator_id,operated_at) VALUES(?,?,?,?)", (row["contract_id"], next_status, operator_id, utc_now()))
            return self.row(db.execute("SELECT * FROM audit_result WHERE id=?", (result_id,)).fetchone())

    def complete_contract_review(self, contract_id: int, decisions: list[dict[str, Any]], operator_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            expected = {int(row["id"]) for row in db.execute("SELECT id FROM audit_result WHERE contract_id=?", (contract_id,))}
            supplied = {int(item["risk_id"]) for item in decisions}
            if not expected:
                raise ValueError("当前合同没有可复核的风险")
            if supplied != expected:
                raise ValueError("请完成全部风险项的属实性判定")
            for item in decisions:
                db.execute(
                    "UPDATE audit_result SET legal_review_status=?,legal_comment=? WHERE id=? AND contract_id=?",
                    (item["legal_review_status"], item.get("legal_comment", ""), item["risk_id"], contract_id),
                )
            previous = db.execute("SELECT status FROM contract WHERE id=?", (contract_id,)).fetchone()
            if not previous:
                return None
            db.execute("UPDATE contract SET status='复核完成' WHERE id=?", (contract_id,))
            if previous["status"] != "复核完成":
                db.execute("INSERT INTO contract_status_log(contract_id,status,operator_id,operated_at) VALUES(?, '复核完成', ?, ?)", (contract_id, operator_id, utc_now()))
        return self.contract(contract_id)

    def list_rules(self, include_disabled: bool = True) -> list[dict[str, Any]]:
        with self.connect() as db:
            sql = "SELECT * FROM business_rule"
            if not include_disabled:
                sql += " WHERE enable=1"
            return [dict(r) for r in db.execute(sql + " ORDER BY id DESC")]

    def create_rule(self, values: tuple[Any, ...]) -> dict[str, Any]:
        if len(values) == 6:
            name, content, rule_type, enable, description, created_at = values
            values = (name, content, rule_type, enable, "中", description, created_at)
        with self.connect() as db:
            cur = db.execute("INSERT INTO business_rule(rule_name,rule_content,rule_type,enable,risk_level,description,created_at) VALUES(?,?,?,?,?,?,?)", values)
            return self.row(db.execute("SELECT * FROM business_rule WHERE id=?", (cur.lastrowid,)).fetchone()) or {}

    def update_rule(self, rule_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {k: values[k] for k in ("rule_name", "rule_content", "rule_type", "enable", "risk_level", "description") if k in values}
        if not allowed:
            with self.connect() as db:
                return self.row(db.execute("SELECT * FROM business_rule WHERE id=?", (rule_id,)).fetchone())
        with self.connect() as db:
            db.execute(f"UPDATE business_rule SET {','.join(f'{k}=?' for k in allowed)} WHERE id=?", (*allowed.values(), rule_id))
            return self.row(db.execute("SELECT * FROM business_rule WHERE id=?", (rule_id,)).fetchone())

    def list_knowledge(self, include_disabled: bool = True) -> list[dict[str, Any]]:
        with self.connect() as db:
            sql = "SELECT * FROM knowledge_item"
            if not include_disabled:
                sql += " WHERE enable=1"
            return [dict(r) for r in db.execute(sql + " ORDER BY id DESC")]

    def create_knowledge(self, values: tuple[Any, ...]) -> dict[str, Any]:
        if len(values) == 5:
            category, title, content, reference_no, created_at = values
            values = (category, title, content, reference_no, 1, created_at)
        with self.connect() as db:
            cur = db.execute("INSERT INTO knowledge_item(category,title,content,reference_no,enable,created_at) VALUES(?,?,?,?,?,?)", values)
            return self.row(db.execute("SELECT * FROM knowledge_item WHERE id=?", (cur.lastrowid,)).fetchone()) or {}

    @staticmethod
    def _page_result(rows: list[sqlite3.Row], total: int, page: int, page_size: int) -> dict[str, Any]:
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    def admin_rules(self, page: int, page_size: int) -> dict[str, Any]:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) n FROM business_rule").fetchone()["n"]
            rows = list(db.execute("SELECT * FROM business_rule ORDER BY id DESC LIMIT ? OFFSET ?", (page_size, (page - 1) * page_size)))
            return self._page_result(rows, total, page, page_size)

    def delete_rule(self, rule_id: int) -> bool:
        with self.connect() as db:
            return db.execute("DELETE FROM business_rule WHERE id=?", (rule_id,)).rowcount > 0

    def admin_knowledge(self, page: int, page_size: int, category: str | None = None) -> dict[str, Any]:
        with self.connect() as db:
            where, args = (" WHERE category=?", (category,)) if category else ("", ())
            total = db.execute(f"SELECT COUNT(*) n FROM knowledge_item{where}", args).fetchone()["n"]
            rows = list(db.execute(f"SELECT * FROM knowledge_item{where} ORDER BY id DESC LIMIT ? OFFSET ?", (*args, page_size, (page - 1) * page_size)))
            return self._page_result(rows, total, page, page_size)

    def update_knowledge(self, knowledge_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {k: values[k] for k in ("category", "title", "content", "reference_no", "enable") if k in values}
        with self.connect() as db:
            if allowed:
                db.execute(f"UPDATE knowledge_item SET {','.join(f'{key}=?' for key in allowed)} WHERE id=?", (*allowed.values(), knowledge_id))
            return self.row(db.execute("SELECT * FROM knowledge_item WHERE id=?", (knowledge_id,)).fetchone())

    def delete_knowledge(self, knowledge_id: int) -> bool:
        with self.connect() as db:
            return db.execute("DELETE FROM knowledge_item WHERE id=?", (knowledge_id,)).rowcount > 0

    def admin_users(self, page: int, page_size: int) -> dict[str, Any]:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) n FROM user").fetchone()["n"]
            rows = list(db.execute("SELECT id,username,display_name,role,enable,created_at FROM user ORDER BY id DESC LIMIT ? OFFSET ?", (page_size, (page - 1) * page_size)))
            return self._page_result(rows, total, page, page_size)

    def update_user(self, user_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {k: values[k] for k in ("display_name", "role", "enable") if k in values}
        if values.get("password"):
            allowed["password_hash"] = hash_password(str(values["password"]))
        with self.connect() as db:
            if allowed:
                db.execute(f"UPDATE user SET {','.join(f'{key}=?' for key in allowed)} WHERE id=?", (*allowed.values(), user_id))
            return self.row(db.execute("SELECT id,username,display_name,role,enable,created_at FROM user WHERE id=?", (user_id,)).fetchone())

    def delete_user(self, user_id: int) -> bool:
        with self.connect() as db:
            return db.execute("DELETE FROM user WHERE id=?", (user_id,)).rowcount > 0

    def enabled_admin_count(self) -> int:
        with self.connect() as db:
            return int(db.execute("SELECT COUNT(*) n FROM user WHERE role='admin' AND enable=1").fetchone()["n"])

    def system_config(self) -> dict[str, dict[str, str]]:
        with self.connect() as db:
            return {row["key"]: {"value": row["value"], "desc": row["desc"]} for row in db.execute("SELECT key,value,desc FROM system_config ORDER BY key")}

    def update_system_config(self, values: dict[str, str]) -> dict[str, dict[str, str]]:
        with self.connect() as db:
            for key, value in values.items():
                db.execute("UPDATE system_config SET value=? WHERE key=?", (str(value), key))
        return self.system_config()


db = Database()
