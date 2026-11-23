from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl, computed_field, model_validator
from pydantic_core import PydanticCustomError

NAIROBI = ZoneInfo("Africa/Nairobi")
DAILY_REVENUE_DISPLAY_DAYS = 31
BranchName = Annotated[str, Field(min_length=1, max_length=100)]


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
    breakdown: Literal["total", "daily", "trend"] = "total"
    include_daily_gateways: bool = False


class ConversationContext(BaseModel):
    branch_id: str
    period: RevenuePeriod | None = None
    comparison_month: date | None = None

    @property
    def reference_month(self) -> date | None:
        if self.period is None:
            return self.comparison_month
        month = self.period.start_date.replace(day=1)
        return month if self.period.end_date.replace(day=1) == month else None


class BranchConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    base_url: HttpUrl
    token_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")

    @model_validator(mode="after")
    def secure_origin(self) -> Self:
        if (
            self.base_url.username
            or self.base_url.password
            or self.base_url.query
            or self.base_url.fragment
        ):
            raise ValueError(
                "Use an API base URL without credentials, query or fragment"
            )
        if self.base_url.scheme != "https" and self.base_url.host not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("Remote inventory APIs require HTTPS")
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


class RevenueSummary(BaseModel):
    schema_version: Literal[1]
    branch: BranchIdentity
    start_date: date
    end_date: date
    timezone: Literal["Africa/Nairobi"]
    currency: Literal["KES"]
    generated_at: AwareDatetime
    is_provisional: bool
    totals: RevenueAmounts


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
        if trend_requested and len(daily) >= 14:
            previous, latest = daily[-14:-7], daily[-7:]
            trend = RevenueTrend(
                latest=RevenuePeriod(start_date=latest[0].date, end_date=latest[-1].date),
                previous=RevenuePeriod(start_date=previous[0].date, end_date=previous[-1].date),
                latest_total=sum((row.total_revenue for row in latest), Decimal(0)),
                previous_total=sum((row.total_revenue for row in previous), Decimal(0)),
            )
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


class RevenueProblem(BaseModel):
    branch: str
    status: Literal[
        "unknown_branch",
        "authentication_failed",
        "not_deployed",
        "backend_unavailable",
        "invalid_response",
        "invalid_request",
    ]
    message: str
    available_branches: list[str] = Field(default_factory=list)
