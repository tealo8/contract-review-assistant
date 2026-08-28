from __future__ import annotations

from typing import Any

from backend.rag_engine.store import KnowledgeStore
from backend.rule_engine.engine import evaluate_rules

DISCLAIMER = "本报告为 AI 辅助建议，不可替代法务专业审核，不具备法律效力"


def audit_contract(text: str, clauses: list[dict[str, Any]], rules: list[dict[str, Any]], store: KnowledgeStore) -> tuple[list[dict[str, Any]], list[str]]:
    """Deterministic baseline auditor with source gating; an LLM adapter can be added behind this contract."""
    results = evaluate_rules(text, rules)
    warnings: list[str] = []
    clause_types = {c["clause_type"] for c in clauses}
    clause_text = {c["clause_type"]: c.get("clause_content", "") for c in clauses}

    payment = clause_text.get("付款", "")
    if payment:
        hits = store.search(payment + " 付款 周期", 3)
        if "天" in payment and any(x in payment for x in ("120", "180", "90")):
            source = hits[0]["reference_no"] if hits else ""
            if source:
                results.append({"clause_type": "付款", "risk_level": "高", "risk_desc": "付款周期可能超过企业可接受范围，影响现金流。", "source_reference": f"法条 ID: {source}", "source_type": "knowledge", "source_id": hits[0]["id"], "suggestion": "建议将付款周期调整为 90 天以内，并明确逾期利息。"})
            else:
                warnings.append("付款条款检索不到有效依据，未生成语义风险结论。")
    penalty = clause_text.get("违约", "")
    if penalty and any(x in penalty for x in ("30%", "40%", "50%", "百分之三十")):
        hits = store.search(penalty + " 违约金", 3)
        if hits:
            results.append({"clause_type": "违约", "risk_level": "高", "risk_desc": "违约金比例较高，存在明显成本暴露。", "source_reference": f"知识库编号: {hits[0]['reference_no']}", "source_type": "knowledge", "source_id": hits[0]["id"], "suggestion": "建议设置违约金上限不超过合同总额的 30%，并区分实际损失。"})
        else:
            warnings.append("违约金条款缺少可验证的知识库依据，已拦截无来源风险。")
    for required in ("保密", "终止", "争议解决", "知识产权"):
        if required not in clause_types:
            results.append({"clause_type": required, "risk_level": "建议关注", "risk_desc": f"未识别到{required}条款，可能存在合同要素缺失。", "source_reference": "企业规则 ID: RULE-CLAUSE-COMPLETENESS", "source_type": "rule", "source_id": "CLAUSE-COMPLETENESS", "suggestion": f"请法务人工确认是否需要补充{required}条款。"})
    if "无法判定" in text or "待定" in text or "以双方另行协商" in text:
        results.append({"clause_type": "模糊条款", "risk_level": "建议关注", "risk_desc": "【无法判定，请法务人工审阅】条款语义不明确，系统不会臆测法律风险。", "source_reference": "企业规则 ID: RULE-MANUAL-REVIEW", "source_type": "rule", "source_id": "MANUAL-REVIEW", "suggestion": "请补充明确的时间、金额、责任边界后再复核。"})
    # Hard gate: no empty or fabricated source is allowed downstream.
    return [r for r in results if r.get("source_reference")], warnings
