from __future__ import annotations

import re
from typing import Any


def _number(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(天|日|%|％|万元|元)?", text)
    return float(match.group(1)) if match else None


def evaluate_rules(text: str, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for rule in rules:
        if not rule.get("enable", 1):
            continue
        content = str(rule.get("rule_content", ""))
        matched = False
        evidence = ""
        if rule["rule_type"] == "keyword":
            keywords = [x.strip() for x in re.split(r"[,，|]", content) if x.strip()]
            matched = any(keyword in text for keyword in keywords)
            evidence = next((keyword for keyword in keywords if keyword in text), "")
        elif rule["rule_type"] == "regex":
            try:
                hit = re.search(content, text, re.I | re.S)
                matched = bool(hit)
                evidence = hit.group(0)[:120] if hit else ""
            except re.error:
                continue
        elif rule["rule_type"] == "num":
            # Supported syntax: field operator threshold, e.g. 付款周期>90天, 违约金>30%
            m = re.search(r"(.+?)(>=|<=|>|<|=)(\d+(?:\.\d+)?)\s*(天|日|%|％|万元|元)?", content)
            if m:
                field, op, threshold, unit = m.group(1).strip(), m.group(2), float(m.group(3)), m.group(4) or ""
                field_match = re.search(re.escape(field), text, re.I)
                if not field_match:
                    aliases = {"付款周期": "付款", "支付周期": "付款", "违约金比例": "违约", "赔偿上限": "赔偿"}
                    alias = aliases.get(field)
                    field_match = re.search(re.escape(alias), text, re.I) if alias else None
                if field_match:
                    tail = text[field_match.end():field_match.end() + 100]
                    current = _number(tail)
                    if current is not None:
                        matched = {">": current > threshold, ">=": current >= threshold, "<": current < threshold, "<=": current <= threshold, "=": current == threshold}[op]
                        evidence = tail[:80]
        if matched:
            findings.append({
                "clause_type": "业务规则",
                "risk_level": rule.get("risk_level") or ("高" if rule["rule_type"] == "num" else "中"),
                "risk_desc": f"命中企业规则“{rule['rule_name']}”：{rule.get('description') or content}（证据：{evidence}）",
                "source_reference": f"企业规则 ID: RULE-{rule['id']}",
                "source_type": "rule",
                "source_id": rule["id"],
                "suggestion": "请按照企业合同规范调整相关条款，并由法务复核。",
            })
    return findings
