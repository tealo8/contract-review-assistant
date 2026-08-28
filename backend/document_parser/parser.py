from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def parse_document(path: str | Path) -> str:
    """Extract text from text PDFs and DOCX files. OCR is intentionally an extension point."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF 解析依赖未安装，请安装 pypdf") from exc
        reader = PdfReader(str(file_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if not text:
            raise ValueError("PDF 未提取到可复制文本，扫描件 OCR 为扩展能力")
        return text
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("DOCX 解析依赖未安装，请安装 python-docx") from exc
        doc = Document(str(file_path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
    raise ValueError("仅支持 PDF、DOCX、TXT 文件")


CLAUSE_PATTERNS: dict[str, tuple[str, ...]] = {
    "甲方": (r"甲方[：:]?(.*?)(?=乙方|付款|第[一二三四五六七八九十0-9]+条|$)",),
    "乙方": (r"乙方[：:]?(.*?)(?=付款|第[一二三四五六七八九十0-9]+条|$)",),
    "付款": (r"(付款|支付|结算)(.*?)(?=违约|保密|终止|争议|知识产权|第[一二三四五六七八九十0-9]+条|$)",),
    "违约": (r"(违约责任|违约金)(.*?)(?=保密|终止|争议|赔偿|知识产权|第[一二三四五六七八九十0-9]+条|$)",),
    "保密": (r"(保密)(.*?)(?=终止|争议|赔偿|知识产权|第[一二三四五六七八九十0-9]+条|$)",),
    "终止": (r"(合同终止|解除|终止)(.*?)(?=争议|赔偿|知识产权|第[一二三四五六七八九十0-9]+条|$)",),
    "争议解决": (r"(争议解决|管辖|仲裁|诉讼)(.*?)(?=赔偿|知识产权|第[一二三四五六七八九十0-9]+条|$)",),
    "赔偿上限": (r"(赔偿上限|责任上限|赔偿责任)(.*?)(?=知识产权|第[一二三四五六七八九十0-9]+条|$)",),
    "知识产权": (r"(知识产权|成果归属|版权)(.*?)(?=第[一二三四五六七八九十0-9]+条|$)",),
}


def extract_clauses(text: str) -> list[dict[str, str]]:
    normalized = re.sub(r"\r\n?", "\n", text)
    clauses: list[dict[str, str]] = []
    for clause_type, patterns in CLAUSE_PATTERNS.items():
        matches = []
        for pattern in patterns:
            matches.extend(re.findall(pattern, normalized, flags=re.S | re.I))
        if matches:
            value = matches[0]
            if isinstance(value, tuple):
                value = " ".join(value)
            value = re.sub(r"\s+", " ", value).strip(" ：:;；。\n")
            if value:
                clauses.append({"clause_type": clause_type, "clause_content": value[:5000]})
    return clauses


def clause_diff(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_map = {x["clause_type"]: x.get("clause_content", "") for x in old}
    new_map = {x["clause_type"]: x.get("clause_content", "") for x in new}
    diff = []
    for clause_type in sorted(set(old_map) | set(new_map)):
        before, after = old_map.get(clause_type, ""), new_map.get(clause_type, "")
        if before != after:
            change_type = "added" if not before else "deleted" if not after else "modified"
            diff.append({
                "clause_type": clause_type,
                "before": before,
                "after": after,
                "changed": True,
                "change_type": change_type,
            })
    return diff
