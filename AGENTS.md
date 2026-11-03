# Resolute — agent instructions
Project: multi-agent support resolution platform. Full plan: plan.md (read §0 and only your assigned task).
Commands: make install | make up | make test | make lint | make eval-smoke | make demo
Layout: src/agentcore (spine), src/resolute/{retrieval,mcp_servers,graph,hitl,api}, evals/, apps/web
Rules:
- All LLM calls via agentcore/llm.py; all tools via MCP servers; all nodes wrapped by @guarded.
- Pydantic structured outputs only. Async I/O. Type hints. ruff + mypy clean.
- OFFLINE=1 must keep tests passing with no keys. Missing fixture = error.
- Never hardcode model names or secrets. Never add a local LLM (8 GB machine).
- Do not read: evals/data/**, tests/fixtures/**, apps/web/node_modules/**, *.jsonl
- Finish = tests pass → tick task in plan.md → one line in PROGRESS.md → commit "<type>(Tx.y): summary".
