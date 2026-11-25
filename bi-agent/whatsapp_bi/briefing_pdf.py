from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Rect
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .briefing import BriefingDocument


INK = HexColor("#142C3C")
ACCENT = HexColor("#137C76")
MUTED = HexColor("#456274")
PALE = HexColor("#DCECEB")
LEVELS = "▁▂▃▄▅▆▇█"


def render_briefing_pdf(report: BriefingDocument) -> bytes:
    output = BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=44, rightMargin=44,
        topMargin=50, bottomMargin=45, title=f"Inventory briefing — {report.day}",
    )
    title = ParagraphStyle(
        "Title", fontName="Helvetica-Bold", fontSize=21, leading=24,
        textColor=INK, spaceAfter=13, keepWithNext=True,
    )
    branch = ParagraphStyle(
        "Branch", fontName="Helvetica-Bold", fontSize=14, leading=18,
        textColor=white, backColor=INK, borderPadding=(5, 8, 5, 8),
        spaceBefore=14, spaceAfter=9, keepWithNext=True,
    )
    section = ParagraphStyle(
        "Section", fontName="Helvetica-Bold", fontSize=11, leading=15,
        textColor=ACCENT, spaceBefore=9, spaceAfter=3, keepWithNext=True,
    )
    body = ParagraphStyle("Body", fontSize=9, leading=13, textColor=INK, spaceAfter=1)
    chart_label = ParagraphStyle("ChartLabel", parent=body, keepWithNext=True)

    def footer(canvas, document):
        canvas.setStrokeColor(PALE)
        canvas.line(44, 34, A4[0] - 44, 34)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(44, 22, f"Inventory briefing  |  {report.day}  |  Africa/Nairobi")
        canvas.drawRightString(A4[0] - 44, 22, str(document.page))

    story = []
    for i, line in enumerate(report.text.splitlines()):
        if not line:
            continue
        if all(char in LEVELS for char in line):
            width = min(12 * len(line), doc.width)
            chart = Drawing(width, 40)
            step = width / len(line)
            chart.add(Line(0, 3, width, 3, strokeColor=PALE))
            for index, char in enumerate(line):
                height = 2 + LEVELS.index(char) * 4
                chart.add(Rect(index * step, 3, step - 2, height, fillColor=ACCENT, strokeColor=None))
            story.extend([chart, Spacer(1, 3)])
            continue
        text = line.strip("*")
        if i == 0:
            style = title
        elif line.startswith("*"):
            style = branch if text in (*report.branch_names, "All branches") else section
        elif " by day, " in line:
            style = chart_label
        else:
            style = body
        story.append(Paragraph(escape(text), style))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
