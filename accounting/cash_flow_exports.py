"""
Cash Flow export functions - V2 (Template-Based)
Generates PDF, Excel, and CSV reports for DFC (Demonstração do Fluxo de Caixa)

V2 Changes:
- Green color scheme matching ControlladorIA template
- Sheet titled "FLUXO DE CAIXA"
- Structure inspired by template: Saldo Inicial -> Entradas -> Saídas -> Saldo Final
  then DRE-like breakdown below
- Period-based (daily granularity to come with cash_flow_daily.py)
"""

from decimal import Decimal
from io import BytesIO
from typing import Optional

from accounting.cash_flow_calculator import CashFlow


def _format_currency(value: Decimal) -> str:
    """Format decimal as Brazilian Real currency"""
    abs_value = abs(value)
    formatted = f"{abs_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if value < 0:
        return f"(R$ {formatted})"
    return f"R$ {formatted}"


def export_cash_flow_to_pdf(cash_flow: CashFlow, logo_bytes: bytes = None) -> bytes:
    """
    Export Cash Flow to PDF format - V2 green theme

    Args:
        cash_flow: CashFlow object
        logo_bytes: Optional PNG/JPEG bytes for the header logo

    Returns:
        PDF file as bytes
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, inch, mm
    from reportlab.platypus import (
        Image as RLImage,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=10 * mm, bottomMargin=10 * mm)
    story = []
    styles = getSampleStyleSheet()

    # Logo header
    if logo_bytes:
        try:
            img = RLImage(BytesIO(logo_bytes), width=5 * cm, height=2 * cm, kind="proportional")
            img.hAlign = "CENTER"
            story.append(img)
            story.append(Spacer(1, 3 * mm))
        except Exception:
            pass

    # Title style - green theme
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#1B5E20"),
        spaceAfter=20,
        alignment=1,  # Center
    )

    subtitle_style = ParagraphStyle(
        "CustomSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#666666"),
        spaceAfter=10,
        alignment=1,
    )

    # Title
    story.append(Paragraph("FLUXO DE CAIXA", title_style))
    story.append(Paragraph(cash_flow.company_name, subtitle_style))
    if cash_flow.cnpj:
        story.append(Paragraph(f"CNPJ: {cash_flow.cnpj}", subtitle_style))

    story.append(Paragraph(
        f"Período: {cash_flow.start_date.strftime('%d/%m/%Y')} a {cash_flow.end_date.strftime('%d/%m/%Y')}",
        subtitle_style,
    ))
    story.append(Paragraph(
        f"Método: {'Indireto' if cash_flow.method == 'indirect' else 'Direto'}",
        subtitle_style,
    ))
    story.append(Spacer(1, 15))

    # Build table data
    table_data = []

    # Header
    table_data.append([
        Paragraph("<b>Descrição</b>", styles["Normal"]),
        Paragraph(f"<b>{cash_flow.end_date.year}</b>", styles["Normal"]),
    ])

    # SALDO INICIAL
    table_data.append(["SALDO INICIAL", _format_currency(cash_flow.cash_beginning)])

    # OPERATING ACTIVITIES
    table_data.append(["", ""])
    table_data.append(["ATIVIDADES OPERACIONAIS", ""])
    for label, value in cash_flow.operating_activities.line_items.items():
        table_data.append([f"  {label}", _format_currency(value)])
    table_data.append([
        "Caixa Líquido das Atividades Operacionais",
        _format_currency(cash_flow.net_cash_from_operations)
    ])

    # INVESTING ACTIVITIES
    table_data.append(["", ""])
    table_data.append(["ATIVIDADES DE INVESTIMENTO", ""])
    for label, value in cash_flow.investing_activities.line_items.items():
        table_data.append([f"  {label}", _format_currency(value)])
    table_data.append([
        "Caixa Líquido das Atividades de Investimento",
        _format_currency(cash_flow.net_cash_from_investments)
    ])

    # FINANCING ACTIVITIES
    table_data.append(["", ""])
    table_data.append(["ATIVIDADES DE FINANCIAMENTO", ""])
    for label, value in cash_flow.financing_activities.line_items.items():
        table_data.append([f"  {label}", _format_currency(value)])
    table_data.append([
        "Caixa Líquido das Atividades de Financiamento",
        _format_currency(cash_flow.net_cash_from_financing)
    ])

    # TOTALS
    table_data.append(["", ""])
    table_data.append(["AUMENTO/REDUÇÃO LÍQUIDO DE CAIXA", _format_currency(cash_flow.net_increase_in_cash)])
    table_data.append(["SALDO FINAL", _format_currency(cash_flow.cash_ending)])

    # Create table
    table = Table(table_data, colWidths=[130 * mm, 50 * mm])

    table.setStyle(TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4CAF50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        # General
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        # Alternating rows
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f8e9")]),
    ]))

    # Highlight totals and section headers
    for i, row_data in enumerate(table_data):
        if row_data[0] in ["SALDO INICIAL", "SALDO FINAL",
                           "ATIVIDADES OPERACIONAIS", "ATIVIDADES DE INVESTIMENTO",
                           "ATIVIDADES DE FINANCIAMENTO",
                           "AUMENTO/REDUÇÃO LÍQUIDO DE CAIXA"]:
            table.setStyle(TableStyle([
                ("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"),
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#C8E6C9")),
            ]))
        elif row_data[0].startswith("Caixa Líquido"):
            table.setStyle(TableStyle([
                ("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"),
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#E8F5E9")),
            ]))

    story.append(table)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes


def export_cash_flow_to_excel(cash_flow: CashFlow, logo_bytes: bytes = None) -> bytes:
    """
    Export Cash Flow to Excel format matching ControlladorIA template style.

    Layout:
    - B2: "FLUXO DE CAIXA - {year}"
    - Green color scheme
    - Saldo Inicial -> Activities -> Saldo Final structure

    Args:
        cash_flow: CashFlow object
        logo_bytes: Optional PNG/JPEG bytes for the header logo

    Returns:
        Excel file as bytes
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "FLUXO DE CAIXA"

    # Logo header (floats over A1)
    if logo_bytes:
        try:
            from openpyxl.drawing.image import Image as XLImage
            xl_img = XLImage(BytesIO(logo_bytes))
            xl_img.width = 140
            xl_img.height = 50
            ws.add_image(xl_img, "A1")
        except Exception:
            pass

    # Styles
    green_fill = PatternFill(start_color="4CAF50", end_color="4CAF50", fill_type="solid")
    light_green_fill = PatternFill(start_color="C8E6C9", end_color="C8E6C9", fill_type="solid")
    subtotal_fill = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")

    title_font = Font(name="Arial", size=14, bold=True, color="1B5E20")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    section_font = Font(name="Arial", size=11, bold=True)
    total_font = Font(name="Arial", size=11, bold=True)
    normal_font = Font(name="Arial", size=10)
    sub_font = Font(name="Arial", size=10, color="333333")

    thin_border = Border(
        left=Side(style="thin", color="BDBDBD"),
        right=Side(style="thin", color="BDBDBD"),
        top=Side(style="thin", color="BDBDBD"),
        bottom=Side(style="thin", color="BDBDBD"),
    )

    year_str = str(cash_flow.end_date.year)

    # Title
    ws["B2"] = f"FLUXO DE CAIXA - {year_str}"
    ws["B2"].font = title_font
    ws.merge_cells("B2:D2")

    ws["B3"] = cash_flow.company_name
    ws["B3"].font = Font(name="Arial", size=11, color="666666")

    # Method
    ws["B4"] = f"Método: {'Indireto' if cash_flow.method == 'indirect' else 'Direto'}"
    ws["B4"].font = Font(name="Arial", size=10, color="999999")

    # Column header
    ws["D5"] = year_str
    ws["D5"].font = header_font
    ws["D5"].fill = green_fill
    ws["D5"].alignment = Alignment(horizontal="center")
    ws["D5"].border = thin_border

    row = 6

    def write_section_header(label):
        nonlocal row
        ws[f"B{row}"] = label
        ws[f"B{row}"].font = section_font
        ws[f"B{row}"].fill = light_green_fill
        ws[f"D{row}"].fill = light_green_fill
        for col in ["B", "D"]:
            ws[f"{col}{row}"].border = thin_border
        row += 1

    def write_line(label, value, is_total=False, level=0):
        nonlocal row
        ws[f"B{row}"] = ("  " * level) + label
        ws[f"D{row}"] = float(value)
        ws[f"D{row}"].number_format = '#,##0.00'
        ws[f"D{row}"].alignment = Alignment(horizontal="right")

        if is_total:
            ws[f"B{row}"].font = total_font
            ws[f"D{row}"].font = total_font
            for col in ["B", "D"]:
                ws[f"{col}{row}"].fill = subtotal_fill
        else:
            ws[f"B{row}"].font = sub_font if level > 0 else normal_font
            ws[f"D{row}"].font = normal_font

        for col in ["B", "D"]:
            ws[f"{col}{row}"].border = thin_border
        row += 1

    # SALDO INICIAL
    write_section_header("SALDO INICIAL")
    write_line("Saldo de Caixa", cash_flow.cash_beginning, is_total=True)
    row += 1

    # ATIVIDADES OPERACIONAIS
    write_section_header("ATIVIDADES OPERACIONAIS")
    for label, value in cash_flow.operating_activities.line_items.items():
        write_line(label, value, level=1)
    write_line("Caixa Líquido das Atividades Operacionais", cash_flow.net_cash_from_operations, is_total=True)
    row += 1

    # ATIVIDADES DE INVESTIMENTO
    write_section_header("ATIVIDADES DE INVESTIMENTO")
    for label, value in cash_flow.investing_activities.line_items.items():
        write_line(label, value, level=1)
    write_line("Caixa Líquido das Atividades de Investimento", cash_flow.net_cash_from_investments, is_total=True)
    row += 1

    # ATIVIDADES DE FINANCIAMENTO
    write_section_header("ATIVIDADES DE FINANCIAMENTO")
    for label, value in cash_flow.financing_activities.line_items.items():
        write_line(label, value, level=1)
    write_line("Caixa Líquido das Atividades de Financiamento", cash_flow.net_cash_from_financing, is_total=True)
    row += 1

    # TOTALS
    write_section_header("RESULTADO")
    write_line("Aumento/Redução Líquido de Caixa", cash_flow.net_increase_in_cash, is_total=True)
    write_line("Saldo Final de Caixa", cash_flow.cash_ending, is_total=True)

    # Column widths
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 45
    ws.column_dimensions["C"].width = 2
    ws.column_dimensions["D"].width = 18

    # Save to bytes
    buffer = BytesIO()
    wb.save(buffer)
    excel_bytes = buffer.getvalue()
    buffer.close()

    return excel_bytes


def export_cash_flow_to_csv(cash_flow: CashFlow) -> str:
    """
    Export Cash Flow to CSV format - V2

    Args:
        cash_flow: CashFlow object

    Returns:
        CSV file as string
    """
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    year_str = str(cash_flow.end_date.year)

    # Header
    writer.writerow([f"FLUXO DE CAIXA - {year_str}"])
    writer.writerow([cash_flow.company_name])
    if cash_flow.cnpj:
        writer.writerow([f"CNPJ: {cash_flow.cnpj}"])
    writer.writerow([
        f"Período: {cash_flow.start_date.strftime('%d/%m/%Y')} a {cash_flow.end_date.strftime('%d/%m/%Y')}"
    ])
    writer.writerow([f"Método: {'Indireto' if cash_flow.method == 'indirect' else 'Direto'}"])
    writer.writerow([])

    # Column headers
    writer.writerow(["Descrição", year_str])

    # SALDO INICIAL
    writer.writerow(["SALDO INICIAL", f"{float(cash_flow.cash_beginning):.2f}"])
    writer.writerow([])

    # OPERATING ACTIVITIES
    writer.writerow(["ATIVIDADES OPERACIONAIS", ""])
    for label, value in cash_flow.operating_activities.line_items.items():
        writer.writerow([f"  {label}", f"{float(value):.2f}"])
    writer.writerow([
        "Caixa Líquido das Atividades Operacionais",
        f"{float(cash_flow.net_cash_from_operations):.2f}"
    ])
    writer.writerow([])

    # INVESTING ACTIVITIES
    writer.writerow(["ATIVIDADES DE INVESTIMENTO", ""])
    for label, value in cash_flow.investing_activities.line_items.items():
        writer.writerow([f"  {label}", f"{float(value):.2f}"])
    writer.writerow([
        "Caixa Líquido das Atividades de Investimento",
        f"{float(cash_flow.net_cash_from_investments):.2f}"
    ])
    writer.writerow([])

    # FINANCING ACTIVITIES
    writer.writerow(["ATIVIDADES DE FINANCIAMENTO", ""])
    for label, value in cash_flow.financing_activities.line_items.items():
        writer.writerow([f"  {label}", f"{float(value):.2f}"])
    writer.writerow([
        "Caixa Líquido das Atividades de Financiamento",
        f"{float(cash_flow.net_cash_from_financing):.2f}"
    ])
    writer.writerow([])

    # TOTALS
    writer.writerow(["AUMENTO/REDUÇÃO LÍQUIDO DE CAIXA", f"{float(cash_flow.net_increase_in_cash):.2f}"])
    writer.writerow(["SALDO FINAL", f"{float(cash_flow.cash_ending):.2f}"])

    csv_string = output.getvalue()
    output.close()

    return csv_string
