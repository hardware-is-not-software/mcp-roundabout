#!/usr/bin/env python3
"""MCP Roundabout server with direct downstream MCP connections."""

from __future__ import annotations

import json
import os
import fnmatch
import importlib
import inspect
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

MCP_SERVER_NAME = "mcp-roundabout"
MCP_SERVER_VERSION = "0.1.0"
MCP_HOST = os.environ.get("MCP_META_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("MCP_META_PORT", "5052"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "mcp_results")

mcp = FastMCP(
    MCP_SERVER_NAME,
    host=MCP_HOST,
    port=MCP_PORT,
)


def _find_config_path(explicit_path: str | None = None) -> str | None:
    candidates: list[str] = []
    if explicit_path:
        candidates.append(explicit_path)
    env_path = os.environ.get("MCP_CONFIG_PATH")
    if env_path:
        candidates.append(env_path)
    candidates.extend(
        [
            os.path.join(os.getcwd(), "mcp_servers.json"),
            os.path.expanduser("~/.mcp_servers.json"),
            os.path.expanduser("~/.config/mcp/mcp_servers.json"),
        ]
    )
    for candidate in candidates:
        expanded = os.path.abspath(os.path.expanduser(candidate))
        if os.path.exists(expanded):
            return expanded
    return None


def _load_config(path: str | None = None) -> dict[str, Any]:
    resolved = _find_config_path(path)
    if not resolved:
        raise FileNotFoundError(
            "No mcp_servers.json found. Provide config_path or set MCP_CONFIG_PATH."
        )
    with open(resolved, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers"), dict):
        raise ValueError('Config must contain object: {"mcpServers": {...}}')
    data["_resolved_config_path"] = resolved
    return data


def _import_required(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Failed to import MCP client SDK modules. "
            "Install/upgrade the Python MCP package."
        ) from exc


def _resolve_client_symbols() -> dict[str, Any]:
    root = _import_required("mcp")
    stdio_mod = _import_required("mcp.client.stdio")

    streamable_mod = None
    for module_name in ("mcp.client.streamable_http", "mcp.client.streamableHttp"):
        try:
            streamable_mod = importlib.import_module(module_name)
            break
        except Exception:
            continue
    if streamable_mod is None:
        raise RuntimeError(
            "Could not import streamable HTTP MCP client transport "
            "(mcp.client.streamable_http)."
        )

    session_cls = getattr(root, "ClientSession", None)
    stdio_params_cls = getattr(root, "StdioServerParameters", None)
    stdio_client_fn = getattr(stdio_mod, "stdio_client", None)
    streamable_fn = getattr(streamable_mod, "streamablehttp_client", None) or getattr(
        streamable_mod, "streamable_http_client", None
    )
    if not all([session_cls, stdio_params_cls, stdio_client_fn, streamable_fn]):
        raise RuntimeError(
            "Your installed MCP Python package does not expose expected client APIs "
            "(ClientSession, StdioServerParameters, stdio_client, streamable_http client)."
        )
    return {
        "ClientSession": session_cls,
        "StdioServerParameters": stdio_params_cls,
        "stdio_client": stdio_client_fn,
        "streamable_http_client": streamable_fn,
    }


MCP_CLIENT = _resolve_client_symbols()


def _call_with_supported_kwargs(func: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args, **kwargs)

    params = signature.parameters
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if accepts_var_kw:
        return func(*args, **kwargs)
    filtered = {k: v for k, v in kwargs.items() if k in params}
    return func(*args, **filtered)


def _normalize_server_config(name: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f'Server "{name}" config must be an object')
    has_command = "command" in raw
    has_url = "url" in raw
    if not has_command and not has_url:
        raise ValueError(f'Server "{name}" must have "command" or "url"')
    if has_command and has_url:
        raise ValueError(f'Server "{name}" cannot have both "command" and "url"')
    return raw


def _matches_any(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()
    for pattern in patterns:
        if isinstance(pattern, str) and fnmatch.fnmatchcase(lowered, pattern.lower()):
            return True
    return False


def _is_tool_allowed(tool_name: str, server_cfg: dict[str, Any]) -> bool:
    disabled = server_cfg.get("disabledTools") or []
    allowed = server_cfg.get("allowedTools") or []
    if isinstance(disabled, list) and _matches_any(tool_name, disabled):
        return False
    if isinstance(allowed, list) and allowed:
        return _matches_any(tool_name, allowed)
    return True


def _tool_to_dict(tool: Any, include_description: bool = True) -> dict[str, Any]:
    name = getattr(tool, "name", None) or ""
    description = getattr(tool, "description", None)
    input_schema = getattr(tool, "inputSchema", None)
    if input_schema is None:
        input_schema = getattr(tool, "input_schema", None)

    item = {
        "name": name,
        "inputSchema": _to_jsonable(input_schema) if input_schema is not None else {},
    }
    if include_description:
        item["description"] = description
    return item


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())  # type: ignore[attr-defined]
    if hasattr(value, "__dict__"):
        return _to_jsonable(vars(value))
    return str(value)


def _store_call_result(
    server: str,
    tool: str,
    arguments: dict[str, Any],
    result: Any,
    config_path: str,
) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{timestamp}_{server}_{tool}_{uuid4().hex[:8]}.json"
    filename = filename.replace("/", "_").replace("\\", "_")
    file_path = os.path.join(RESULTS_DIR, filename)

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "server": server,
        "tool": tool,
        "arguments": _to_jsonable(arguments),
        "result": _to_jsonable(result),
        "config_path": config_path,
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)
        f.write("\n")
    return file_path


@asynccontextmanager
async def _open_client(server_name: str, server_cfg: dict[str, Any]):
    session_cls = MCP_CLIENT["ClientSession"]
    stdio_params_cls = MCP_CLIENT["StdioServerParameters"]
    stdio_client = MCP_CLIENT["stdio_client"]
    streamable_http_client = MCP_CLIENT["streamable_http_client"]

    if "url" in server_cfg:
        transport_cm = _call_with_supported_kwargs(
            streamable_http_client,
            server_cfg["url"],
            headers=server_cfg.get("headers"),
            timeout=server_cfg.get("timeout"),
        )
    else:
        kwargs = {
            "command": server_cfg["command"],
            "args": server_cfg.get("args", []),
            "env": server_cfg.get("env"),
            "cwd": server_cfg.get("cwd"),
        }
        stdio_params = _call_with_supported_kwargs(stdio_params_cls, **kwargs)
        transport_cm = stdio_client(stdio_params)

    async with transport_cm as transport:
        if isinstance(transport, tuple):
            read_stream, write_stream = transport[0], transport[1]
        else:
            read_stream, write_stream = transport

        async with session_cls(read_stream, write_stream) as session:
            await session.initialize()
            yield session


def _get_server_entry(config: dict[str, Any], server_name: str) -> dict[str, Any]:
    raw = config["mcpServers"].get(server_name)
    if raw is None:
        available = sorted(config["mcpServers"].keys())
        raise ValueError(
            f'Server "{server_name}" not found. Available servers: {", ".join(available)}'
        )
    return _normalize_server_config(server_name, raw)


@mcp.tool()
def list_servers(config_path: str | None = None) -> dict[str, Any]:
    """List configured downstream MCP servers from mcp_servers.json."""
    config = _load_config(config_path)
    servers = config["mcpServers"]
    out: list[dict[str, Any]] = []
    for name, raw in servers.items():
        if not isinstance(raw, dict):
            continue
        info = {"name": name}
        server_cfg = _normalize_server_config(name, raw)
        if "url" in server_cfg:
            info["transport"] = "http"
            info["url"] = server_cfg.get("url")
        elif "command" in server_cfg:
            info["transport"] = "stdio"
            info["command"] = server_cfg.get("command")
            info["args"] = server_cfg.get("args", [])
        else:
            info["transport"] = "unknown"
        out.append(info)

    out.sort(key=lambda item: str(item["name"]).lower())
    return {
        "config_path": config["_resolved_config_path"],
        "servers": out,
        "count": len(out),
    }


@mcp.tool()
async def list_tools(
    server: str,
    with_descriptions: bool = True,
    config_path: str | None = None,
) -> dict[str, Any]:
    """List tools on a downstream server."""
    if not server or not server.strip():
        raise ValueError("server is required")
    config = _load_config(config_path)
    name = server.strip()
    server_cfg = _get_server_entry(config, name)

    async with _open_client(name, server_cfg) as session:
        response = await session.list_tools()
    tools = getattr(response, "tools", response)
    filtered = [
        _tool_to_dict(t, include_description=with_descriptions)
        for t in tools
        if _is_tool_allowed(getattr(t, "name", ""), server_cfg)
    ]

    return {
        "server": name,
        "config_path": config["_resolved_config_path"],
        "tools": filtered,
        "count": len(filtered),
    }


@mcp.tool()
async def describe_tool(
    server: str,
    tool: str,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Show a downstream tool schema."""
    if not server or not server.strip():
        raise ValueError("server is required")
    if not tool or not tool.strip():
        raise ValueError("tool is required")
    config = _load_config(config_path)
    server_name = server.strip()
    tool_name = tool.strip()
    server_cfg = _get_server_entry(config, server_name)
    async with _open_client(server_name, server_cfg) as session:
        response = await session.list_tools()

    tools = getattr(response, "tools", response)
    target = None
    for item in tools:
        if getattr(item, "name", None) == tool_name:
            target = item
            break
    if target is None:
        available = sorted(getattr(t, "name", "") for t in tools)
        raise ValueError(
            f'Tool "{tool_name}" not found on server "{server_name}". '
            f"Available: {', '.join(available)}"
        )
    if not _is_tool_allowed(tool_name, server_cfg):
        raise ValueError(f'Tool "{tool_name}" is blocked by server filtering config')

    return {
        "server": server_name,
        "tool": tool_name,
        "config_path": config["_resolved_config_path"],
        "schema": _tool_to_dict(target, include_description=True),
    }


@mcp.tool()
async def grep_tools(
    pattern: str,
    with_descriptions: bool = True,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Search tools across downstream servers by glob pattern."""
    if not pattern or not pattern.strip():
        raise ValueError("pattern is required")
    config = _load_config(config_path)
    pat = pattern.strip().lower()
    matches: list[dict[str, Any]] = []

    for server_name in sorted(config["mcpServers"].keys(), key=str.lower):
        server_cfg = _normalize_server_config(server_name, config["mcpServers"][server_name])
        async with _open_client(server_name, server_cfg) as session:
            response = await session.list_tools()
        tools = getattr(response, "tools", response)
        for item in tools:
            tool_name = getattr(item, "name", "")
            if not _is_tool_allowed(tool_name, server_cfg):
                continue
            if fnmatch.fnmatchcase(tool_name.lower(), pat):
                matches.append(
                    {
                        "server": server_name,
                        "tool": _tool_to_dict(item, include_description=with_descriptions),
                    }
                )

    return {
        "pattern": pattern.strip(),
        "config_path": config["_resolved_config_path"],
        "matches": matches,
        "count": len(matches),
    }


@mcp.tool()
async def call_tool(
    server: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Call any downstream MCP tool and return only a link/path to stored output."""
    if not server or not server.strip():
        raise ValueError("server is required")
    if not tool or not tool.strip():
        raise ValueError("tool is required")

    config = _load_config(config_path)
    server_name = server.strip()
    tool_name = tool.strip()
    server_cfg = _get_server_entry(config, server_name)
    payload = arguments or {}
    if not isinstance(payload, dict):
        raise ValueError("arguments must be an object")
    if not _is_tool_allowed(tool_name, server_cfg):
        raise ValueError(f'Tool "{tool_name}" is blocked by server filtering config')

    async with _open_client(server_name, server_cfg) as session:
        result = await session.call_tool(tool_name, arguments=payload)
    result_path = _store_call_result(
        server=server_name,
        tool=tool_name,
        arguments=payload,
        result=result,
        config_path=config["_resolved_config_path"],
    )

    return {
        "file": result_path,
    }


if __name__ == "__main__":
    print(f"Meta MCP server: http://{MCP_HOST}:{MCP_PORT}/mcp")
    print(f"Server name:     {MCP_SERVER_NAME}")
    mcp.run(transport="streamable-http")
