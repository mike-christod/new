# Research Agent

A command-line agent that researches a topic on the web and writes a cited Markdown report.

Claude breaks the topic into key questions, runs web searches, reads the most useful pages, and writes a structured report: executive summary, background, key findings, open questions, and recommendations. Claims are marked with numbered citations, and the sources are listed at the end.

Search and page fetching run on Anthropic's servers, so the only dependency is the `anthropic` Python SDK.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...                 # Windows: set ANTHROPIC_API_KEY=...
```

Web search must be enabled for your organisation in the Claude Console (Settings → Privacy / web search).

## Usage

```bash
python research_agent.py "heat pump retrofits for commercial office buildings"
python research_agent.py "chiller plant optimisation strategies and typical savings" --effort xhigh
python research_agent.py "NABERS energy rating changes 2026" --max-searches 25 --out my_reports
```

Progress (each search query and page fetch) prints to the terminal. The report is saved to `reports/<date>-<topic>.md`.

| Option | Default | Meaning |
|---|---|---|
| `--effort` | `high` | Reasoning depth: `low`, `medium`, `high`, `xhigh`, `max`. Higher is more thorough, slower and costs more. |
| `--max-searches` | 15 | Maximum number of web searches |
| `--max-fetches` | 10 | Maximum number of full pages read |
| `--out` | `reports` | Output folder |

## Cost

A typical run at `high` effort costs well under a dollar in tokens, plus $10 per 1,000 web searches. Use `--effort medium` and a smaller `--max-searches` for quick scans.

## Customising

- **Report structure and research style:** edit `SYSTEM_PROMPT` in `research_agent.py`. For example, add "always include typical energy savings (%) and payback periods" for energy-efficiency topics.
- **Trusted sources only:** add `"allowed_domains": ["energy.gov", "ashrae.org", ...]` to the `web_search` tool in `build_tools()`.
