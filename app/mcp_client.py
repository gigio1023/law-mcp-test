"""Korean Law MCP stdio client.

This module owns the Model Context Protocol transport. It deliberately avoids
LLM or UI decisions; callers provide already-approved tool requests and receive
plain text results.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import AppConfig, PROJECT_ROOT
from app.models import McpToolRequest, McpToolResult, ToolCatalogEntry


class KoreanLawMcpClient:
    """Thin async client for the Korean Law MCP server.

    Background:
        ``korean-law-mcp`` is a Node MCP server. Running it over stdio preserves
        the MCP JSON-RPC contract and avoids parsing CLI text output manually.
        The app starts a fresh server process for catalog reads and tool calls,
        so the LLM always sees the live tool list advertised by the configured
        local MCP build or by the ``npx`` fallback.
    """

    def __init__(self, config: AppConfig, law_api_key: str) -> None:
        """Store runtime configuration and the optional 법제처 API key.

        Function:
            ``law_api_key`` is already resolved by ``AppConfig`` from
            ``MCP_API_KEY`` first, then compatibility aliases. This class maps
            that value into the environment variables understood by the Node MCP
            server before each subprocess is started.
        """

        self.config = config
        self.law_api_key = law_api_key

    async def list_tools(self) -> list[ToolCatalogEntry]:
        """Return the MCP-advertised tool catalog.

        Intent:
            The system prompt includes this catalog so the LLM can select tools
            from explicit descriptions and JSON schemas instead of relying on
            keyword heuristics in Python.

        Background:
            This method calls the MCP protocol's real ``list_tools()`` endpoint.
            The returned names and schemas are later converted into OpenAI
            ``tools`` without a custom wrapper, which is the critical path that
            keeps OpenAI tool calling aligned with the MCP server.
        """

        async with stdio_client(self._server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [self._catalog_entry(tool) for tool in result.tools]

    async def call_many(self, requests: list[McpToolRequest]) -> list[McpToolResult]:
        """Execute multiple approved MCP requests within one stdio session.

        Function:
            Tool calls from a single OpenAI assistant message are independent in
            this app. Running them concurrently keeps the status UI responsive
            without changing the semantics of the LLM-selected calls.
        """

        if not requests:
            return []

        async with stdio_client(self._server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def run_one(request: McpToolRequest) -> McpToolResult:
                    try:
                        result = await session.call_tool(request.tool_name, request.arguments)
                        return McpToolResult(
                            request=request,
                            text=self._result_text(result),
                            is_error=bool(getattr(result, "isError", False)),
                        )
                    except Exception as exc:
                        return McpToolResult(request=request, text=f"{type(exc).__name__}: {exc}", is_error=True)

                return await asyncio.gather(*(run_one(request) for request in requests))

    def _server_params(self) -> StdioServerParameters:
        """Build subprocess parameters for local build or ``npx`` fallback.

        Background:
            The upstream Korean Law MCP server reads the 법제처 credential from
            ``LAW_OC`` or ``KOREAN_LAW_API_KEY``. This app accepts the user's
            preferred ``MCP_API_KEY`` through Pydantic settings, then exports the
            resolved value as both upstream-compatible names for the child
            process.
        """

        node = shutil.which("node")
        if self.config.mcp_entry.exists() and node:
            command = node
            args = [str(self.config.mcp_entry)]
            cwd = str(self.config.mcp_repo_dir)
        else:
            npx = shutil.which("npx")
            if not npx:
                raise RuntimeError("Node.js/npx is required to run korean-law-mcp.")
            command = npx
            args = ["-y", "korean-law-mcp"]
            cwd = str(PROJECT_ROOT)

        env = os.environ.copy()
        if self.law_api_key:
            env["LAW_OC"] = self.law_api_key
            env["KOREAN_LAW_API_KEY"] = self.law_api_key
        env.setdefault("LAW_REFERER", "https://www.law.go.kr/")
        return StdioServerParameters(command=command, args=args, cwd=cwd, env=env)

    def _catalog_entry(self, tool: Any) -> ToolCatalogEntry:
        """Normalize an MCP SDK tool object into prompt-friendly data."""

        raw = tool.model_dump(mode="json") if hasattr(tool, "model_dump") else dict(tool)
        return ToolCatalogEntry(
            name=str(raw.get("name", "")),
            description=str(raw.get("description", "")),
            input_schema=dict(raw.get("inputSchema") or raw.get("input_schema") or {}),
        )

    def _result_text(self, result: Any) -> str:
        """Extract text content from an MCP ``CallToolResult`` object."""

        parts: list[str] = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            parts.append(str(text if text is not None else item))
        return "\n".join(parts).strip()
