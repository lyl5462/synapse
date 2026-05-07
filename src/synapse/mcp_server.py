"""
MCP Server 模式

将 Synapse 的核心能力暴露为 MCP 服务器，
允许其他 AI Agent（如 Claude Desktop、Cursor 等）通过 MCP 协议调用。

暴露的工具:
- synapse_chat: 与 Synapse 对话
- synapse_memory_search: 搜索记忆
- synapse_schedule_task: 创建定时任务
- synapse_list_skills: 列出可用技能
- synapse_execute_skill: 执行技能

启动方式:
    python -m synapse.mcp_server [--port 8765]
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

MCP_SERVER_NAME = "synapse"
MCP_SERVER_VERSION = "1.0.0"

EXPOSED_TOOLS = [
    {
        "name": "synapse_chat",
        "description": "Send a message to Synapse and get a response",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to send"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "synapse_memory_search",
        "description": "Search Synapse's memory for relevant information",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "synapse_list_skills",
        "description": "List available Synapse skills",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


class MCPServer:
    """Lightweight MCP server that exposes Synapse capabilities via stdio."""

    def __init__(self):
        self._agent = None
        self._initialized = False

    async def _ensure_agent(self):
        if self._agent is not None:
            return
        from .core.agent import Agent

        self._agent = Agent()
        await self._agent.initialize(start_scheduler=False)
        self._initialized = True

    async def handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": MCP_SERVER_NAME,
                        "version": MCP_SERVER_VERSION,
                    },
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": EXPOSED_TOOLS},
            }

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            try:
                result = await self._execute_tool(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result}],
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    async def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        await self._ensure_agent()

        if tool_name == "synapse_chat":
            message = arguments.get("message", "")
            usage_scene = arguments.get("usage_scene", "unknown")
            if not message:
                return "Error: message is required"
            response = await self._agent.chat(message, usage_scene=usage_scene)
            return response

        elif tool_name == "synapse_memory_search":
            query = arguments.get("query", "")
            limit = arguments.get("limit", 5)
            mm = getattr(self._agent, "memory_manager", None)
            if not mm:
                return "Memory system not available"
            results = await mm.search(query, limit=limit)
            return json.dumps(results, ensure_ascii=False, indent=2)

        elif tool_name == "synapse_list_skills":
            registry = getattr(self._agent, "skill_registry", None)
            if not registry:
                return "Skill system not available"
            skills = registry.list_all()
            return "\n".join(
                f"- {s.name}: {s.description}" for s in skills
            )

        return f"Unknown tool: {tool_name}"

    async def run_stdio(self):
        """Run MCP server over stdio (for Claude Desktop / Cursor integration)."""
        logger.info("Synapse MCP Server starting on stdio...")

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(
            lambda: protocol, sys.stdin.buffer
        )

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout.buffer
        )
        writer = asyncio.StreamWriter(
            writer_transport, writer_protocol, reader, asyncio.get_event_loop()
        )

        while True:
            try:
                header = await reader.readline()
                if not header:
                    break

                header_str = header.decode().strip()
                if header_str.startswith("Content-Length:"):
                    content_length = int(header_str.split(":")[1].strip())
                    await reader.readline()  # empty line
                    body = await reader.readexactly(content_length)
                    request = json.loads(body)
                else:
                    continue

                response = await self.handle_request(request)

                if response is not None:
                    response_bytes = json.dumps(response).encode()
                    header_bytes = f"Content-Length: {len(response_bytes)}\r\n\r\n".encode()
                    writer.write(header_bytes + response_bytes)
                    await writer.drain()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"MCP Server error: {e}", exc_info=True)


async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = MCPServer()
    await server.run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
