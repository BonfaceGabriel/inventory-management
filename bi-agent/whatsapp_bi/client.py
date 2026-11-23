import os
from collections.abc import Callable
from datetime import date, datetime
from typing import Literal, TypeVar

import httpx
from pydantic import ValidationError

from .models import (
    NAIROBI,
    BranchConfig,
    BranchReport,
    FullStockReport,
    ProductReport,
    ReceiptEvidence,
    InventoryReport,
    MerchandiseReport,
    ReconciliationSummary,
    RegistrationReport,
    RevenueProblem,
    RevenueQuery,
    RevenueReport,
    SalesSummary,
    SalesSeries,
    StockReport,
    normalize_branch,
)

ReportT = TypeVar("ReportT", bound=BranchReport)


class RevenueClient:
    """Read-only HTTP access. Branch URLs and credentials are application-owned."""

    def __init__(
        self,
        branches: list[BranchConfig],
        http: httpx.AsyncClient,
        *,
        token_lookup: Callable[[str], str | None] = os.getenv,
        clock: Callable[[], date] | None = None,
    ):
        self.branches = branches
        self.http = http
        self._token_lookup = token_lookup
        self._clock = clock or (lambda: datetime.now(NAIROBI).date())
        self._aliases: dict[str, BranchConfig] = {}
        if not branches:
            raise ValueError("Configure at least one inventory branch")
        for branch in branches:
            for alias in {normalize_branch(branch.id), normalize_branch(branch.name)}:
                if alias in self._aliases and self._aliases[alias].id != branch.id:
                    raise ValueError(f"Duplicate branch alias: {alias}")
                self._aliases[alias] = branch
        if len({branch.id for branch in branches}) != len(branches):
            raise ValueError("Branch IDs must be unique")

    @property
    def today(self) -> date:
        return self._clock()

    async def get_revenue(self, query: RevenueQuery) -> RevenueReport | RevenueProblem:
        return await self._get_report(query, "revenue", RevenueReport)

    async def get_receipt_evidence(self, query: RevenueQuery) -> ReceiptEvidence | RevenueProblem:
        return await self._get_report(query, "receipts", ReceiptEvidence)

    async def get_sales(self, query: RevenueQuery, *, daily: bool = False) -> SalesSummary | RevenueProblem:
        if daily:
            return await self._get_report(query, "sales", SalesSeries, daily=True)
        return await self._get_report(query, "sales", SalesSummary)

    async def get_products(self, query: RevenueQuery) -> ProductReport | RevenueProblem:
        return await self._get_report(query, "products", ProductReport)

    async def get_reconciliation(self, query: RevenueQuery) -> ReconciliationSummary | RevenueProblem:
        return await self._get_report(query, "reconciliation", ReconciliationSummary)

    async def get_registrations(self, query: RevenueQuery) -> RegistrationReport | RevenueProblem:
        return await self._get_report(query, "registrations", RegistrationReport)

    async def get_merchandise(self, query: RevenueQuery, page: int) -> MerchandiseReport | RevenueProblem:
        return await self._get_report(query, "inventory", MerchandiseReport, extra_params={"view": "merchandise", "page": page})

    async def get_stock(self, branch: str, page: int) -> StockReport | RevenueProblem:
        today = self.today
        query = RevenueQuery(branch=branch, start_date=today, end_date=today)
        return await self._get_report(query, "inventory", StockReport, extra_params={"view": "stock", "page": page})

    async def get_full_stock(self, branch: str) -> FullStockReport | RevenueProblem:
        first = await self.get_stock(branch, 1)
        if isinstance(first, RevenueProblem):
            return first

        incomplete = RevenueProblem(
            branch=branch,
            status="invalid_response",
            message="The branch returned inconsistent stock alert pages.",
        )
        stock_fields = {"generated_at", "page", "items"}
        summary = first.model_dump(exclude=stock_fields)
        items = list(first.items)
        for page in range(2, first.page_count + 1):
            result = await self.get_stock(branch, page)
            if isinstance(result, RevenueProblem):
                return result
            if result.model_dump(exclude=stock_fields) != summary:
                return incomplete
            items.extend(result.items)

        if (
            len({item.code for item in items}) != len(items)
            or sum(item.status == "LOW_STOCK" for item in items) != first.low_stock_count
            or sum(item.status == "OUT_OF_STOCK" for item in items) != first.out_of_stock_count
        ):
            return incomplete
        return FullStockReport.model_validate({**first.model_dump(), "items": items})

    async def _get_report(
        self,
        query: RevenueQuery,
        metric: Literal["revenue", "receipts", "sales", "reconciliation", "products", "inventory", "registrations"],
        response_model: type[ReportT],
        *,
        daily: bool = False,
        extra_params: dict[str, str | int] | None = None,
    ) -> ReportT | RevenueProblem:
        def problem(status, message):
            return RevenueProblem(
                branch=query.branch,
                status=status,
                message=message,
                available_branches=[branch.name for branch in self.branches],
            )

        branch = self._aliases.get(normalize_branch(query.branch))
        if branch is None:
            return problem("unknown_branch", "Choose a branch from available_branches.")
        if query.end_date > self.today:
            return problem("invalid_request", f"Future {metric} dates cannot be queried.")
        token = self._token_lookup(branch.token_env)
        if not token:
            return problem(
                "authentication_failed",
                "The BI service credential is not configured for this branch.",
            )

        url = str(branch.base_url).rstrip("/") + f"/agent/{metric}/"
        params = {
            "start_date": query.start_date.isoformat(),
            "end_date": query.end_date.isoformat(),
            **(extra_params or {}),
        }
        if daily:
            params["daily"] = "true"
        try:
            response = await self.http.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=15.0,
                follow_redirects=False,
            )
        except httpx.RequestError:
            return problem(
                "backend_unavailable",
                f"The branch API could not be reached; {metric} is unavailable.",
            )

        if response.status_code in {401, 403}:
            return problem(
                "authentication_failed",
                "The branch API rejected the BI service credential.",
            )
        if response.status_code == 404:
            return problem(
                "not_deployed",
                f"The read-only {metric} endpoint is not deployed at this branch.",
            )
        if response.status_code == 400:
            return problem(
                "invalid_request", "The branch API rejected the requested date range."
            )
        if response.status_code == 409 and metric in {"sales", "products"}:
            return problem(
                "incomplete_fulfillment_history",
                "The branch records cannot assign all fulfilled amounts to the requested dates.",
            )
        if response.status_code != 200:
            return problem(
                "backend_unavailable",
                f"The branch API did not return a successful {metric} response.",
            )

        try:
            report = response_model.model_validate_json(response.content)
        except (ValidationError, ValueError):
            return problem(
                "invalid_response",
                f"The branch returned incomplete or inconsistent {metric} data.",
            )
        if (
            report.branch.id != branch.id
            or report.start_date != query.start_date
            or report.end_date != query.end_date
        ):
            return problem(
                "invalid_response",
                "The returned branch or period differs from the request.",
            )
        if isinstance(report, InventoryReport) and params and report.page != params["page"]:
            return problem("invalid_response", "The returned inventory page differs from the request.")
        return report
