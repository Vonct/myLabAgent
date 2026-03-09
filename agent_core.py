from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Generator

from openai import OpenAI

from amap_mcp_adapter import AMapMCPAdapter, DEFAULT_AMAP_MCP_COMMAND
from core.permissions import PermissionLevel
from core.tool_registry import ToolRegistry
from rag_engine import RAGEngine


class LabAgent:
    def __init__(
        self,
        api_key: str,
        rag_engine: RAGEngine,
        base_url: str,
        llm_model: str = "qwen3.5-plus",
        tool_registry: ToolRegistry | None = None,
        system_prompt: str = "",
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.llm_model = llm_model
        self.rag = rag_engine
        self.weather_adapter = AMapMCPAdapter(
            mode=os.environ.get("AMAP_MCP_MODE", "mcp"),
            mcp_command=os.environ.get("AMAP_MCP_COMMAND", DEFAULT_AMAP_MCP_COMMAND),
            mcp_tool_name=os.environ.get("AMAP_MCP_TOOL_NAME", "maps_weather"),
        )
        self.system_prompt = system_prompt.replace("当前 LLM 模型名称", self.llm_model)
        self.tool_registry = tool_registry
        if self.tool_registry is not None:
            self.tool_registry.register("retrieve_document", self._run_retrieve_document, PermissionLevel.READ_ONLY)
            self.tool_registry.register("recognize_handwritten_digit", self._run_digit_inference, PermissionLevel.EXEC)
            self.tool_registry.register("get_amap_weather", self._run_weather_query, PermissionLevel.NETWORK)
        self.tools = self.tool_registry.get_openai_schemas() if self.tool_registry else []

    def _parse_usage(self, usage: Any) -> dict[str, int]:
        if usage is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        if isinstance(usage, dict):
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens))
            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or (input_tokens + output_tokens))
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    def _merge_usage(self, first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
        return {
            "input_tokens": first["input_tokens"] + second["input_tokens"],
            "output_tokens": first["output_tokens"] + second["output_tokens"],
            "total_tokens": first["total_tokens"] + second["total_tokens"],
        }

    def _usage_suffix(self, usage: dict[str, int]) -> str:
        return (
            "\n\n---\n"
            f"Token 消耗：输入 {usage['input_tokens']}，输出 {usage['output_tokens']}，总计 {usage['total_tokens']}"
        )

    def _extract_text(self, message: Any) -> tuple[str, str]:
        content = getattr(message, "content", None)
        reasoning = getattr(message, "reasoning_content", "") or getattr(message, "reasoning", "")

        final_content = ""
        if isinstance(content, str):
            final_content = content
        elif isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if text:
                        parts.append(text)
                else:
                    text = getattr(item, "text", "") or getattr(item, "content", "")
                    if text:
                        parts.append(text)
            final_content = "".join(parts)
        elif content is not None:
            final_content = str(content)

        return final_content, str(reasoning) if reasoning else ""

    def _resolve_infer_pythons(self, base_dir: Path) -> list[Path]:
        candidates = [Path(sys.executable)]
        for candidate in [
            base_dir / ".venv" / "Scripts" / "python.exe",
            base_dir / ".venv" / "bin" / "python",
        ]:
            if candidate.exists():
                candidates.append(candidate)

        seen = set()
        unique_candidates: list[Path] = []
        for candidate in candidates:
            candidate_str = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if candidate_str in seen:
                continue
            seen.add(candidate_str)
            unique_candidates.append(candidate)
        return unique_candidates

    def _run_retrieve_document(self, args: dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip()
        docs = self.rag.retrieve(query)
        if not docs:
            return "未检索到相关文档片段。"
        return "\n\n".join([f"[来源: {d['source']}]\n{d['content']}" for d in docs])

    def _run_digit_inference(self, args: dict[str, Any]) -> str:
        image_path = args.get("image_path")
        invert = bool(args.get("invert", False))
        normalize = bool(args.get("normalize", True))
        device = str(args.get("device", "auto"))
        model_path = args.get("model_path")
        base_dir = Path(__file__).parent
        service_script = base_dir / "digit_infer_service.py"

        infer_content = None
        for infer_python in self._resolve_infer_pythons(base_dir):
            cmd = [
                str(infer_python),
                str(service_script),
                str(image_path),
                "--device",
                device,
            ]
            if invert:
                cmd.append("--invert")
            if not normalize:
                cmd.append("--no-normalize")
            if model_path:
                cmd.extend(["--model-path", model_path])

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(base_dir),
            )
            if proc.returncode != 0:
                continue

            output_text = proc.stdout.strip()
            try:
                json.loads(output_text)
                infer_content = output_text
                break
            except json.JSONDecodeError:
                continue

        if infer_content is None:
            infer_content = json.dumps(
                {"error": "请检查 Python 环境是否已安装手写数字识别所需依赖。"},
                ensure_ascii=False,
            )
        return infer_content

    def _run_weather_query(self, args: dict[str, Any]) -> str:
        city = str(args.get("city", "")).strip()
        try:
            weather_result = self.weather_adapter.get_weather(city)
            return json.dumps(weather_result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"天气工具调用失败: {e}"}, ensure_ascii=False)

    def chat(
        self,
        messages: list[dict[str, Any]],
        reasoning_mode: bool = False,
        supports_thinking: bool = True,
        session_store=None,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        full_messages = [{"role": "system", "content": self.system_prompt}] + messages

        try:
            extra_params = {}
            if reasoning_mode and supports_thinking:
                extra_params["extra_body"] = {"enable_thinking": True}

            response = self.client.chat.completions.create(
                model=self.llm_model,
                messages=full_messages,
                tools=self.tools,
                tool_choice="auto",
                stream=False,
                **extra_params,
            )
            first_usage = self._parse_usage(getattr(response, "usage", None))
            initial_msg = response.choices[0].message

            if initial_msg.tool_calls:
                yield {"type": "thought", "content": "正在分析问题并准备调用工具..."}
                full_messages.append(initial_msg)

                for tool_call in initial_msg.tool_calls:
                    func_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    yield {"type": "tool_exec", "tool": func_name, "input": json.dumps(args, ensure_ascii=False)}
                    tool_output = self.tool_registry.execute(func_name, args) if self.tool_registry else json.dumps({"error": "Tool registry unavailable"}, ensure_ascii=False)
                    yield {"type": "tool_result", "output": tool_output}
                    if session_store and session_id and task_id:
                        session_store.append_tool_event(
                            session_id,
                            task_id,
                            {
                                "tool": func_name,
                                "args": args,
                                "output_preview": tool_output[:400],
                            },
                        )
                    full_messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": func_name,
                            "content": tool_output,
                        }
                    )

                final_response = self.client.chat.completions.create(
                    model=self.llm_model,
                    messages=full_messages,
                    stream=False,
                    **extra_params,
                )
                second_usage = self._parse_usage(getattr(final_response, "usage", None))
                total_usage = self._merge_usage(first_usage, second_usage)
                final_text, final_reasoning = self._extract_text(final_response.choices[0].message)

                if final_reasoning:
                    yield {"type": "reasoning", "content": final_reasoning}

                if not final_text:
                    final_text = "模型本轮没有返回可见文本，请重试或切换模型。"
                answer = final_text + self._usage_suffix(total_usage)
                for i in range(0, len(answer), 40):
                    yield {"type": "answer_chunk", "content": answer[i:i + 40]}
            else:
                initial_text, reasoning = self._extract_text(initial_msg)
                if reasoning:
                    yield {"type": "reasoning", "content": reasoning}
                if not initial_text:
                    initial_text = "模型本轮没有返回可见文本，请重试或切换模型。"
                content = initial_text + self._usage_suffix(first_usage)
                for i in range(0, len(content), 40):
                    yield {"type": "answer_chunk", "content": content[i:i + 40]}
        except Exception as e:
            yield {"type": "error", "content": str(e)}
