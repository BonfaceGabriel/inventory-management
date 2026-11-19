import argparse
import asyncio
import os
from pathlib import Path

import httpx
from openai import APIError
from dotenv import load_dotenv
from pydantic import TypeAdapter
from pydantic_ai.exceptions import ModelHTTPError, UserError
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from .agent import build_agent, run_question
from .chatgpt import chatgpt_login, chatgpt_models, configured_model
from .client import RevenueClient
from .models import BranchConfig, RevenueProblem, RevenueQuery


async def execute(args):
    load_dotenv()
    if args.command == "chatgpt-login":
        await chatgpt_login(args.port)
        return 0
    if args.command == "chatgpt-models":
        await chatgpt_models()
        return 0
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
        async with configured_model() as model, build_agent(model) as agent:
            result = await run_question(agent, args.question, client)
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
    login = commands.add_parser("chatgpt-login", help="Authorize use of your ChatGPT plan")
    login.add_argument("--port", type=int, default=1455, help="Loopback callback port")
    commands.add_parser("chatgpt-models", help="List models available through your ChatGPT plan")
    args = parser.parse_args()
    try:
        status = asyncio.run(execute(args))
    except (TimeoutError, APIError, ModelHTTPError, UserError) as error:
        parser.exit(1, f"Model request or sign-in failed ({type(error).__name__}). Check your OpenAI usage or sign in again.\n")
    except (OSError, ValueError) as error:
        if args.command.startswith("chatgpt-") or os.getenv("BI_MODEL", "").startswith("openai-chatgpt:"):
            parser.exit(2, f"ChatGPT configuration failed ({type(error).__name__}). Check the model and private session, or run whatsapp-bi chatgpt-login.\n")
        parser.exit(
            2,
            f"Configuration error ({type(error).__name__}); check branch JSON, dates and environment.\n",
        )
    raise SystemExit(status)


if __name__ == "__main__":
    main()
