import argparse
import asyncio
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.usage import UsageLimits

from .agent import build_agent
from .client import RevenueClient
from .models import BranchConfig, RevenueProblem, RevenueQuery


async def execute(args):
    load_dotenv()
    path = Path(args.config or os.getenv("BI_BRANCH_CONFIG", "branches.json"))
    branches = TypeAdapter(list[BranchConfig]).validate_json(path.read_text())
    async with httpx.AsyncClient() as http:
        client = RevenueClient(branches, http)
        if args.command == "revenue":
            result = await client.get_revenue(
                RevenueQuery(
                    branch=args.branch, start_date=args.start, end_date=args.end
                )
            )
            print(result.model_dump_json(indent=2))
            return 1 if isinstance(result, RevenueProblem) else 0
        agent = build_agent(os.getenv("BI_MODEL", "openai:gpt-5-mini"))
        result = await agent.run(
            args.question,
            deps=client,
            usage_limits=UsageLimits(request_limit=6, tool_calls_limit=4),
        )
        if args.trace:
            for message in result.all_messages():
                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        print("TOOL REQUEST:", part.tool_name, part.args)
                    elif isinstance(part, ToolReturnPart):
                        print("TOOL RESULT:", part.content)
        print(result.output)
        return 0


def main():
    parser = argparse.ArgumentParser(description="Read-only live inventory BI")
    parser.add_argument("--config", help="Branch configuration JSON path")
    commands = parser.add_subparsers(dest="command", required=True)
    revenue = commands.add_parser(
        "revenue", help="Fetch verified API data without an LLM call"
    )
    revenue.add_argument("--branch", required=True)
    revenue.add_argument("--start", required=True)
    revenue.add_argument("--end", required=True)
    ask = commands.add_parser("ask", help="Ask the Pydantic AI agent a question")
    ask.add_argument("question")
    ask.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    try:
        status = asyncio.run(execute(args))
    except (OSError, ValueError) as error:
        parser.exit(
            2,
            f"Configuration error ({type(error).__name__}); check branch JSON, dates and environment.\n",
        )
    raise SystemExit(status)


if __name__ == "__main__":
    main()
