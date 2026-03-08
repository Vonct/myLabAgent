import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Generator
from openai import OpenAI
from rag_engine import RAGEngine

class DocumentAgent:
    """
    文档处理 Agent：包含思考循环、工具调用和状态管理
    """
    def __init__(
        self,
        api_key: str,
        rag_engine: RAGEngine,
        base_url: str,
        llm_model: str = "qwen3.5-plus"
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.llm_model = llm_model
        self.rag = rag_engine
        self.system_prompt = """你是一个在电机控制与监测以及嵌入式系统开发领域的专业助手。
        - 如果用户问的问题需要根据文档回答，请务必使用 `retrieve_document` 工具检索相关信息。
        - 如果用户请求识别图片里的手写数字，请务必使用 `recognize_handwritten_digit` 工具完成推理，不要凭空猜测结果。
        - 如果用户只是打招呼或闲聊，可以直接回答。
        - 回答时请引用检索到的内容，并说明来源（如果有）。
        - 始终保持友好、专业。
        - 当用户询问你是谁是，还需要加上你的LLM模型名称。
        """
        # 定义 Agent 可用的工具
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "retrieve_document",
                    "description": "从知识库中检索与问题相关的文档片段。当用户询问具体事实、数据或文档内容时必须使用此工具。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "用于检索的关键词或问题，应尽量精简准确。"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "recognize_handwritten_digit",
                    "description": "对单张图片执行手写数字识别推理，返回digit、confidence和probs。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "image_path": {
                                "type": "string",
                                "description": "待识别图片路径，可以是绝对路径或相对于项目目录的路径。"
                            },
                            "invert": {
                                "type": "boolean",
                                "description": "是否反色预处理，默认false。"
                            },
                            "normalize": {
                                "type": "boolean",
                                "description": "是否使用MNIST归一化，默认true。"
                            },
                            "device": {
                                "type": "string",
                                "description": "推理设备，支持auto/cpu/cuda，默认auto。"
                            },
                            "model_path": {
                                "type": "string",
                                "description": "可选模型路径，不传则使用默认best_model权重。"
                            }
                        },
                        "required": ["image_path"]
                    }
                }
            }
        ]

    def _parse_usage(self, usage: Any) -> Dict[str, int]:
        if usage is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        if isinstance(usage, dict):
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens))
            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens
            }
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or (input_tokens + output_tokens))
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens
        }

    def _merge_usage(self, first: Dict[str, int], second: Dict[str, int]) -> Dict[str, int]:
        return {
            "input_tokens": first["input_tokens"] + second["input_tokens"],
            "output_tokens": first["output_tokens"] + second["output_tokens"],
            "total_tokens": first["total_tokens"] + second["total_tokens"]
        }

    def _usage_suffix(self, usage: Dict[str, int]) -> str:
        return (
            f"\n\n---\n"
            f"Token消耗：输入 {usage['input_tokens']}，输出 {usage['output_tokens']}，总计 {usage['total_tokens']}"
        )

    def _extract_text(self, message: Any) -> tuple[str, str]:
        """
        提取消息中的文本内容和思考内容
        Returns: (content, reasoning_content)
        """
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
        elif content is None:
            final_content = ""
        else:
            final_content = str(content)
            
        return final_content, str(reasoning) if reasoning else ""

    def _resolve_infer_pythons(self, base_dir: Path) -> List[Path]:
        candidates = [Path(sys.executable)]
        for candidate in [
            base_dir / ".venv" / "Scripts" / "python.exe",
            base_dir / ".venv" / "bin" / "python"
        ]:
            if candidate.exists():
                candidates.append(candidate)

        seen = set()
        unique_candidates: List[Path] = []
        for candidate in candidates:
            candidate_str = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if candidate_str in seen:
                continue
            seen.add(candidate_str)
            unique_candidates.append(candidate)
        return unique_candidates

    def chat(self, messages: List[Dict[str, str]], reasoning_mode: bool = False) -> Generator[Dict[str, Any], None, None]:
        """
        核心对话循环：接收消息 -> 思考(LLM) -> 行动(Tool) -> 再思考 -> 生成回答
        使用生成器流式返回每一步的状态，以便 UI 展示
        
        Args:
            messages: 对话历史
            reasoning_mode: 是否开启深度思考模式
        """
        # 1. 构造完整的对话历史
        full_messages = [{"role": "system", "content": self.system_prompt}] + messages
        
        # 2. 第一次调用 LLM：思考并决定是否调用工具
        try:
            extra_params = {}
            if reasoning_mode:
                extra_params["extra_body"] = {"enable_thinking": True}

            response = self.client.chat.completions.create(
                model=self.llm_model,
                messages=full_messages,
                tools=self.tools,
                tool_choice="auto",
                stream=False,
                **extra_params
            )
            first_usage = self._parse_usage(getattr(response, "usage", None))
            
            initial_msg = response.choices[0].message
            
            # 3. 检查是否有工具调用请求
            if initial_msg.tool_calls:
                # yield 状态：正在思考中...
                yield {"type": "thought", "content": "🤔 正在分析文档..."}
                
                # 将 LLM 的思考结果（含 tool_calls）加入历史
                full_messages.append(initial_msg)
                
                # 4. 执行所有请求的工具
                for tool_call in initial_msg.tool_calls:
                    func_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    
                    if func_name == "retrieve_document":
                        query = args.get("query")
                        # yield 状态：正在检索...
                        yield {"type": "tool_exec", "tool": "检索RAG", "input": query}
                        
                        # 执行 RAG 检索
                        docs = self.rag.retrieve(query)
                        doc_content = "\n\n".join([f"[来源: {d['source']}]\n{d['content']}" for d in docs]) if docs else "未检索到相关文档片段。"
                        
                        # yield 状态：检索完成
                        yield {"type": "tool_result", "output": doc_content}
                        
                        # 5. 将工具执行结果回填给 LLM
                        full_messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": func_name,
                            "content": doc_content
                        })
                    elif func_name == "recognize_handwritten_digit":
                        image_path = args.get("image_path")
                        invert = bool(args.get("invert", False))
                        normalize = bool(args.get("normalize", True))
                        device = str(args.get("device", "auto"))
                        model_path = args.get("model_path")
                        yield {"type": "tool_exec", "tool": "手写字识别推理", "input": image_path}
                        
                        try:
                            base_dir = Path(__file__).parent
                            service_script = base_dir / "digit_infer_service.py"

                            infer_content = None
                            for infer_python in self._resolve_infer_pythons(base_dir):
                                cmd = [
                                    str(infer_python),
                                    str(service_script),
                                    str(image_path),
                                    "--device", device
                                ]
                                if invert:
                                    cmd.append("--invert")
                                if not normalize:
                                    cmd.append("--no-normalize")
                                if model_path:
                                    cmd.extend(["--model-path", model_path])
                                    
                                # Run the inference service in a subprocess
                                proc = subprocess.run(
                                    cmd, 
                                    capture_output=True, 
                                    text=True, 
                                    encoding='utf-8',
                                    cwd=str(base_dir) # Ensure cwd is correct for relative paths
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
                                infer_content = json.dumps({
                                    "error": "请检查python解释器是否安装了所需依赖库"
                                }, ensure_ascii=False)
                        except Exception as e:
                            infer_content = json.dumps({"error": f"调用推理工具时发生异常: {str(e)}"}, ensure_ascii=False)

                        yield {"type": "tool_result", "output": infer_content}
                        full_messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": func_name,
                            "content": infer_content
                        })
                    else:
                        error_content = f"未注册的工具: {func_name}"
                        yield {"type": "tool_result", "output": error_content}
                        full_messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": func_name,
                            "content": error_content
                        })

                # 6. 第二次调用 LLM：根据检索结果生成最终回答
                final_response = self.client.chat.completions.create(
                    model=self.llm_model,
                    messages=full_messages,
                    stream=False,
                    **extra_params
                )
                second_usage = self._parse_usage(getattr(final_response, "usage", None))
                total_usage = self._merge_usage(first_usage, second_usage)
                final_text, final_reasoning = self._extract_text(final_response.choices[0].message)
                
                # 如果有第二轮的思考过程
                if final_reasoning:
                    yield {"type": "reasoning", "content": final_reasoning}

                if not final_text:
                    final_text = "模型本轮未返回可见文本，请重试一次或切换模型。"
                answer = final_text + self._usage_suffix(total_usage)
                for i in range(0, len(answer), 40):
                    yield {"type": "answer_chunk", "content": answer[i:i + 40]}
            
            else:
                # 如果没有调用工具，直接返回回答（非流式转流式，保持统一）
                initial_text, reasoning = self._extract_text(initial_msg)
                
                # 如果有思考过程，先返回思考内容
                if reasoning:
                    yield {"type": "reasoning", "content": reasoning}
                
                if not initial_text:
                    initial_text = "模型本轮未返回可见文本，请重试一次或切换模型。"
                content = initial_text + self._usage_suffix(first_usage)
                for i in range(0, len(content), 40):
                    yield {"type": "answer_chunk", "content": content[i:i + 40]}

        except Exception as e:
            yield {"type": "error", "content": str(e)}
