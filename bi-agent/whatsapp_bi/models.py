from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl, computed_field, model_validator

NAIROBI = ZoneInfo("Africa/Nairobi")
BranchName = Annotated[str, Field(min_length=1, max_length=100)]


def normalize_branch(value: str) -> str:
    return "-".join(value.strip().casefold().split())


class RevenuePeriod(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days >= 366:
            raise ValueError("Request at most 366 days at a time")
        return self


class RevenueQuery(RevenuePeriod):
    branch: BranchName


class ConversationContext(BaseModel):
    branch_id: str
    period: RevenuePeriod | None = None


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
