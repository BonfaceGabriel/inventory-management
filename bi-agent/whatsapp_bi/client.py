import os
from collections.abc import Callable
from datetime import date, datetime

import httpx
from pydantic import ValidationError

from .models import (
    NAIROBI,
    BranchConfig,
    RevenueProblem,
    RevenueQuery,
    RevenueReport,
    normalize_branch,
)


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
            return problem("invalid_request", "Future revenue dates cannot be queried.")
        token = self._token_lookup(branch.token_env)
        if not token:
            return problem(
                "authentication_failed",
                "The BI service credential is not configured for this branch.",
            )

        url = str(branch.base_url).rstrip("/") + "/agent/revenue/"
        try:
            response = await self.http.get(
                url,
                params={
                    "start_date": query.start_date.isoformat(),
                    "end_date": query.end_date.isoformat(),
                },
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
                "The branch API could not be reached; revenue is unavailable.",
            )

        if response.status_code in {401, 403}:
            return problem(
                "authentication_failed",
                "The branch API rejected the BI service credential.",
            )
        if response.status_code == 404:
            return problem(
                "not_deployed",
                "The read-only revenue endpoint is not deployed at this branch.",
            )
        if response.status_code == 400:
            return problem(
                "invalid_request", "The branch API rejected the requested date range."
            )
        if response.status_code != 200:
            return problem(
                "backend_unavailable",
                "The branch API did not return a successful revenue response.",
            )

        try:
            report = RevenueReport.model_validate_json(response.content)
        except (ValidationError, ValueError):
            return problem(
                "invalid_response",
                "The branch returned incomplete or inconsistent revenue data.",
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
        return report
