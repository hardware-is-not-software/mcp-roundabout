---
name: mcp-roundabout
description: Use mcp-roundabout as the primary source of truth for discovering and using downstream MCP tools. Use when tools behind mcp-roundabout are not directly available as normal MCP servers and you need to query available servers/tools, inspect tool schemas, and execute delegated tool calls.
---

# MCP Roundabout

Use mcp-roundabout as the main information source for downstream MCP capabilities. Do not assume downstream tools are available directly through normal MCP connections.

## Workflow

1. Query `list_servers` first to discover available downstream servers.
2. Query `list_tools(server)` to see tools exposed by each downstream server.
3. Query `describe_tool(server, tool)` before calling unfamiliar tools to confirm schema.
4. Use `grep_tools(pattern)` to find tools across all configured servers.
5. Use `call_tool(server, tool, arguments)` to execute and persist output in `mcp_results/`.

## Notes

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
