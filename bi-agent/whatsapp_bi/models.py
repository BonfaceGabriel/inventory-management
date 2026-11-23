from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, BeforeValidator, Field, HttpUrl, computed_field, model_validator
from pydantic_core import PydanticCustomError

NAIROBI = ZoneInfo("Africa/Nairobi")
DAILY_REVENUE_DISPLAY_DAYS = 31
BranchName = Annotated[str, Field(min_length=1, max_length=100)]


def _require_decimal_string(amount):
    if not isinstance(amount, (str, Decimal)):
        raise ValueError("Use a decimal string for money")
    return amount


ExactAmount = Annotated[
    Decimal, BeforeValidator(_require_decimal_string), Field(allow_inf_nan=False, decimal_places=2)
]


def normalize_branch(value: str) -> str:
    return "-".join(value.strip().casefold().split())


class RevenuePeriod(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.end_date < self.start_date:
            raise PydanticCustomError("revenue_dates_out_of_order", "end_date must be on or after start_date")
        if (self.end_date - self.start_date).days >= 366:
            raise PydanticCustomError("revenue_range_too_long", "Request at most 366 days at a time")
        return self


class RevenueQuery(RevenuePeriod):
    branch: BranchName


class RevenueToolQuery(RevenueQuery):
    breakdown: Literal["total", "daily", "trend", "monthly"] = "total"
    include_daily_gateways: bool = False


class SalesToolQuery(RevenueQuery):
    breakdown: Literal["total", "daily", "trend", "monthly"] = "total"


class ConversationContext(BaseModel):
    branch_id: str
    period: RevenuePeriod | None = None
    comparison_month: date | None = None
    metric: Literal["revenue", "sales", "reconciliation", "product performance", "merchandise", "stock"] = "revenue"

    @property
    def reference_month(self) -> date | None:
        if self.period is None:
            return self.comparison_month
        month = self.period.start_date.replace(day=1)
        return month if self.period.end_date.replace(day=1) == month else None


def validate_api_base_url(url: HttpUrl) -> HttpUrl:
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("Use an API base URL without credentials, query or fragment")
    if url.scheme != "https" and url.host not in {"localhost", "127.0.0.1", "[::1]"}:
        raise ValueError("Remote inventory APIs require HTTPS")
    return url


class BranchConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    base_url: HttpUrl
    token_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")

    @model_validator(mode="after")
    def secure_origin(self) -> Self:
        validate_api_base_url(self.base_url)
        return self


class BranchIdentity(BaseModel):
    id: str
    name: str


class RevenueAmounts(BaseModel):
    paybill: Decimal
    pdq: Decimal
    till: Decimal
    total_revenue: Decimal
    transaction_count: int = Field(ge=0)

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        amounts = (self.paybill, self.pdq, self.till, self.total_revenue)
        if any(
            not amount.is_finite() or amount != amount.quantize(Decimal("0.01"))
            for amount in amounts
        ):
            raise ValueError("Amounts must be finite and expressed in whole cents")
        if self.total_revenue != self.paybill + self.pdq + self.till:
            raise ValueError("Gateway amounts do not match total revenue")
        return self


class DailyRevenue(RevenueAmounts):
    date: date


class BranchReport(BaseModel):
    schema_version: Literal[1]
    branch: BranchIdentity
    start_date: date
    end_date: date
    timezone: Literal["Africa/Nairobi"]
    currency: Literal["KES"]
    generated_at: AwareDatetime
    is_provisional: bool


class RevenueSummary(BranchReport):
    totals: RevenueAmounts


class SalesSummary(BranchReport):
    total_sales: ExactAmount = Field(ge=0)


class DailySales(BaseModel):
    date: date
    total_sales: ExactAmount = Field(ge=0)


class SalesSeries(SalesSummary):
    daily: list[DailySales]

    @model_validator(mode="after")
    def verify_daily_coverage(self) -> Self:
        days = (self.end_date - self.start_date).days + 1
        expected = [self.start_date + timedelta(days=i) for i in range(days)]
        if not 1 <= days <= 366 or [row.date for row in self.daily] != expected:
            raise ValueError("Unexpected daily sales coverage")
        if sum(row.total_sales for row in self.daily) != self.total_sales:
            raise ValueError("Daily sales do not match the period total")
        return self


class RankedProduct(BaseModel):
    name: str
    code: str
    units_sold: int = Field(gt=0)
    sales_value: ExactAmount = Field(ge=0)


class ProductReport(BranchReport):
    products: list[RankedProduct]


PageNumber = Annotated[int, Field(ge=1)]


class InventoryReport(BranchReport):
    page: PageNumber
    page_count: PageNumber


class MerchandiseItem(BaseModel):
    code: str
    name: str
    units_sold: int = Field(ge=0)
    sales_value: ExactAmount = Field(ge=0)
    remaining_units: int = Field(ge=0)
    remaining_catalog_value: ExactAmount = Field(ge=0)


class MerchandiseReport(InventoryReport):
    total_fulfilled: ExactAmount = Field(ge=0)
    previous_day_total: ExactAmount | None = Field(default=None, ge=0)
    items: list[MerchandiseItem] = Field(max_length=8)


class StockItem(BaseModel):
    code: str
    name: str
    quantity: int
    reorder_level: int
    status: Literal["LOW_STOCK", "OUT_OF_STOCK"]


class StockReport(InventoryReport):
    total_stock_value_at_cost: ExactAmount
    low_stock_count: int = Field(ge=0)
    out_of_stock_count: int = Field(ge=0)
    items: list[StockItem] = Field(max_length=8)


class ReconciliationSummary(BranchReport):
    x_value: ExactAmount
    y_value: ExactAmount
    result: ExactAmount
    is_balanced: bool


class RevenueComparison(BaseModel):
    period: RevenueSummary
    baseline: RevenueSummary

    @computed_field
    @property
    def change(self) -> Decimal:
        return self.period.totals.total_revenue - self.baseline.totals.total_revenue


class RevenueReport(RevenueSummary):
    daily: list[DailyRevenue]

    @model_validator(mode="after")
    def verify_daily_coverage(self) -> Self:
        days = (self.end_date - self.start_date).days + 1
        if not 1 <= days <= 366:
            raise ValueError("Unexpected response date range")
        expected = [self.start_date + timedelta(days=i) for i in range(days)]
        if [row.date for row in self.daily] != expected:
            raise ValueError("Daily coverage is incomplete, duplicated, or unordered")
        for field in ("paybill", "pdq", "till", "total_revenue", "transaction_count"):
            if sum(getattr(row, field) for row in self.daily) != getattr(
                self.totals, field
            ):
                raise ValueError(f"Daily {field} does not match its period total")
        return self


class RevenueTrend(BaseModel):
    latest: RevenuePeriod
    previous: RevenuePeriod
    latest_total: Decimal
    previous_total: Decimal

    @computed_field
    @property
    def change(self) -> Decimal:
        return self.latest_total - self.previous_total

    @computed_field
    @property
    def percent_change(self) -> Decimal | None:
        if self.previous_total == 0:
            return Decimal(0) if self.latest_total == 0 else None
        return (self.change / self.previous_total * 100).quantize(Decimal("0.01"))

    @classmethod
    def for_daily_rows(cls, rows: list[tuple[date, Decimal]]) -> Self | None:
        if len(rows) < 14:
            return None
        previous, latest = rows[-14:-7], rows[-7:]
        return cls(
            latest=RevenuePeriod(start_date=latest[0][0], end_date=latest[-1][0]),
            previous=RevenuePeriod(start_date=previous[0][0], end_date=previous[-1][0]),
            latest_total=sum((amount for _, amount in latest), Decimal(0)),
            previous_total=sum((amount for _, amount in previous), Decimal(0)),
        )


class DailyRevenueTotal(BaseModel):
    date: date
    total_revenue: Decimal


class DailyRevenueBreakdown(RevenueSummary):
    days: list[DailyRevenueTotal | DailyRevenue]
    day_count: int
    trend_requested: bool = False
    trend: RevenueTrend | None = None

    @classmethod
    def from_report(
        cls, report: RevenueReport, *, trend_requested: bool = False, include_gateways: bool = False
    ) -> Self:
        daily = report.daily
        trend = None
        if trend_requested:
            trend = RevenueTrend.for_daily_rows([(row.date, row.total_revenue) for row in daily])
        return cls(
            **report.model_dump(exclude={"daily"}),
            day_count=len(daily),
            days=[
                row if include_gateways else DailyRevenueTotal(date=row.date, total_revenue=row.total_revenue)
                for row in daily[-DAILY_REVENUE_DISPLAY_DAYS:]
            ],
            trend_requested=trend_requested,
            trend=trend,
        )


class MonthlyAmount(RevenuePeriod):
    amount: Decimal
    coverage: Literal["complete", "current_month", "partial_month"]
    comparison: RevenueTrend | None = None


def monthly_amounts(daily: list[tuple[date, Decimal]], today: date) -> list[MonthlyAmount]:
    months: list[MonthlyAmount] = []
    current_month = today.replace(day=1)
    for month, month_rows in groupby(daily, key=lambda row: row[0].replace(day=1)):
        rows = list(month_rows)
        start, end = rows[0][0], rows[-1][0]
        coverage: Literal["complete", "current_month", "partial_month"] = "complete"
        if month == current_month:
            coverage = "current_month"
        elif start != month or end.day != monthrange(month.year, month.month)[1]:
            coverage = "partial_month"

        total = sum((amount for _, amount in rows), Decimal(0))
        previous = months[-1] if months else None
        comparison = None
        if coverage == "complete" and previous is not None and previous.coverage == "complete":
            comparison = RevenueTrend(
                latest=RevenuePeriod(start_date=start, end_date=end),
                previous=RevenuePeriod(start_date=previous.start_date, end_date=previous.end_date),
                latest_total=total,
                previous_total=previous.amount,
            )
        months.append(MonthlyAmount(
            start_date=start, end_date=end, amount=total, coverage=coverage, comparison=comparison,
        ))
    return months

class MonthlyRevenueTotal(RevenuePeriod):
    total_revenue: Decimal
    coverage: Literal["complete", "current_month", "partial_month"]
    comparison: RevenueTrend | None = None


class MonthlyRevenueBreakdown(RevenueSummary):
    months: list[MonthlyRevenueTotal]

    @classmethod
    def from_report(cls, report: RevenueReport, today: date) -> Self:
        months = [
            MonthlyRevenueTotal(**month.model_dump(exclude={"amount"}), total_revenue=month.amount)
            for month in monthly_amounts([(row.date, row.total_revenue) for row in report.daily], today)
        ]
        return cls(**report.model_dump(exclude={"daily"}), months=months)


class SalesBreakdown(SalesSummary):
    days: list[DailySales] = Field(default_factory=list)
    day_count: int
    months: list[MonthlyAmount] = Field(default_factory=list)
    trend_requested: bool = False
    trend: RevenueTrend | None = None

    @classmethod
    def from_report(cls, report: SalesSeries, breakdown: str, today: date) -> Self:
        dated = [(row.date, row.total_sales) for row in report.daily]
        return cls(
            **report.model_dump(exclude={"daily"}),
            day_count=len(dated),
            days=[] if breakdown == "monthly" else report.daily[-DAILY_REVENUE_DISPLAY_DAYS:],
            months=monthly_amounts(dated, today) if breakdown == "monthly" else [],
            trend_requested=breakdown == "trend",
            trend=RevenueTrend.for_daily_rows(dated) if breakdown == "trend" else None,
        )


class RevenueProblem(BaseModel):
    branch: str
    status: Literal[
        "unknown_branch",
        "authentication_failed",
        "not_deployed",
        "backend_unavailable",
        "invalid_response",
        "invalid_request",
        "incomplete_fulfillment_history",
        "reconciliation_date_required",
        "invalid_growth_periods",
    ]
    message: str
    available_branches: list[str] = Field(default_factory=list)
