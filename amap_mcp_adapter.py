import asyncio
import json
import os
import shlex
from typing import Any

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


DEFAULT_AMAP_MCP_COMMAND = "npx -y @amap/amap-maps-mcp-server"


class AMapMCPAdapter:
    def __init__(
        self,
        mode: str = "mcp",
        mcp_command: str = DEFAULT_AMAP_MCP_COMMAND,
        mcp_tool_name: str = "maps_weather",
    ):
        self.mode = mode
        self.mcp_command = mcp_command
        self.mcp_tool_name = mcp_tool_name

    def _build_server_params(self):
        if ClientSession is None or StdioServerParameters is None or stdio_client is None:
            raise RuntimeError("缺少 mcp 依赖，请先安装：python -m pip install mcp")
        if not self.mcp_command.strip():
            raise RuntimeError("MCP 启动命令为空")
        cmd_parts = shlex.split(self.mcp_command, posix=False)
        if not cmd_parts:
            raise RuntimeError("MCP 启动命令为空")
        return StdioServerParameters(
            command=cmd_parts[0],
            args=cmd_parts[1:],
            env=os.environ.copy(),
        )

    async def _list_tools_from_mcp(self) -> list[dict[str, Any]]:
        server_params = self._build_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
        tools = []
        for tool in getattr(listed, "tools", []) or []:
            tools.append(
                {
                    "name": getattr(tool, "name", ""),
                    "description": getattr(tool, "description", ""),
                    "inputSchema": getattr(tool, "inputSchema", {}),
                }
            )
        return tools

    async def _get_weather_from_mcp(self, city: str) -> dict[str, Any]:
        server_params = self._build_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(self.mcp_tool_name, {"city": city})

        texts: list[str] = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text is not None:
                texts.append(text)

        merged_text = "\n".join(texts).strip()
        if merged_text:
            try:
                parsed = json.loads(merged_text)
                if isinstance(parsed, dict):
                    parsed["source"] = "amap_mcp"
                    return parsed
                return {"raw": parsed, "source": "amap_mcp"}
            except Exception:
                return {"text": merged_text, "source": "amap_mcp"}
        return {"content": str(getattr(result, "content", "")), "source": "amap_mcp"}

    def get_weather(self, city: str) -> dict[str, Any]:
        if self.mode == "mock":
            return {
                "city": city,
                "weather": "晴",
                "temperature": "24",
                "winddirection": "东南",
                "windpower": "3",
                "source": "mock_amap_mcp",
            }
        return asyncio.run(self._get_weather_from_mcp(city))

    def list_tools(self) -> list[dict[str, Any]]:
        return asyncio.run(self._list_tools_from_mcp())
