from __future__ import annotations

from io import BytesIO
from typing import Any

from backend.llm_audit.auditor import DISCLAIMER


def build_markdown(contract: dict[str, Any]) -> str:
    risks = contract.get("audit_results", [])
    counts = {level: sum(1 for r in risks if r["risk_level"] == level) for level in ("高", "中", "低", "建议关注")}
    lines = [f"# 合同审查报告：{contract['contract_name']}", "", f"- 项目：{contract.get('project_name', '')}", f"- 版本：{contract['version']}", f"- 上传时间：{contract['upload_time']}", f"- 状态：{contract['status']}", "", "## 风险汇总", f"高风险 {counts['高']} | 中风险 {counts['中']} | 低风险 {counts['低']} | 建议关注 {counts['建议关注']}", "", "## 逐条风险"]
    for i, risk in enumerate(risks, 1):
        lines += [f"### {i}. [{risk['risk_level']}] {risk.get('clause_type') or '条款'}", f"- 风险描述：{risk['risk_desc']}", f"- 依据来源：{risk['source_reference']}", f"- 修改建议：{risk['suggestion']}", f"- 法务复核：{risk.get('legal_review_status', '待复核')} {risk.get('legal_comment') or ''}", ""]
    lines += ["---", f"> **免责声明：{DISCLAIMER}**"]
    return "\n".join(lines)


def build_pdf(contract: dict[str, Any]) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    except ImportError as exc:
        raise RuntimeError("PDF 导出依赖未安装，请安装 reportlab") from exc
    output = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=22 * mm)
    styles = getSampleStyleSheet()
    for style_name in ("Title", "Heading2", "BodyText", "Normal"):
        styles[style_name].fontName = "STSong-Light"
    styles.add(ParagraphStyle(name="Watermark", parent=styles["Normal"], fontName="STSong-Light", fontSize=8, textColor=colors.HexColor("#b42318"), alignment=TA_CENTER))
    story = [Paragraph(f"合同审查报告：{contract['contract_name']}", styles["Title"]), Spacer(1, 8)]
    meta = [["项目", contract.get("project_name", "")], ["版本", contract["version"]], ["状态", contract["status"]], ["上传时间", contract["upload_time"]]]
    table = Table(meta, colWidths=[28 * mm, 145 * mm])
    table.setStyle(TableStyle([["GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d5dd")], ["BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f4f7")], ["VALIGN", (0, 0), (-1, -1), "TOP"], ["FONTNAME", (0, 0), (-1, -1), "STSong-Light"]]))
    story += [table, Spacer(1, 12), Paragraph("风险汇总", styles["Heading2"])]
    risks = contract.get("audit_results", [])
    summary = [["等级", "数量"]] + [[level, str(sum(1 for r in risks if r["risk_level"] == level))] for level in ("高", "中", "低", "建议关注")]
    summary_table = Table(summary, colWidths=[60 * mm, 40 * mm])
    summary_table.setStyle(TableStyle([["GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d5dd")], ["BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#101828")], ["TEXTCOLOR", (0, 0), (-1, 0), colors.white], ["FONTNAME", (0, 0), (-1, -1), "STSong-Light"]]))
    story += [summary_table, Spacer(1, 12), Paragraph("逐条风险点", styles["Heading2"])]
    for i, risk in enumerate(risks, 1):
        body = f"<b>{i}. [{risk['risk_level']}] {risk.get('clause_type') or '条款'}</b><br/>风险描述：{risk['risk_desc']}<br/>依据来源：{risk['source_reference']}<br/>修改建议：{risk['suggestion']}<br/>法务复核：{risk.get('legal_review_status', '待复核')}"
        story += [Paragraph(body, styles["BodyText"]), Spacer(1, 8)]
    def footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("STSong-Light", 8)
        canvas.setFillColor(colors.HexColor("#b42318"))
        canvas.drawCentredString(A4[0] / 2, 10 * mm, DISCLAIMER)
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
