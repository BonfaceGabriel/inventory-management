from asyncio import gather
from typing import Literal

from pydantic import BaseModel

from .client import RevenueClient
from .models import (
    BranchConfig,
    RevenuePeriod,
    RevenueProblem,
    RevenueQuery,
    RevenueSummary,
    RevenueTrend,
    SalesSummary,
)

GrowthMetric = Literal["revenue", "sales"]


class BranchGrowthRow(BaseModel):
    branch: str
    trend: RevenueTrend | None = None


class BranchGrowthReport(BaseModel):
    metric: GrowthMetric
    period: RevenuePeriod
    baseline: RevenuePeriod
    is_provisional: bool
    rows: list[BranchGrowthRow]

    @property
    def leaders(self) -> list[str]:
        if any(row.trend is None for row in self.rows):
            return []
        eligible = [
            (row.trend.percent_change, row.branch)
            for row in self.rows if row.trend is not None and row.trend.percent_change is not None
        ]
        if len(eligible) < 2:
            return []
        best = max(percent for percent, _ in eligible)
        return [branch for percent, branch in eligible if percent == best]


async def compare_branch_growth(
    client: RevenueClient, metric: GrowthMetric, period: RevenuePeriod, baseline: RevenuePeriod
) -> BranchGrowthReport | RevenueProblem:
    if (
        baseline.end_date >= period.start_date
        or baseline.end_date - baseline.start_date != period.end_date - period.start_date
    ):
        return RevenueProblem(
            branch="all branches", status="invalid_growth_periods",
            message="Choose two non-overlapping periods of the same length, with the baseline first in time.",
        )

    async def read_branch(branch: BranchConfig) -> BranchGrowthRow:
        fetch = client.get_revenue if metric == "revenue" else client.get_sales
        current, previous = await gather(
            fetch(RevenueQuery(branch=branch.id, **period.model_dump())),
            fetch(RevenueQuery(branch=branch.id, **baseline.model_dump())),
        )
        if isinstance(current, RevenueProblem) or isinstance(previous, RevenueProblem):
            return BranchGrowthRow(branch=branch.name)

        def amount(report: RevenueSummary | SalesSummary):
            return report.total_sales if isinstance(report, SalesSummary) else report.totals.total_revenue

        return BranchGrowthRow(branch=branch.name, trend=RevenueTrend(
            latest=period, previous=baseline, latest_total=amount(current), previous_total=amount(previous),
        ))

    return BranchGrowthReport(
        metric=metric, period=period, baseline=baseline, is_provisional=period.end_date == client.today,
        rows=await gather(*(read_branch(branch) for branch in client.branches)),
    )
