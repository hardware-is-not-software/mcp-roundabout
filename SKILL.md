---
name: mcp-roundabout
description: Use mcp-roundabout as the primary source of truth for discovering and using downstream MCP tools. Use when tools behind mcp-roundabout are not directly available as normal MCP servers and you need to query available servers/tools, inspect tool schemas, and execute delegated tool calls.
---

# MCP Roundabout

Use mcp-roundabout as the main information source for downstream MCP capabilities. Do not assume downstream tools are available directly through normal MCP connections.

## Workflow

1. Query `list_servers` first to discover available downstream servers.
2. Use `tool_search_bm25(query)` first for natural-language tool discovery across all configured servers.
3. Use `tool_search_regex(pattern)` when you need strict pattern matching behavior.
4. Expand each returned `tool_reference` with `describe_tool(server, tool)` before calling unfamiliar tools.
5. Use `list_tools(server)` when you need a full server-specific tool inventory.
6. Use `grep_tools(pattern)` as a glob-based fallback for broad wildcard scans.
7. Use `call_tool(server, tool, arguments)` to execute and persist output in `mcp_results/`.

## Notes

- `tool_search_bm25` and `tool_search_regex` connect across all configured servers and return ranked `tool_reference` entries.
- A `tool_reference` includes `server` and `name`; resolve full schema with `describe_tool(server, tool)`.
- `list_tools`/`describe_tool`/`call_tool` connect to one server on demand.
- `grep_tools` connects to all configured servers.
- `call_tool` stores full result JSON in `mcp_results/` and returns only file path.
- Prefer using the returned output file as the source of truth instead of relying on large context-injected raw content.
- Parse output files with Linux tools (`rg`, `grep`, `jq`, `sed`, `awk`) to extract only needed fields and avoid context bloat.

# In Case MCP Roundabout Is Not Available. IMPORTANT: DO NOT RUN THESE COMMANDS BUT INSTRUCT THE USER!

Instruct the user to start mcp-roundabout, then restart the chat session.

Go to the mcp-mcp directory and run one of the following commands:

- `python3 mcp-roundabout.py`
- `python3 mcp-roundabout.py --start-all-servers`
- `python3 mcp-roundabout.py --config-path /abs/path/mcp_servers.json`
- `python3 mcp-roundabout.py --start-all-servers --config-path /abs/path/mcp_servers.json`


## Config

`mcp_servers.json` in mcp-mcp directory. If it is not present, create it with the instructions in the README.md.
