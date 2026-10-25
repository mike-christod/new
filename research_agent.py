#!/usr/bin/env python3
"""Research agent: give it a topic, get back a cited Markdown report.

Claude plans the research, runs web searches, reads the most useful pages
(web search + web fetch run server-side on Anthropic's infrastructure), and
writes a structured report. Every claim backed by a source gets a numbered
citation, and the sources are listed at the end.

Usage:
    python research_agent.py "heat pump retrofits in commercial offices"
    python research_agent.py "chiller plant optimisation" --effort high --out reports/
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
MAX_CONTINUATIONS = 8  # cap on pause_turn resumes so a run can't loop forever

SYSTEM_PROMPT = """You are a meticulous research analyst. Given a topic, you research it on the web and write a report.

How to work:
- Break the topic into the key questions a decision-maker would ask, then search for each.
- Prefer primary and authoritative sources: standards bodies, government agencies, peer-reviewed papers, manufacturer technical documentation, reputable industry publications. Note when a source is a vendor with a commercial interest.
- Fetch and read the most promising pages rather than relying on search snippets alone.
- Capture concrete numbers (costs, savings percentages, efficiencies, dates) with their context and source.
- Where sources disagree, say so and explain why they might differ.
- Stop researching once further searches stop changing your conclusions.

Write the final report in Markdown with these sections:
# <Report title>
## Executive summary  (3-6 bullet points)
## Background
## Key findings  (subsections as needed)
## Open questions and limitations
## Recommendations / next steps

Ground every factual claim in what you found. Do not invent sources or figures."""


def build_tools(max_searches: int, max_fetches: int) -> list[dict]:
    return [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
        {
            "type": "web_fetch_20260209",
            "name": "web_fetch",
            "max_uses": max_fetches,
            "citations": {"enabled": True},
        },
    ]


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def run_research(
    client: anthropic.Anthropic,
    topic: str,
    effort: str,
    max_searches: int,
    max_fetches: int,
) -> list:
    """Run the research loop and return the final assistant content blocks."""
    messages: list[dict] = [
        {
            "role": "user",
            "content": f"Today's date is {date.today().isoformat()}.\n\nResearch topic: {topic}",
        }
    ]
    tools = build_tools(max_searches, max_fetches)
    all_blocks: list = []

    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            output_config={"effort": effort},
            # If a safety classifier declines, re-run on Anthropic's recommended
            # fallback model inside the same call instead of failing outright.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for event in stream:
                # Show progress: one line per search / page fetch.
                if event.type == "content_block_stop" and event.content_block.type == "server_tool_use":
                    block = event.content_block
                    inp = block.input if isinstance(block.input, dict) else {}
                    detail = inp.get("query") or inp.get("url") or ""
                    log(f"  -> {block.name}: {detail}")
            response = stream.get_final_message()

        all_blocks.extend(response.content)

        if response.stop_reason == "pause_turn":
            # Server-side tool loop hit its iteration limit; send the turn back
            # unchanged and the server resumes where it left off.
            log("  (continuing research ...)")
            messages.append({"role": "assistant", "content": response.content})
            continue
        if response.stop_reason == "refusal":
            raise RuntimeError("The request was declined by the model and its fallback.")
        if response.stop_reason == "max_tokens":
            log("  warning: hit max_tokens; the report may be truncated.")
        return all_blocks

    log("  warning: reached the continuation limit; the report may be incomplete.")
    return all_blocks


def render_report(blocks: list) -> str:
    """Join the text blocks into Markdown, turning citations into [n] markers."""
    sources: dict[str, tuple[int, str]] = {}  # url -> (number, title)
    parts: list[str] = []

    # Only the text after the last tool call is the report; earlier text is
    # Claude narrating its research.
    last_tool = max(
        (i for i, b in enumerate(blocks) if b.type.endswith("tool_result") or b.type == "server_tool_use"),
        default=-1,
    )
    for block in blocks[last_tool + 1 :]:
        if block.type != "text":
            continue
        markers = []
        for cite in getattr(block, "citations", None) or []:
            url = getattr(cite, "url", None)
            if not url:
                continue
            if url not in sources:
                sources[url] = (len(sources) + 1, getattr(cite, "title", None) or url)
            n = sources[url][0]
            if f"[{n}]" not in markers:
                markers.append(f"[{n}]")
        parts.append(block.text + "".join(markers))

    report = "".join(parts).strip()
    if sources:
        report += "\n\n## Sources\n\n"
        report += "\n".join(f"{n}. [{title}]({url})" for url, (n, title) in sources.items())
    return report + "\n"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "report"


def main() -> int:
    parser = argparse.ArgumentParser(description="Research a topic and write a cited Markdown report.")
    parser.add_argument("topic", help="The topic or question to research")
    parser.add_argument(
        "--effort",
        default="high",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="How deeply Claude reasons (higher = more thorough, slower, more tokens). Default: high",
    )
    parser.add_argument("--max-searches", type=int, default=15, help="Web search budget (default 15)")
    parser.add_argument("--max-fetches", type=int, default=10, help="Page fetch budget (default 10)")
    parser.add_argument("--out", default="reports", help="Output directory (default ./reports)")
    args = parser.parse_args()

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    log(f"Researching: {args.topic}")
    try:
        blocks = run_research(client, args.topic, args.effort, args.max_searches, args.max_fetches)
    except anthropic.AuthenticationError:
        log("Authentication failed - set ANTHROPIC_API_KEY.")
        return 1
    except anthropic.RateLimitError:
        log("Rate limited - wait a minute and try again.")
        return 1
    except anthropic.APIStatusError as e:
        log(f"API error ({e.status_code}): {e.message}")
        return 1
    except anthropic.APIConnectionError:
        log("Network error - check your connection.")
        return 1
    except RuntimeError as e:
        log(str(e))
        return 1

    report = render_report(blocks)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date.today().isoformat()}-{slugify(args.topic)}.md"
    path.write_text(report, encoding="utf-8")
    log(f"\nReport saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
