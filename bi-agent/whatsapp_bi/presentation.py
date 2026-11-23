from .models import BranchReport, RegistrationReport, RevenuePeriod, RevenueTrend


def format_period(summary: BranchReport | RevenuePeriod) -> str:
    if summary.end_date == summary.start_date:
        return str(summary.start_date)
    return f"{summary.start_date} to {summary.end_date}"


def format_change(trend: RevenueTrend) -> str:
    percent = trend.percent_change
    if percent is None:
        return (
            f"KES {trend.change:+,.2f}. "
            "Percentage undefined because the previous total was KES 0.00."
        )
    return f"{percent:+,.2f}%" if percent else "0.00%"


def registration_lines(report: RegistrationReport) -> list[str]:
    return [
        f"Registrations (kits issued): {report.kits_issued:,}",
        f"Transactions with kits issued: {report.registration_transactions:,}",
        f"Registration margin ({report.kits_issued:,} × KES {report.margin_per_kit:,.2f}): "
        f"KES {report.registration_margin:,.2f}",
    ]
