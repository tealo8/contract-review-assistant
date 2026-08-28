# 架构说明

```text
Vue 3 工作台
   │ JWT / multipart
FastAPI API ── 权限与状态机 ── SQLite
   ├─ document_parser：PDF/DOCX -> 文本 -> 条款
   ├─ rag_engine：法条/企业规范检索（可替换 ChromaDB）
   ├─ rule_engine：num / regex / keyword 硬约束
   ├─ llm_audit：Qwen 适配边界 + 来源门禁 + 模糊项拦截
   └─ report_export：PDF（免责页脚）/ Markdown 降级
```

风险必须有 `source_reference` 才能落库。法务标记更新 `legal_review_status`，所有风险完成复核后合同进入“复核完成”。
