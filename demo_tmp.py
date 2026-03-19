import argparse
import asyncio
import json
import os
import shlex
from typing import Any, Dict, List

from openai import OpenAI

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


TOOL_DEFS = [
    {
        "type": "function",
        "name": "get_amap_weather",
        "description": "根据城市名称查询天气",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"}
            },
            "required": ["city"]
        }
    }
]
DEFAULT_AMAP_MCP_COMMAND = "npx -y @amap/amap-maps-mcp-server"


class AMapMCPAdapter:
    def __init__(self, mode: str = "mcp", mcp_command: str = DEFAULT_AMAP_MCP_COMMAND, mcp_tool_name: str = "maps_weather"):
        self.mode = mode
        self.mcp_command = mcp_command
        self.mcp_tool_name = mcp_tool_name

    def _build_server_params(self):
        if ClientSession is None or StdioServerParameters is None or stdio_client is None:
            raise RuntimeError("缺少 mcp 依赖，请先安装：pip install mcp")
        if not self.mcp_command.strip():
            raise RuntimeError("MCP 启动命令为空")
        cmd_parts = shlex.split(self.mcp_command, posix=False) # 这里为npx -y @amap/amap-maps-mcp-server
        if not cmd_parts:
            raise RuntimeError("MCP 启动命令为空")
        return StdioServerParameters(
            command=cmd_parts[0],
            args=cmd_parts[1:],
            env=os.environ.copy(),
        )

    # 向MCP查询工具列表
    async def _list_tools_from_mcp(self) -> List[Dict[str, Any]]:
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

    async def _get_weather_from_mcp(self, city: str) -> Dict[str, Any]:
        server_params = self._build_server_params()

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(self.mcp_tool_name, {"city": city})

        texts: List[str] = []
        print('res:', result)
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

    def get_weather(self, city: str) -> Dict[str, Any]:
        if self.mode == "mock":
            return {
                "city": city,
                "weather": "晴",
                "temperature": "24",
                "winddirection": "东南",
                "windpower": "3",
                "source": "mock_amap_mcp"
            }
        return asyncio.run(self._get_weather_from_mcp(city))

    def list_tools(self) -> List[Dict[str, Any]]:
        return asyncio.run(self._list_tools_from_mcp())


def build_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ.get("DASHSCOPE_API_KEY", "sk-93cc25579e244edba7e9d14306c6cf8d"),
        base_url=os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )


def run_once(question: str, model: str, adapter: AMapMCPAdapter, enable_thinking: bool) -> str:
    client = build_client()
    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": question},
    ]

    extra_params: Dict[str, Any] = {}
    if enable_thinking:
        extra_params["extra_body"] = {"enable_thinking": True}

    first = client.responses.create(
        model=model,
        instructions="你是一个天气助手。涉及天气时优先调用工具。",
        input=messages,
        tools=TOOL_DEFS,
        tool_choice="auto",
        stream=False,
        **extra_params,
    )
    tool_calls = [
        item for item in (getattr(first, "output", None) or [])
        if getattr(item, "type", None) == "function_call"
    ]

    if not tool_calls:
        return getattr(first, "output_text", "") or ""

    for tool_call in tool_calls:
        if tool_call.name != "get_amap_weather":
            tool_output = {"error": f"unknown tool: {tool_call.name}"}
        else:
            args = json.loads(tool_call.arguments or "{}")
            city = args.get("city", "")
            tool_output = adapter.get_weather(city)
        messages.append({"type": "function_call_output", "call_id": tool_call.call_id, "output": json.dumps(tool_output, ensure_ascii=False)})

    second = client.responses.create(
        model=model,
        instructions="你是一个天气助手。涉及天气时优先调用工具。",
        input=messages,
        previous_response_id=first.id,
        stream=False,
        **extra_params,
    )
    return getattr(second, "output_text", "") or ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="上海今天天气怎么样？")
    parser.add_argument("--model", default="qwen3.5-plus")
    parser.add_argument("--mcp-mode", choices=["mcp", "mock"], default="mcp")
    parser.add_argument("--mcp-tool-name", default=os.environ.get("AMAP_MCP_TOOL_NAME", "maps_weather"))
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--list-tools", action="store_true")
    args = parser.parse_args()

    adapter = AMapMCPAdapter(
        mode=args.mcp_mode,
        mcp_tool_name=args.mcp_tool_name,
    )
    if args.list_tools:
        print(json.dumps(adapter.list_tools(), ensure_ascii=False, indent=2))
        return
    answer = run_once(
        question=args.question,
        model=args.model,
        adapter=adapter,
        enable_thinking=args.thinking,
    )
    print(answer)


if __name__ == "__main__":
    main()
