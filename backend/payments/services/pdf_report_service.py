"""
PDF Report Generation Service

Generates professional PDF reports for reconciliation and financial reporting.
Uses ReportLab for PDF generation.
"""

from decimal import Decimal
from datetime import date, datetime
from io import BytesIO
from typing import Dict, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, Image
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from django.utils import timezone
import logging

from .reconciliation_service import ReconciliationService

logger = logging.getLogger(__name__)


class PDFReportService:
    """
    Service for generating PDF reports.

    Provides methods to:
    - Generate daily reconciliation PDF
    - Generate date range reconciliation PDF
    - Format currency and numbers
    - Create professional layouts
    """

    @staticmethod
    def generate_daily_reconciliation_pdf(report_date: date = None) -> BytesIO:
        """
        Generate PDF for daily reconciliation report.

        Args:
            report_date: Date to generate report for (defaults to today)

        Returns:
            BytesIO object containing the PDF
        """
        if report_date is None:
            report_date = timezone.now().date()

        logger.info(f"Generating PDF reconciliation report for {report_date}")

        # Get report data
        report_data = ReconciliationService.generate_daily_report(report_date)

        # Create PDF buffer
        buffer = BytesIO()

        # Create PDF document
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
        )

        # Container for the 'Flowable' objects
        elements = []

        # Get styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a202c'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#2d3748'),
            spaceAfter=12,
            spaceBefore=12
        )
        normal_style = styles['Normal']

        # Title
        title = Paragraph(
            f"Daily Reconciliation Report<br/>{report_date.strftime('%B %d, %Y')}",
            title_style
        )
        elements.append(title)
        elements.append(Spacer(1, 12))

        # Report metadata
        metadata_data = [
            ['Generated:', timezone.now().strftime('%Y-%m-%d %H:%M:%S')],
            ['Report Date:', report_data['report_date']],
            ['Total Transactions:', str(report_data['summary']['total_transactions'])],
            ['Total Gateways:', str(report_data['summary']['gateways_count'])],
        ]
        metadata_table = Table(metadata_data, colWidths=[2*inch, 4*inch])
        metadata_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f7fafc')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2d3748')),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        elements.append(metadata_table)
        elements.append(Spacer(1, 20))

        # Overall Summary
        elements.append(Paragraph("Overall Summary", heading_style))
        summary_data = [
            ['Metric', 'Amount (KES)'],
            ['Total Amount', PDFReportService._format_currency(report_data['overall_totals']['total_amount'])],
            ['To Parent Company', PDFReportService._format_currency(report_data['overall_totals']['total_parent_settlement'])],
            ['To Shop', PDFReportService._format_currency(report_data['overall_totals']['total_shop_amount'])],
        ]
        summary_table = Table(summary_data, colWidths=[3*inch, 3*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a5568')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e0')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 20))

        # Gateway-wise breakdown
        elements.append(Paragraph("Gateway-wise Breakdown", heading_style))

        for gateway_report in report_data['gateway_reports']:
            # Gateway header
            gateway_header = Paragraph(
                f"<b>{gateway_report['gateway_name']}</b> ({gateway_report['gateway_number']})",
                normal_style
            )
            elements.append(gateway_header)
            elements.append(Spacer(1, 6))

            # Gateway summary
            gateway_data = [
                ['Transactions', 'Amount', 'Parent Settlement', 'Shop Amount'],
                [
                    str(gateway_report['transaction_count']),
                    PDFReportService._format_currency(gateway_report['total_amount']),
                    PDFReportService._format_currency(gateway_report['settlement']['parent_amount']),
                    PDFReportService._format_currency(gateway_report['settlement']['shop_amount']),
                ]
            ]
            gateway_table = Table(gateway_data, colWidths=[1.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
            gateway_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf2f7')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2d3748')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
            ]))
            elements.append(gateway_table)

            # Settlement note
            if gateway_report['settlement']['calculation_note']:
                note = Paragraph(
                    f"<i>Note: {gateway_report['settlement']['calculation_note']}</i>",
                    ParagraphStyle('Note', parent=normal_style, fontSize=8, textColor=colors.HexColor('#718096'))
                )
                elements.append(Spacer(1, 4))
                elements.append(note)

            elements.append(Spacer(1, 16))

        # Status Breakdown
        elements.append(Paragraph("Transaction Status Breakdown", heading_style))
        status_data = [['Status', 'Count', 'Total Amount (KES)']]
        for status_code, status_info in report_data['status_breakdown'].items():
            if status_info['count'] > 0:
                status_data.append([
                    status_info['label'],
                    str(status_info['count']),
                    PDFReportService._format_currency(status_info['total_amount'])
                ])

        status_table = Table(status_data, colWidths=[2.5*inch, 1.5*inch, 2*inch])
        status_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf2f7')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2d3748')),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ]))
        elements.append(status_table)
        elements.append(Spacer(1, 20))

        # Manual Payments
        if report_data['manual_payments']['total_count'] > 0:
            elements.append(Paragraph("Manual Payments", heading_style))
            manual_data = [['Payment Method', 'Count', 'Total Amount (KES)']]
            for method_code, method_info in report_data['manual_payments']['by_method'].items():
                manual_data.append([
                    method_info['label'],
                    str(method_info['count']),
                    PDFReportService._format_currency(method_info['total_amount'])
                ])

            # Add total row
            manual_data.append([
                'Total',
                str(report_data['manual_payments']['total_count']),
                PDFReportService._format_currency(report_data['manual_payments']['total_amount'])
            ])

            manual_table = Table(manual_data, colWidths=[2.5*inch, 1.5*inch, 2*inch])
            manual_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf2f7')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2d3748')),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
                # Highlight total row
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e2e8f0')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ]))
            elements.append(manual_table)

        # Footer
        elements.append(Spacer(1, 40))
        footer_text = Paragraph(
            f"<i>Report generated by Payment Management System on {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</i>",
            ParagraphStyle('Footer', parent=normal_style, fontSize=8, textColor=colors.HexColor('#a0aec0'), alignment=TA_CENTER)
        )
        elements.append(footer_text)

        # Build PDF
        doc.build(elements)

        # Get the value of the BytesIO buffer and return it
        buffer.seek(0)
        logger.info(f"Successfully generated PDF for {report_date}")
        return buffer

    @staticmethod
    def generate_date_range_reconciliation_pdf(start_date: date, end_date: date) -> BytesIO:
        """
        Generate PDF for date range reconciliation report.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            BytesIO object containing the PDF
        """
        logger.info(f"Generating PDF reconciliation report from {start_date} to {end_date}")

        # Get report data
        report_data = ReconciliationService.generate_date_range_report(start_date, end_date)

        # Create PDF buffer
        buffer = BytesIO()

        # Create PDF document
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
        )

        elements = []
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=colors.HexColor('#1a202c'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#2d3748'),
            spaceAfter=12,
            spaceBefore=12
        )

        # Title
        title = Paragraph(
            f"Reconciliation Report<br/>{start_date.strftime('%b %d, %Y')} - {end_date.strftime('%b %d, %Y')}",
            title_style
        )
        elements.append(title)
        elements.append(Spacer(1, 20))

        # Grand Totals
        elements.append(Paragraph("Grand Totals", heading_style))
        grand_totals_data = [
            ['Metric', 'Amount (KES)'],
            ['Total Transactions', str(report_data['grand_totals']['total_transactions'])],
            ['Total Amount', PDFReportService._format_currency(report_data['grand_totals']['total_amount'])],
            ['To Parent Company', PDFReportService._format_currency(report_data['grand_totals']['total_parent_settlement'])],
            ['To Shop', PDFReportService._format_currency(report_data['grand_totals']['total_shop_amount'])],
            ['Number of Days', str(report_data['date_range']['days'])],
        ]

        grand_table = Table(grand_totals_data, colWidths=[3*inch, 3*inch])
        grand_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a5568')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e0')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(grand_table)
        elements.append(Spacer(1, 20))

        # Daily summaries
        elements.append(Paragraph("Daily Breakdown", heading_style))

        daily_summary_data = [['Date', 'Transactions', 'Total Amount', 'To Parent', 'To Shop']]
        for daily_report in report_data['daily_reports']:
            daily_summary_data.append([
                daily_report['report_date'],
                str(daily_report['summary']['total_transactions']),
                PDFReportService._format_currency(daily_report['summary']['total_amount']),
                PDFReportService._format_currency(daily_report['summary']['total_to_parent']),
                PDFReportService._format_currency(daily_report['summary']['total_to_shop']),
            ])

        daily_table = Table(daily_summary_data, colWidths=[1.2*inch, 1.2*inch, 1.4*inch, 1.4*inch, 1.4*inch])
        daily_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf2f7')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2d3748')),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ]))
        elements.append(daily_table)

        # Footer
        elements.append(Spacer(1, 40))
        footer_text = Paragraph(
            f"<i>Report generated by Payment Management System on {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</i>",
            ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#a0aec0'), alignment=TA_CENTER)
        )
        elements.append(footer_text)

        # Build PDF
        doc.build(elements)

        buffer.seek(0)
        logger.info(f"Successfully generated date range PDF from {start_date} to {end_date}")
        return buffer

    @staticmethod
    def _format_currency(amount: float) -> str:
        """
        Format amount as currency string.

        Args:
            amount: Amount to format

        Returns:
            Formatted currency string
        """
        return f"{amount:,.2f}"
