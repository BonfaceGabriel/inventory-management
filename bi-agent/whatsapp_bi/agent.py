from datetime import timedelta

from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import UsageLimits

from .client import RevenueClient
from .models import RevenueProblem, RevenueQuery, RevenueSummary


def build_agent(model="openai:gpt-5-mini"):
    agent = Agent(
        model,
        deps_type=RevenueClient,
        defer_model_check=True,
        instructions=(
            "You are the inventory business's BI assistant. Use get_revenue for revenue figures. "
            "Revenue means receipts via Paybill, PDQ and Till; it is distinct from sales/fulfillment. "
            "Report the branch, exact dates, each gateway and total in KES. "
            "Use only figures returned by a successful tool result. A successful zero total is zero revenue. "
            "Unavailable, unauthorized, invalid or unknown-branch results are not zero revenue. "
            "Explain problems in plain language without exposing internal status codes or inventing figures. "
            "Ask which branch if none is specified. Never silently substitute a branch or period. "
            "Branches are separate databases. Cross-branch totals are not supported yet because shared payments require deduplication. "
            "Identify today's results as provisional when is_provisional is true. "
            "Answer concisely and directly. Do not offer unrequested next steps. "
            "The API reports receipts only. Explain the available revenue scope if asked for unsupported sales, charts or comparisons."
        ),
    )

    @agent.instructions
    def runtime_context(ctx: RunContext[RevenueClient]) -> str:
        today = ctx.deps.today
        yesterday = today - timedelta(days=1)
        return (
            f"Today in Africa/Nairobi is {today}. Available branches: "
            + ", ".join(branch.name for branch in ctx.deps.branches)
            + f". Date ranges are inclusive. A single date uses equal start/end. "
            f"Yesterday is {yesterday}; this week starts {today - timedelta(days=today.weekday())}; "
            f"this month starts {today.replace(day=1)}; this year starts {today.replace(month=1, day=1)}. "
            "This week/month/year ends today. Never query future dates. Maximum range: 366 days."
        )

    @agent.tool
    async def get_revenue(
        ctx: RunContext[RevenueClient], query: RevenueQuery
    ) -> RevenueSummary | RevenueProblem:
        """Get actual branch receipts for an inclusive period, with Paybill, PDQ and Till totals."""
        result = await ctx.deps.get_revenue(query)
        if isinstance(result, RevenueProblem):
            return result
        # Validate the full daily series in the client, but send the model only
        # the summary it needs. A year-long question needn't send 366 rows.
        return RevenueSummary.model_validate(result.model_dump(exclude={"daily"}))

    return agent


async def run_question(agent: Agent[RevenueClient, str], question: str, client: RevenueClient):
    return await agent.run(
        question,
        deps=client,
        usage_limits=UsageLimits(request_limit=6, tool_calls_limit=4),
    )
