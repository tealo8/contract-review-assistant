import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.database import Database, utc_now, verify_password
from backend.document_parser.parser import clause_diff
from backend.rag_engine.store import KnowledgeStore
from backend.rule_engine.engine import evaluate_rules


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    test_db = Database(tmp_path / "contract_review_test.db")
    test_db.init()
    monkeypatch.setattr(main, "db", test_db)
    monkeypatch.setattr(main, "store", KnowledgeStore(test_db))
    monkeypatch.setattr(main, "runtime_client_seen", False)
    with main.runtime_lock:
        main.runtime_clients.clear()
    main.startup()
    yield test_db


def auth(username: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_health_and_login():
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/assets/contract-review-logo.svg").status_code == 200
    headers = auth("uploader", "uploader123")
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "uploader"


def test_role_boundary():
    headers = auth("uploader", "uploader123")
    assert client.post("/api/rules", headers=headers, json={"rule_name":"x","rule_content":"x","rule_type":"keyword"}).status_code == 403


def test_upload_and_audit():
    headers = auth("uploader", "uploader123")
    with open("demo_files/sample_risky_contract.txt", "rb") as handle:
        response = client.post("/api/contracts/upload?project_id=1", headers=headers, files={"file": ("risky.txt", handle, "text/plain")})
    assert response.status_code == 200
    contract_id = response.json()["contract_id"]
    audit_response = client.post(f"/api/contracts/{contract_id}/audit", headers=headers)
    assert audit_response.status_code == 200
    assert all(r["source_reference"] for r in audit_response.json()["contract"]["audit_results"])


def test_runtime_page_lifecycle():
    client_id = "test-runtime-client"
    assert client.post("/api/runtime/heartbeat", json={"client_id": client_id}).status_code == 200
    active = client.get("/api/runtime/status").json()
    assert active["active_clients"] >= 1
    assert active["shutdown_requested"] is False

    assert client.post("/api/runtime/page-closed", json={"client_id": client_id}).status_code == 200
    with main.runtime_lock:
        main.runtime_clients[client_id]["last_seen"] -= main.RUNTIME_GRACE_SECONDS + 1
    closed = client.get("/api/runtime/status").json()
    assert closed["shutdown_requested"] is True


def test_runtime_missing_heartbeat_eventually_requests_shutdown():
    client_id = "test-missing-heartbeat"
    assert client.post("/api/runtime/heartbeat", json={"client_id": client_id}).status_code == 200
    with main.runtime_lock:
        main.runtime_clients[client_id]["last_seen"] -= main.RUNTIME_HEARTBEAT_TIMEOUT_SECONDS + 1
    status_response = client.get("/api/runtime/status").json()
    assert status_response["active_clients"] == 0
    assert status_response["shutdown_requested"] is True


ADMIN_REQUESTS = (
    ("GET", "/api/admin/rules", None),
    ("POST", "/api/admin/rules", {"rule_name": "x", "rule_content": "x", "rule_type": "keyword"}),
    ("PUT", "/api/admin/rules/1", {"enable": False}),
    ("DELETE", "/api/admin/rules/1", None),
    ("GET", "/api/admin/knowledge", None),
    ("POST", "/api/admin/knowledge", {"category": "law", "title": "x", "content": "x", "reference_no": "x"}),
    ("PUT", "/api/admin/knowledge/1", {"enable": False}),
    ("DELETE", "/api/admin/knowledge/1", None),
    ("GET", "/api/admin/users", None),
    ("POST", "/api/admin/users", {"username": "blocked_user", "display_name": "x", "password": "Password1!", "role": "uploader"}),
    ("PUT", "/api/admin/users/1", {"role": "admin"}),
    ("DELETE", "/api/admin/users/1", None),
    ("GET", "/api/admin/config", None),
    ("PUT", "/api/admin/config", {"llm_api_url": "http://localhost:8000/v1", "chroma_host": "localhost", "chroma_port": "8001", "chroma_collection": "contracts", "upload_storage_path": "./data_storage/contracts", "ai_risk_threshold": "0.75"}),
)


@pytest.mark.parametrize(("username", "password"), (("legal", "legal123"), ("uploader", "uploader123")))
@pytest.mark.parametrize(("method", "path", "payload"), ADMIN_REQUESTS)
def test_every_admin_endpoint_rejects_non_admin(username, password, method, path, payload):
    response = client.request(method, path, headers=auth(username, password), json=payload)
    assert response.status_code == 403


def test_admin_rule_crud_pagination_and_live_risk_level(isolated_database):
    headers = auth("admin", "Admin123!")
    created = client.post(
        "/api/admin/rules",
        headers=headers,
        json={
            "rule_name": "低风险保密提示",
            "rule_type": "keyword",
            "rule_content": "专项保密词",
            "risk_level": "低",
            "description": "验证保存后立即生效",
        },
    )
    assert created.status_code == 201
    rule = created.json()

    page = client.get("/api/admin/rules?page=1&page_size=1", headers=headers).json()
    assert page["page_size"] == 1
    assert page["total"] >= 1
    assert page["pages"] >= 1

    findings = evaluate_rules("合同含有专项保密词", isolated_database.list_rules(include_disabled=False))
    assert any(item["risk_level"] == "低" and f"RULE-{rule['id']}" in item["source_reference"] for item in findings)

    updated = client.put(f"/api/admin/rules/{rule['id']}", headers=headers, json={"enable": False, "risk_level": "高"})
    assert updated.status_code == 200
    assert updated.json()["enable"] == 0
    assert not evaluate_rules("合同含有专项保密词", isolated_database.list_rules(include_disabled=False))
    assert client.delete(f"/api/admin/rules/{rule['id']}", headers=headers).status_code == 204


def test_admin_knowledge_crud_and_disabled_items_are_not_retrieved():
    headers = auth("admin", "Admin123!")
    created = client.post(
        "/api/admin/knowledge",
        headers=headers,
        json={
            "category": "enterprise_spec",
            "title": "专项检索词规范",
            "content": "专项检索词应由法务复核",
            "reference_no": "KB-ADMIN-001",
            "enable": True,
        },
    )
    assert created.status_code == 201
    item = created.json()
    assert any(hit["id"] == item["id"] for hit in main.store.search("专项检索词"))

    page = client.get("/api/admin/knowledge?category=enterprise_spec&page=1&page_size=1", headers=headers).json()
    assert page["page_size"] == 1
    assert all(row["category"] == "enterprise_spec" for row in page["items"])

    updated = client.put(f"/api/admin/knowledge/{item['id']}", headers=headers, json={"enable": False, "title": "已停用规范"})
    assert updated.status_code == 200
    assert updated.json()["enable"] == 0
    assert all(hit["id"] != item["id"] for hit in main.store.search("专项检索词"))
    assert client.delete(f"/api/admin/knowledge/{item['id']}", headers=headers).status_code == 204


def test_admin_user_crud_bcrypt_reset_and_disable(isolated_database):
    headers = auth("admin", "Admin123!")
    created = client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "reviewer2", "display_name": "二号法务", "password": "Initial123!", "role": "uploader"},
    )
    assert created.status_code == 201
    account = created.json()
    assert "password" not in account and "password_hash" not in account

    stored = isolated_database.user_by_username("reviewer2")
    assert stored["password_hash"].startswith("$2")
    assert stored["password_hash"] != "Initial123!"
    assert verify_password("Initial123!", stored["password_hash"])

    old_token_headers = auth("reviewer2", "Initial123!")
    updated = client.put(
        f"/api/admin/users/{account['id']}",
        headers=headers,
        json={"role": "legal_reviewer", "password": "ResetPass123!"},
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "legal_reviewer"
    assert client.post("/api/auth/login", json={"username": "reviewer2", "password": "Initial123!"}).status_code == 401
    new_token_headers = auth("reviewer2", "ResetPass123!")

    assert client.put(f"/api/admin/users/{account['id']}", headers=headers, json={"enable": False}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "reviewer2", "password": "ResetPass123!"}).status_code == 403
    assert client.get("/api/auth/me", headers=old_token_headers).status_code == 403
    assert client.get("/api/auth/me", headers=new_token_headers).status_code == 403

    assert client.put(f"/api/admin/users/{account['id']}", headers=headers, json={"enable": True}).status_code == 200
    assert client.get("/api/admin/users?page=1&page_size=2", headers=headers).json()["page_size"] == 2
    assert client.delete(f"/api/admin/users/{account['id']}", headers=headers).status_code == 204
    assert isolated_database.user_by_username("reviewer2") is None


def test_admin_system_config_round_trip():
    headers = auth("admin", "Admin123!")
    initial = client.get("/api/admin/config", headers=headers)
    assert initial.status_code == 200
    payload = {
        "llm_api_url": "http://model.internal/v1",
        "chroma_host": "chroma.internal",
        "chroma_port": "8100",
        "chroma_collection": "legal_contracts",
        "upload_storage_path": "./data_storage/custom_contracts",
        "ai_risk_threshold": "0.82",
    }
    updated = client.put("/api/admin/config", headers=headers, json=payload)
    assert updated.status_code == 200
    assert updated.json()["config"] == payload
    assert client.get("/api/admin/config", headers=headers).json()["config"] == payload


def test_existing_users_receive_display_names_during_migration(isolated_database):
    with isolated_database.connect() as connection:
        connection.execute("UPDATE user SET display_name='' WHERE username IN ('legal','uploader')")
    isolated_database.init()
    assert isolated_database.user_by_username("legal")["display_name"] == "法务审核员"
    assert isolated_database.user_by_username("uploader")["display_name"] == "合同上传员"


def test_upload_content_security_signatures_and_archive_limits(monkeypatch):
    assert main.validate_upload_content("contract.pdf", b"%PDF-1.7\n") == ".pdf"
    with pytest.raises(Exception) as invalid_pdf:
        main.validate_upload_content("contract.pdf", b"not-a-pdf")
    assert invalid_pdf.value.status_code == 400

    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    assert main.validate_upload_content("contract.docx", docx.getvalue()) == ".docx"

    for filename, content in (("empty.txt", b""), ("binary.txt", b"a\x00b"), ("script.exe", b"MZ")):
        with pytest.raises(Exception) as blocked:
            main.validate_upload_content(filename, content)
        assert blocked.value.status_code == 400

    monkeypatch.setattr(main, "MAX_UPLOAD", 3)
    with pytest.raises(Exception) as too_large:
        main.validate_upload_content("large.txt", b"four")
    assert too_large.value.status_code == 413


def test_contract_pagination_search_and_uploader_isolation(isolated_database):
    uploader = isolated_database.user_by_username("uploader")
    admin = isolated_database.user_by_username("admin")
    isolated_database.create_contract((1, uploader["id"], "上传员合同", "v1", "demo.txt", "待审查", utc_now(), None), uploader["id"])
    isolated_database.create_contract((1, admin["id"], "管理员合同", "v1", "demo.txt", "复核完成", utc_now(), None), admin["id"])

    uploader_page = client.get("/api/contracts?page=1&page_size=10", headers=auth("uploader", "uploader123")).json()
    assert uploader_page["total"] == 1
    assert uploader_page["items"][0]["contract_name"] == "上传员合同"

    admin_page = client.get("/api/contracts?page=1&page_size=1&search=合同&status=复核完成", headers=auth("admin", "Admin123!")).json()
    assert admin_page["total"] == 1
    assert admin_page["page_size"] == 1
    assert admin_page["items"][0]["contract_name"] == "管理员合同"


def test_contract_detail_contains_original_text_and_relative_storage_path():
    headers = auth("uploader", "uploader123")
    raw = "甲方：测试公司\n付款周期为120天。".encode("utf-8")
    uploaded = client.post("/api/contracts/upload?project_id=1", headers=headers, files={"file": ("original.txt", raw, "text/plain")})
    assert uploaded.status_code == 200
    contract = uploaded.json()["contract"]
    assert not contract["file_path"].startswith(("/", "\\"))
    detail = client.get(f"/api/contracts/{contract['id']}", headers=headers).json()
    assert "测试公司" in detail["original_text"]
    assert detail["status_history"][0]["status"] == "上传中"


def test_batch_review_completes_workflow_and_records_operator():
    uploader_headers = auth("uploader", "uploader123")
    with open("demo_files/sample_risky_contract.txt", "rb") as handle:
        uploaded = client.post("/api/contracts/upload?project_id=1", headers=uploader_headers, files={"file": ("review.txt", handle, "text/plain")})
    contract_id = uploaded.json()["contract_id"]
    audited = client.post(f"/api/contracts/{contract_id}/audit", headers=uploader_headers).json()["contract"]
    assert audited["status"] == "待法务复核"

    decisions = [
        {"risk_id": risk["id"], "legal_review_status": "属实" if index % 2 == 0 else "不属实", "legal_comment": "已核验"}
        for index, risk in enumerate(audited["audit_results"])
    ]
    completed = client.post(
        f"/api/contracts/{contract_id}/review/complete",
        headers=auth("legal", "legal123"),
        json={"decisions": decisions},
    )
    assert completed.status_code == 200
    contract = completed.json()["contract"]
    assert contract["status"] == "复核完成"
    assert all(risk["legal_review_status"] in {"属实", "不属实"} for risk in contract["audit_results"])
    assert contract["status_history"][-1]["operator"] == "legal"


def test_clause_diff_reports_added_deleted_and_modified():
    old = [
        {"clause_type": "付款", "clause_content": "三十日"},
        {"clause_type": "保密", "clause_content": "保密两年"},
    ]
    new = [
        {"clause_type": "付款", "clause_content": "六十日"},
        {"clause_type": "终止", "clause_content": "提前通知"},
    ]
    assert {item["change_type"] for item in clause_diff(old, new)} == {"added", "deleted", "modified"}


def test_knowledge_store_chroma_sync_with_fake_collection(isolated_database, monkeypatch):
    class FakeCollection:
        def __init__(self):
            self.items = {}

        def upsert(self, ids, embeddings, documents, metadatas):
            self.items[ids[0]] = {"embedding": embeddings[0], "document": documents[0], "metadata": metadatas[0]}

        def delete(self, ids):
            for item_id in ids:
                self.items.pop(item_id, None)

        def get(self, include):
            return {"ids": list(self.items)}

    store = KnowledgeStore(isolated_database)
    fake = FakeCollection()
    monkeypatch.setattr(store, "_chroma", lambda: fake)
    item = isolated_database.create_knowledge(("law", "同步测试", "同步内容", "SYNC-1", 1, utc_now()))
    assert store.sync_item(item) is True
    assert str(item["id"]) in fake.items
    assert store.delete_item(item["id"]) is True
    assert str(item["id"]) not in fake.items


def test_admin_config_rejects_absolute_or_parent_storage_paths():
    headers = auth("admin", "Admin123!")
    base = client.get("/api/admin/config", headers=headers).json()["config"]
    for bad_path in ("C:/outside/contracts", "../outside"):
        response = client.put("/api/admin/config", headers=headers, json={**base, "upload_storage_path": bad_path})
        assert response.status_code == 422
