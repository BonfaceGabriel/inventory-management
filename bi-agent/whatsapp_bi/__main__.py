import argparse
import asyncio
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from sys import stderr

import httpx
from openai import APIError
from dotenv import load_dotenv
from pydantic_ai.exceptions import ModelHTTPError, UserError
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from .agent import build_agent, run_question
from .branch_directory import BranchDirectory, BranchDiscoveryError
from .briefing import render_briefing_preview, render_requested_briefing, select_briefing
from .chatgpt import chatgpt_login, chatgpt_models, configured_model
from .client import RevenueClient
from .inbox import Inbox
from .models import NAIROBI, RevenueProblem, RevenueQuery


async def execute(args):
    load_dotenv()
    if args.command == "chatgpt-login":
        await chatgpt_login(args.port)
        return 0
    if args.command == "chatgpt-models":
        await chatgpt_models()
        return 0
    if args.command == "whatsapp-status":
        inbox_path = Path(os.getenv("WHATSAPP_INBOX_PATH", "whatsapp-inbox.sqlite3"))
        try:
            statuses = Inbox.recent_statuses(inbox_path)
        except (OSError, sqlite3.Error):
            print("WhatsApp inbox unavailable. Run this in the bot container and check WHATSAPP_INBOX_PATH.", file=stderr)
            return 1
        if not statuses:
            print("No messages have been recorded in the WhatsApp inbox.")
        for timestamp, state, failure_reason in statuses:
            received = datetime.fromtimestamp(timestamp, NAIROBI)
            detail = f" — {failure_reason}" if failure_reason else ""
            print(f"{received:%Y-%m-%d %H:%M:%S %Z}  {state}{detail}")
        return 0
    async with httpx.AsyncClient() as http:
        branches = await BranchDirectory.from_env().load(http)
        if args.command == "branches":
            for branch in branches:
                state = "credential set" if os.getenv(branch.token_env) else f"set {branch.token_env}"
                print(f"{branch.name} ({branch.id}) — {state}")
            return 0
        client = RevenueClient(branches, http)
        if args.command == "briefing-preview":
            if args.date > client.today:
                print("Choose a reporting date up to today in Nairobi.", file=stderr)
                return 2
            print(await render_briefing_preview(client, args.date))
            return 0
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
        selection = select_briefing(result.new_messages())
        print(await render_requested_briefing(client, selection) if selection is not None else result.output)
        return 0


def main():
    parser = argparse.ArgumentParser(description="Read-only live inventory BI")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("branches", help="List branches discovered from inventory")
    revenue = commands.add_parser(
        "revenue", help="Fetch verified API data without an LLM call"
    )
    revenue.add_argument("--branch", required=True)
    revenue.add_argument("--start", required=True)
    revenue.add_argument("--end", required=True)
    briefing = commands.add_parser("briefing-preview", help="Render a read-only end-of-day briefing locally")
    briefing.add_argument("--date", type=date.fromisoformat, required=True)
    ask = commands.add_parser("ask", help="Ask the Pydantic AI agent a question")
    ask.add_argument("question")
    ask.add_argument("--trace", action="store_true")
    login = commands.add_parser("chatgpt-login", help="Authorize use of your ChatGPT plan")
    login.add_argument("--port", type=int, default=1455, help="Loopback callback port")
    commands.add_parser("chatgpt-models", help="List models available through your ChatGPT plan")
    commands.add_parser("whatsapp-status", help="Show the last ten WhatsApp inbox statuses")
    args = parser.parse_args()
    try:
        status = asyncio.run(execute(args))
    except BranchDiscoveryError as error:
        parser.exit(2, f"{error}\n")
    except (TimeoutError, APIError, ModelHTTPError, UserError) as error:
        parser.exit(1, f"Model request or sign-in failed ({type(error).__name__}). Check your OpenAI usage or sign in again.\n")
    except (OSError, ValueError) as error:
        if args.command.startswith("chatgpt-") or os.getenv("BI_MODEL", "").startswith("openai-chatgpt:"):
            parser.exit(2, f"ChatGPT configuration failed ({type(error).__name__}). Check the model and private session, or run whatsapp-bi chatgpt-login.\n")
        parser.exit(
            2,
            f"Configuration error ({type(error).__name__}); check dates and environment.\n",
        )
    raise SystemExit(status)


if __name__ == "__main__":
    main()
