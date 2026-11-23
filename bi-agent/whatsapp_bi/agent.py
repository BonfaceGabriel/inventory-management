import re
from datetime import date, timedelta

from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import UsageLimits

from .client import RevenueClient
from .growth import BranchGrowthReport, GrowthMetric, compare_branch_growth
from .models import (
    BranchName,
    ConversationContext,
    DailyRevenueBreakdown,
    MerchandiseReport,
    MonthlyRevenueBreakdown,
    ProductReport,
    PageNumber,
    ReconciliationSummary,
    RegistrationReport,
    RevenueComparison,
    RevenuePeriod,
    RevenueProblem,
    RevenueQuery,
    RevenueSummary,
    RevenueToolQuery,
    SalesSummary,
    SalesBreakdown,
    SalesSeries,
    SalesToolQuery,
    StockReport,
)

DAY_FOLLOW_UP = re.compile(
    r"(?:(?:what\s+(?:about|of)|how\s+about)\s+)?(?:the\s+)?([0-9]{1,2})(?:st|nd|rd|th)?[?.!]*",
    re.IGNORECASE,
)
ROLLING_DAYS = re.compile(
    r"\b(?:the\s+)?last\s+([0-9]{1,3})\s+days?\b(\s+including\s+today)?(?=\s*[?.!]*\s*$)",
    re.IGNORECASE,
)
RECONCILIATION_DATE_REQUIRED = (
    "Reconciliation is reported one day at a time. Please ask again with the branch and one date."
)
_RECONCILIATION = re.compile(r"\breconcil(?:iation|e|ed)\b", re.IGNORECASE)
_CALENDAR_PERIOD = re.compile(r"\b(?:this|last|previous|next)\s+(?:week|month|year)\b", re.IGNORECASE)
_COUNTED_PERIOD = re.compile(
    r"\b(?:last|past|next)\s+([0-9]{1,4}|one|two|three|four|five|six|seven)\s+"
    r"(days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)
_NAMED_DAY = r"(?:today|yesterday|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_ISO_DAY = r"\d{4}-\d{2}-\d{2}"
_ORDINAL = r"\d{1,2}(?:st|nd|rd|th)"
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATED_DAY = rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?)"
_SINGLE_DATE = re.compile(rf"\b(?:{_NAMED_DAY}|{_ISO_DAY}|{_ORDINAL}|{_DATED_DAY})\b", re.IGNORECASE)
_RANGE_DAY = rf"(?:{_ISO_DAY}|{_NAMED_DAY}|{_DATED_DAY}|\d{{1,2}}(?:st|nd|rd|th)?)"
_EXPLICIT_DATE_RANGE = re.compile(
    rf"\b({_RANGE_DAY})\s*(?:\b(?:to|through|until|and)\b|[–—])\s*({_RANGE_DAY})\b",
    re.IGNORECASE,
)


def requests_multiple_reporting_days(question: str) -> bool:
    if any(a.casefold() != b.casefold() for a, b in _EXPLICIT_DATE_RANGE.findall(question)):
        return True
    for count, unit in _COUNTED_PERIOD.findall(question):
        if count.casefold() != "one" and count.lstrip("0") != "1":
            return True
        if not unit.casefold().startswith("day"):
            return True
    return bool(_CALENDAR_PERIOD.search(question) and not _SINGLE_DATE.search(question))


def reconciliation_needs_a_date(question: str) -> bool:
    return bool(_RECONCILIATION.search(question) and requests_multiple_reporting_days(question))


def expand_rolling_dates(question: str, today: date) -> str:
    match = ROLLING_DAYS.search(question)
    if match is None or not 1 <= (days := int(match[1])) <= 366:
        return question
    end = today if match[2] else today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return f"{question[:match.start()]}{start.isoformat()} through {end.isoformat()}{question[match.end():]}"


async def _get_revenue_summary(
    client: RevenueClient, query: RevenueQuery
) -> RevenueSummary | RevenueProblem:
    result = await client.get_revenue(query)
    if isinstance(result, RevenueProblem):
        return result
    if isinstance(query, RevenueToolQuery):
        if query.breakdown == "monthly":
            return MonthlyRevenueBreakdown.from_report(result, client.today)
        if query.breakdown != "total" or query.include_daily_gateways:
            return DailyRevenueBreakdown.from_report(
                result, trend_requested=query.breakdown == "trend", include_gateways=query.include_daily_gateways
            )
    # The client verifies the full series. Ordinary totals only need the summary.
    return RevenueSummary.model_validate(result.model_dump(exclude={"daily"}))


def build_agent(model="openai:gpt-5-mini"):
    agent = Agent(
        model,
        deps_type=RevenueClient,
        defer_model_check=True,
        instructions=(
            "You are the inventory business's BI assistant. Use get_revenue for a single revenue period. "
            "Use breakdown=total for a revenue total over any date range, including a gateway breakdown for the whole range. "
            "Use breakdown=daily for revenue by day, and breakdown=trend when the user asks for a trend without a different granularity. "
            "Use breakdown=monthly for month-by-month or month-to-month revenue. Report each month's coverage and only use provided comparisons. "
            "Set include_daily_gateways=true when the user asks for both a daily and gateway breakdown. "
            "The number of days alone does not request a daily or trend view. "
            "If a daily breakdown lists fewer days than day_count, say it shows the most recent days of the requested period. "
            "If a seven-day trend is returned, use its percentage and dates directly. "
            "Use compare_revenue for two periods at one branch. Put the period being measured first "
            "and the reference period in baseline. Ask for clarification if either period is unclear. "
            "Report both exact periods, their totals, and the signed change returned by the tool. "
            "Revenue means receipts via Paybill, PDQ and Till; it is distinct from sales/fulfillment. "
            "Use get_sales for sales or total value fulfilled. It returns a single fulfilled total excluding merchandise. "
            "For sales by day use breakdown=daily, for a sales trend use trend, and for month-to-month sales use monthly. "
            "Use get_top_products for best sellers and product performance. Report units sold and KES value. "
            "Use get_registrations to count people registered or kits issued in a branch over a date range. "
            "Use the kit count as the registration count and show the margin calculation separately. "
            "Use get_merchandise for fulfilled merchandise sold over a date range and for current remaining merchandise. "
            "If asking only for current merchandise remaining, use today as both dates. "
            "Use get_stock for current product stock value and items that are low or out of stock. "
            "For historic stock questions, explain that only current stock is available. "
            "For stock, omit page to return the full alert list. Set a page only when the user names one. "
            "For merchandise, use page 1 unless the user asks for another page. "
            "Use get_branch_growth for the fastest-growing branch or to compare growth across branches. "
            "Call it only when the user names the metric (revenue or sales) and two comparison periods. "
            "The periods must have the same number of days and must not overlap. Never infer a baseline. "
            "Use get_reconciliation for the balance status, X, Y, and result in one branch on one reporting date. "
            "Ask for a single reporting date if the reconciliation request spans several days. "
            "Use the reconciliation figures and status as supplied by the tool. "
            "For a single period, report the branch, exact dates, each gateway and total in KES. "
            "Use only figures returned by a successful tool result. A successful zero total is zero revenue. "
            "Unavailable, unauthorized, invalid or unknown-branch results are not zero revenue. "
            "Explain problems in plain language without exposing internal status codes or inventing figures. "
            "Ask for the branch or dates if they are unclear. Never invent or substitute a branch or period. "
            "If tool validation rejects a date the user explicitly gave, ask for a correction. "
            "Branches are separate databases. Cross-branch totals are not supported yet because shared payments require deduplication. "
            "Identify today's results as provisional when is_provisional is true. "
            "Answer concisely and directly. Do not offer unrequested next steps. "
            "Explain the available scope if asked for charts."
        ),
    )

    @agent.instructions
    def runtime_context(ctx: RunContext[RevenueClient]) -> str:
        today = ctx.deps.today
        yesterday = today - timedelta(days=1)
        this_week_start = today - timedelta(days=today.weekday())
        return (
            f"Today in Africa/Nairobi is {today}. Available branches: "
            + ", ".join(branch.name for branch in ctx.deps.branches)
            + f". Date ranges are inclusive. A single date uses equal start/end. "
            f"Yesterday is {yesterday}; this week starts {this_week_start}; "
            f"this month starts {today.replace(day=1)}; this year starts {today.replace(month=1, day=1)}. "
            "This week/month/year ends today. "
            f"Last week means the previous Monday through Sunday, "
            f"{this_week_start - timedelta(days=7)} through {this_week_start - timedelta(days=1)}. "
            f"Last 7 days means the last seven completed reporting days, "
            f"{today - timedelta(days=7)} through {yesterday}. "
            f"Last 7 days including today means {today - timedelta(days=6)} through {today}. "
            "For any last N days with no specified endpoint, end yesterday unless the user includes today. "
            "Never query future dates. Maximum range: 366 days."
        )

    @agent.tool
    async def get_revenue(
        ctx: RunContext[RevenueClient], query: RevenueToolQuery
    ) -> RevenueSummary | RevenueProblem:
        """Get branch receipts for a period as totals, daily amounts, a seven-day trend, or monthly totals."""
        return await _get_revenue_summary(ctx.deps, query)

    @agent.tool
    async def get_sales(ctx: RunContext[RevenueClient], query: SalesToolQuery) -> SalesSummary | RevenueProblem:
        """Get completed non-merchandise sales as a total, daily amounts, trend, or monthly amounts."""
        result = await ctx.deps.get_sales(query, daily=query.breakdown != "total")
        if isinstance(result, SalesSeries):
            return SalesBreakdown.from_report(result, query.breakdown, ctx.deps.today)
        return result

    @agent.tool
    async def get_top_products(ctx: RunContext[RevenueClient], query: RevenueQuery) -> ProductReport | RevenueProblem:
        """Get up to ten products ranked by completed units sold, with their value in KES."""
        return await ctx.deps.get_products(query)

    @agent.tool
    async def get_merchandise(
        ctx: RunContext[RevenueClient], query: RevenueQuery, page: PageNumber = 1,
    ) -> MerchandiseReport | RevenueProblem:
        """Get fulfilled merchandise sales for the dates and current stock at catalog price, by item."""
        return await ctx.deps.get_merchandise(query, page)

    @agent.tool
    async def get_stock(
        ctx: RunContext[RevenueClient], branch: BranchName, page: PageNumber | None = None,
    ) -> StockReport | RevenueProblem:
        """Get current stock value at cost and all low or out-of-stock products, or one requested page."""
        if page is None:
            return await ctx.deps.get_full_stock(branch)
        return await ctx.deps.get_stock(branch, page)

    @agent.tool
    async def get_branch_growth(
        ctx: RunContext[RevenueClient], metric: GrowthMetric, period: RevenuePeriod, baseline: RevenuePeriod,
    ) -> BranchGrowthReport | RevenueProblem:
        """Compare percentage growth for each configured branch using the specified metric and periods."""
        return await compare_branch_growth(ctx.deps, metric, period, baseline)

    @agent.tool
    async def get_registrations(
        ctx: RunContext[RevenueClient], query: RevenueQuery
    ) -> RegistrationReport | RevenueProblem:
        """Get registration kits issued, their transaction count, and the registration margin."""
        return await ctx.deps.get_registrations(query)

    @agent.tool
    async def get_reconciliation(
        ctx: RunContext[RevenueClient], branch: BranchName, report_date: date
    ) -> ReconciliationSummary | RevenueProblem:
        """Read a branch's reconciliation status, X, Y, and result for one Nairobi reporting date."""
        if isinstance(ctx.prompt, str) and requests_multiple_reporting_days(ctx.prompt):
            return RevenueProblem(
                branch=branch,
                status="reconciliation_date_required",
                message=RECONCILIATION_DATE_REQUIRED,
            )
        return await ctx.deps.get_reconciliation(
            RevenueQuery(branch=branch, start_date=report_date, end_date=report_date)
        )

    @agent.tool
    async def compare_revenue(
        ctx: RunContext[RevenueClient],
        branch: BranchName,
        period: RevenuePeriod,
        baseline: RevenuePeriod,
    ) -> RevenueComparison | RevenueProblem:
        """Compare receipts at one branch. Change is the period total minus the baseline total."""
        period_result = await _get_revenue_summary(
            ctx.deps, RevenueQuery(branch=branch, **period.model_dump())
        )
        if isinstance(period_result, RevenueProblem):
            return period_result
        baseline_result = await _get_revenue_summary(
            ctx.deps, RevenueQuery(branch=branch, **baseline.model_dump())
        )
        if isinstance(baseline_result, RevenueProblem):
            return baseline_result
        return RevenueComparison(period=period_result, baseline=baseline_result)

    return agent


async def run_question(
    agent: Agent[RevenueClient, str],
    question: str,
    client: RevenueClient,
    *,
    context: ConversationContext | None = None,
):
    instructions = None
    if context is not None:
        instructions = f"The previous verified answer in this chat was for branch ID {context.branch_id}. "
        instructions += f"Its metric was {context.metric}. "
        if context.period is not None:
            instructions += (
                f"Its date range was {context.period.start_date} through {context.period.end_date}. "
            )
        month = context.reference_month
        day_follow_up = DAY_FOLLOW_UP.fullmatch(question.strip())
        if month is not None:
            instructions += (
                f"For a follow-up that only gives a day of the month, use {month:%B %Y} "
                "and treat it as a single-day question. If the day is invalid, ask for a full date. "
            )
            if day_follow_up:
                try:
                    day = month.replace(day=int(day_follow_up[1]))
                except ValueError:
                    pass  # Let the agent ask for a valid date.
                else:
                    question = f"Show {context.metric} for {context.branch_id} on {day.isoformat()}."
        else:
            instructions += "If a follow-up gives only a day of the month, ask for the full date. "
        instructions += (
            "Only reuse these details to resolve an explicit or clear follow-up. "
            "If the follow-up only changes the breakdown, reuse the previous branch and date range when available. "
            "Use any branch or dates the current question specifies. "
            "Use the metric the current question specifies, or reuse the previous metric for a clear follow-up. "
            "If the user refers to a previous period and none is given here, ask which period. "
            "Always use a tool for a new BI answer."
        )
    return await agent.run(
        expand_rolling_dates(question, client.today),
        deps=client,
        instructions=instructions,
        usage_limits=UsageLimits(request_limit=6, tool_calls_limit=4),
    )
