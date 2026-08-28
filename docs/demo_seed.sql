PRAGMA foreign_keys = ON;

INSERT OR IGNORE INTO user(username, password_hash, role, display_name, enable, created_at) VALUES
('admin', '$2b$12$Oh0cucmpzAnhjpr9TYl2yOxzMKReXnKYcq6CzaHHKUJ/Sxr8ty0Du', 'admin', '系统管理员', 1, datetime('now')),
('legal', '$2b$12$WiSbTAUd8vBudRP7mp4pougv0a7V5A1svaiJre95gzQH0tfy8A4j.', 'legal_reviewer', '法务审核员', 1, datetime('now')),
('uploader', '$2b$12$LWTfdjEdRuDO5jsqZUguUuzn3oqgQ1WEyzaOdj.RiNye5.lK8kyH6', 'uploader', '合同上传员', 1, datetime('now'));

INSERT INTO business_rule(rule_name, rule_content, rule_type, enable, risk_level, description, created_at)
SELECT '付款周期上限', '付款.{0,20}(?:1[2-9][0-9]|[2-9][0-9]{2,})天', 'regex', 1, '高', '付款周期超过企业默认上限时提示风险', datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM business_rule WHERE rule_name = '付款周期上限');

INSERT INTO business_rule(rule_name, rule_content, rule_type, enable, risk_level, description, created_at)
SELECT '模糊约定提示', '另行协商', 'keyword', 1, '中', '识别需要法务进一步确认的模糊条款', datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM business_rule WHERE rule_name = '模糊约定提示');

INSERT INTO knowledge_item(category, title, content, reference_no, enable, created_at)
SELECT 'law', '合同履行基本原则', '当事人应当按照约定全面履行自己的义务。', '民法典第509条', 1, datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM knowledge_item WHERE reference_no = '民法典第509条');

INSERT INTO knowledge_item(category, title, content, reference_no, enable, created_at)
SELECT 'enterprise_spec', '付款周期规范', '原则上合同付款周期不应超过九十日，例外情况需法务复核。', 'ENT-PAY-001', 1, datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM knowledge_item WHERE reference_no = 'ENT-PAY-001');

INSERT OR IGNORE INTO system_config(key, value, desc) VALUES
('llm_api_url', 'http://localhost:8000/v1', 'LLM 模型服务 API 地址'),
('chroma_host', 'localhost', 'Chroma 向量库主机'),
('chroma_port', '8001', 'Chroma 向量库端口'),
('chroma_collection', 'contract_knowledge', 'Chroma 集合名称'),
('upload_storage_path', './data_storage/contract_files', '上传文件存储路径'),
('ai_risk_threshold', '0.70', 'AI 风险默认阈值');
