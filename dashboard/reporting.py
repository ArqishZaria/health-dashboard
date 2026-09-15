"""
Server-side PDF report builder for the "Export PDF" button on every
dashboard. Renders the exact same filtered data shown on screen as a
standalone PDF: KPI table, chart images (rendered with matplotlib), and
detail tables (rendered with reportlab).

This is a genuine PDF export (not a browser print-to-PDF): it works
headlessly and produces a consistent, shareable report file.
"""
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from django.utils import timezone

BRAND = "#0b5d63"
ACCENT = "#e8a33d"
PALETTE = ["#0b5d63", "#12878f", "#e8a33d", "#607d8b", "#8e1b1b", "#37474f", "#b5651d", "#16323a"]


def _chart_image(chart, width_in=5.6, height_in=3.1):
    labels, values = chart.get("labels") or [], chart.get("values") or []
    fig, ax = plt.subplots(figsize=(width_in, height_in))
    if not labels or not any(values):
        ax.text(0.5, 0.5, "No data available", ha="center", va="center", fontsize=10, color="#888")
        ax.axis("off")
    elif chart["type"] == "pie":
        ax.pie(values, labels=labels, autopct=lambda p: f"{p:.0f}%" if p > 0 else "", colors=PALETTE, textprops={"fontsize": 7})
    elif chart["type"] == "barh":
        ax.barh(labels, values, color=PALETTE[1])
        ax.tick_params(axis="y", labelsize=7)
    else:  # line or bar
        if chart["type"] == "line":
            ax.plot(labels, values, color=PALETTE[0], marker="o", markersize=3)
            ax.fill_between(range(len(labels)), values, color=PALETTE[0], alpha=0.12)
        else:
            ax.bar(labels, values, color=PALETTE[0])
        ax.tick_params(axis="x", labelsize=6, rotation=40)
    ax.set_title(chart.get("title", ""), fontsize=10, color=BRAND, fontweight="bold")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160)
    plt.close(fig)
    buf.seek(0)
    return buf


def build_dashboard_pdf(title, subtitle, kpis, charts, tables, filters_summary=None):
    """
    kpis: [(label, value), ...]
    charts: [{"type": "bar"/"line"/"pie"/"barh", "title": str, "labels": [...], "values": [...]}]
    tables: [{"title": str, "headers": [...], "rows": [[...], ...]}]
    filters_summary: optional string describing active filters
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=1.4 * cm, bottomMargin=1.4 * cm, leftMargin=1.4 * cm, rightMargin=1.4 * cm
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], textColor=colors.HexColor(BRAND), fontSize=18)
    heading_style = ParagraphStyle("Heading", parent=styles["Heading2"], textColor=colors.HexColor(BRAND), spaceBefore=10)
    normal = styles["Normal"]
    muted = ParagraphStyle("Muted", parent=styles["Normal"], textColor=colors.grey, fontSize=8.5)

    elements = [Paragraph(title, title_style)]
    if subtitle:
        elements.append(Paragraph(subtitle, normal))
    meta = f"Generated {timezone.now():%Y-%m-%d %H:%M}"
    if filters_summary:
        meta += f" &middot; Filters applied: {filters_summary}"
    else:
        meta += " &middot; No filters applied (showing all data in scope)"
    elements.append(Paragraph(meta, muted))
    elements.append(Spacer(1, 0.4 * cm))

    if kpis:
        kpi_data = [["Metric", "Value"]] + [[str(k), str(v)] for k, v in kpis]
        t = Table(kpi_data, colWidths=[10 * cm, 6 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f9f9")]),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.45 * cm))

    for chart in charts:
        elements.append(Paragraph(chart.get("title", ""), heading_style))
        img_buf = _chart_image(chart)
        elements.append(Image(img_buf, width=15 * cm, height=8.2 * cm))
        elements.append(Spacer(1, 0.3 * cm))

    for table in tables:
        elements.append(Paragraph(table["title"], heading_style))
        if not table["rows"]:
            elements.append(Paragraph("No data available.", normal))
            continue
        data = [table["headers"]] + [[str(c) for c in row] for row in table["rows"]]
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f9f9")]),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.4 * cm))

    doc.build(elements)
    buf.seek(0)
    return buf
