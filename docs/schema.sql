PRAGMA foreign_keys = ON;

-- Existing project naming maps to the delivery names as follows:
-- users -> user, contracts -> contract, contract_risk -> audit_result,
-- review_rule -> business_rule, knowledge_base -> knowledge_item.
CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('uploader', 'legal_reviewer', 'admin')),
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
    rule_type TEXT NOT NULL CHECK(rule_type IN ('num', 'regex', 'keyword')),
    enable INTEGER NOT NULL DEFAULT 1,
    risk_level TEXT NOT NULL DEFAULT '中',
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL CHECK(category IN ('law', 'enterprise_spec')),
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
