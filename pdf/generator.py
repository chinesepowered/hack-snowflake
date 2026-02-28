"""
PDF evidence package generator using ReportLab.
Produces a professional chargeback dispute document.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

if TYPE_CHECKING:
    from agents.crew import DisputeEvidence

# Brand colours
DARK = colors.HexColor("#1A1A2E")
ACCENT = colors.HexColor("#4361EE")
LIGHT_BG = colors.HexColor("#F0F4FF")
GREEN = colors.HexColor("#2D9E5F")
RED = colors.HexColor("#D62828")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22,
                                 textColor=DARK, alignment=TA_CENTER, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11,
                                    textColor=colors.grey, alignment=TA_CENTER, spaceAfter=20),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=13,
                                   textColor=ACCENT, spaceBefore=16, spaceAfter=6),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10,
                                leading=15, textColor=DARK, spaceAfter=4),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=9,
                                 textColor=colors.grey),
        "value": ParagraphStyle("value", fontName="Helvetica", fontSize=10, textColor=DARK),
        "narrative": ParagraphStyle("narrative", fontName="Helvetica", fontSize=10,
                                     leading=16, textColor=DARK, leftIndent=12, rightIndent=12,
                                     spaceBefore=8, spaceAfter=8),
        "footer": ParagraphStyle("footer", fontName="Helvetica", fontSize=8,
                                  textColor=colors.grey, alignment=TA_CENTER),
    }


def _fmt_cents(cents: int, currency: str = "USD") -> str:
    return f"{currency} {cents / 100:,.2f}"


def _kv_table(pairs: list[tuple[str, str]], styles) -> Table:
    """Render a two-column key-value table."""
    data = [[Paragraph(k, styles["label"]), Paragraph(str(v), styles["value"])]
            for k, v in pairs]
    t = Table(data, colWidths=[2 * inch, 4.5 * inch])
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDE3F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def generate_dispute_pdf(evidence: "DisputeEvidence", output_dir: str = "./output") -> str:
    """
    Render a complete chargeback dispute PDF from a DisputeEvidence object.
    Returns the path to the generated file.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    cb_id = evidence.chargeback.get("chargeback_id", "unknown")
    filename = f"dispute_{cb_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = os.path.join(output_dir, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = _styles()
    story = []

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    story.append(Paragraph("Chargeback Dispute Evidence Package", styles["title"]))
    story.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%B %d, %Y %H:%M UTC')}",
        styles["subtitle"],
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=ACCENT))
    story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # Dispute summary
    # ------------------------------------------------------------------
    story.append(Paragraph("Dispute Summary", styles["section"]))
    cb = evidence.chargeback
    txn = evidence.transaction
    story.append(_kv_table([
        ("Chargeback ID", cb.get("chargeback_id", "—")),
        ("Transaction ID", cb.get("transaction_id", txn.get("transaction_id", "—"))),
        ("Disputed Amount", _fmt_cents(cb.get("amount_cents", 0), cb.get("currency", "USD"))),
        ("Reason Code", cb.get("reason_code", "—")),
        ("Reason", cb.get("reason_description", "—")),
        ("Evidence Due", str(cb.get("evidence_due_by", "—"))),
        ("Chargeback Status", cb.get("status", "open")),
    ], styles))
    story.append(Spacer(1, 8))

    # ------------------------------------------------------------------
    # Original transaction details
    # ------------------------------------------------------------------
    story.append(Paragraph("Original Transaction Details", styles["section"]))
    story.append(_kv_table([
        ("Transaction ID", txn.get("transaction_id", "—")),
        ("Customer Name", txn.get("customer_name", "—")),
        ("Customer Email", txn.get("customer_email", "—")),
        ("Customer ID", txn.get("customer_id", "—")),
        ("Amount", _fmt_cents(txn.get("amount_cents", 0), txn.get("currency", "USD"))),
        ("Status at Chargeback", txn.get("status", "—")),
        ("Card", f"{txn.get('card_brand', '—')} ending {txn.get('card_last4', '—')}"),
        ("Billing Address", txn.get("billing_address", "—")),
        ("Shipping Address", txn.get("shipping_address", "—")),
        ("Transaction Date", str(txn.get("created_at", "—"))),
        ("IP Address", txn.get("ip_address", "—")),
        ("User Agent", txn.get("user_agent", "—")),
    ], styles))
    story.append(Spacer(1, 8))

    # ------------------------------------------------------------------
    # IP Address Intelligence
    # ------------------------------------------------------------------
    story.append(Paragraph("IP Address Intelligence", styles["section"]))
    ip_info = evidence.ip_enrichment
    if ip_info and not ip_info.get("note"):
        ip_pairs = [
            ("IP Address", ip_info.get("ip", txn.get("ip_address", "—"))),
            ("City", ip_info.get("city", "—")),
            ("Region", ip_info.get("region", "—")),
            ("Country", ip_info.get("country", "—")),
            ("ISP / Org", ip_info.get("org", "—")),
            ("Hostname", ip_info.get("hostname", "—")),
        ]
    else:
        ip_pairs = [("IP Address", txn.get("ip_address", "—")),
                    ("Note", ip_info.get("note", "Enrichment data unavailable"))]
    story.append(_kv_table(ip_pairs, styles))

    ip_txns = evidence.ip_transactions
    if ip_txns:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"This IP address was used in {len(ip_txns)} transaction(s), "
            "demonstrating a consistent pattern of legitimate use:",
            styles["body"],
        ))
        headers = ["Transaction ID", "Customer", "Amount", "Date", "Status"]
        rows = [headers] + [
            [
                t.get("transaction_id", "—"),
                t.get("customer_email", t.get("customer_id", "—")),
                _fmt_cents(t.get("amount_cents", 0), t.get("currency", "USD")),
                str(t.get("created_at", "—"))[:10],
                t.get("status", "—"),
            ]
            for t in ip_txns[:10]
        ]
        ip_tbl = Table(rows, colWidths=[1.6*inch, 1.8*inch, 1*inch, 1*inch, 1*inch])
        ip_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDE3F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(ip_tbl)
    story.append(Spacer(1, 8))

    # ------------------------------------------------------------------
    # Customer Purchase History
    # ------------------------------------------------------------------
    story.append(Paragraph("Customer Purchase History", styles["section"]))
    hist_txns = evidence.customer_history.get("transactions", [])
    if hist_txns:
        story.append(Paragraph(
            f"Customer has {len(hist_txns)} transaction(s) on record with this merchant:",
            styles["body"],
        ))
        headers = ["Transaction ID", "Amount", "Card", "Date", "Status"]
        rows = [headers] + [
            [
                t.get("transaction_id", "—"),
                _fmt_cents(t.get("amount_cents", 0), t.get("currency", "USD")),
                f"{t.get('card_brand', '—')} ···{t.get('card_last4', '—')}",
                str(t.get("created_at", "—"))[:10],
                t.get("status", "—"),
            ]
            for t in hist_txns[:15]
        ]
        hist_tbl = Table(rows, colWidths=[1.7*inch, 1*inch, 1.3*inch, 1*inch, 1.4*inch])
        hist_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDE3F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(hist_tbl)
    else:
        story.append(Paragraph("No additional transaction history available.", styles["body"]))

    hist_events = evidence.customer_history.get("events", [])
    if hist_events:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Account Activity Log:", styles["body"]))
        headers = ["Event", "Date", "IP Address", "Details"]
        rows = [headers] + [
            [
                e.get("event_type", "—"),
                str(e.get("event_at", "—"))[:16],
                e.get("ip_address", "—"),
                str(e.get("details", ""))[:60],
            ]
            for e in hist_events[:15]
        ]
        evt_tbl = Table(rows, colWidths=[1*inch, 1.3*inch, 1.2*inch, 2.9*inch])
        evt_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDE3F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(evt_tbl)

    story.append(Spacer(1, 8))

    # ------------------------------------------------------------------
    # AI-Generated Dispute Narrative
    # ------------------------------------------------------------------
    story.append(Paragraph("Dispute Narrative", styles["section"]))
    story.append(Paragraph(
        "The following narrative was generated by an AI dispute analyst based on the evidence above:",
        styles["body"],
    ))
    story.append(Spacer(1, 4))
    # Box the narrative
    narrative_tbl = Table(
        [[Paragraph(evidence.narrative or "No narrative generated.", styles["narrative"])]],
        colWidths=[6.5 * inch],
    )
    narrative_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, ACCENT),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(narrative_tbl)
    story.append(Spacer(1, 16))

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DDE3F0")))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "This document was automatically generated by the AI Chargeback Dispute Agent. "
        "All data sourced from merchant transaction records. "
        "Powered by CrewAI · TiDB Serverless · Composio · Skyfire",
        styles["footer"],
    ))

    doc.build(story)
    return filepath
