"""Minimal LangChain ReAct-style agent demo.

This example uses LangChain's high-level `create_agent`.
The tool loop is handled by LangChain:

LLM -> tool_call -> tool result -> LLM -> final answer

重点：
1. 你只注册工具和模型。
2. LangChain 帮你维护 ReAct 循环。
3. 你拿到的是最终对话 messages。
"""

from __future__ import annotations

import os

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool

from langchain_learning.config import env_bool, load_dotenv_if_exists


load_dotenv_if_exists()

MODEL_NAME = os.getenv("LABAGENT_LEARNING_MODEL", "gpt-5.4-mini")
MODEL_PROVIDER = os.getenv("LABAGENT_LEARNING_PROVIDER", "openai")
BASE_URL = os.getenv("LABAGENT_LEARNING_BASE_URL")
API_KEY = os.getenv("LABAGENT_LEARNING_API_KEY") or os.getenv("OPENAI_API_KEY")
USE_RESPONSES_API = env_bool("LABAGENT_LEARNING_USE_RESPONSES_API")


def build_chat_model():
    """Create the chat model used by LangChain.

    provider 用来告诉 LangChain 选哪个模型适配器。
    对 OpenAI-compatible 服务，provider 保持 openai 即可；
    真正的服务地址由 base_url 决定。

    大多数 OpenAI-compatible 服务支持的是 Chat Completions；
    只有确定你的服务支持 Responses API 时，才设置：

    export LABAGENT_LEARNING_USE_RESPONSES_API="true"
    """
    kwargs = {
        "model": MODEL_NAME,
        "model_provider": MODEL_PROVIDER,
    }

    if BASE_URL:
        kwargs["base_url"] = BASE_URL
    if API_KEY:
        kwargs["api_key"] = API_KEY
    if USE_RESPONSES_API is not None:
        kwargs["use_responses_api"] = USE_RESPONSES_API

    return init_chat_model(**kwargs)


@tool
def get_weather(city: str) -> str:
    """Get weather for a city.

    `@tool` 会把普通 Python 函数包装成 LLM 可见的工具：
    - 函数名会变成 tool name: get_weather
    - docstring 会变成 tool description
    - 参数类型会被转成 tool schema
    """
    fake_weather = {
        "北京": "晴，12°C，空气干燥",
        "上海": "小雨，16°C，路面湿滑",
        "杭州": "多云，18°C，适合步行",
    }
    return fake_weather.get(city, f"暂时没有 {city} 的天气数据")


def build_agent():
    """Build a LangChain agent.

    `create_agent` 是高层封装。
    你看不到 while loop，但内部大概会做：

    1. 把 messages + tool schema 发给模型。
    2. 如果模型返回 tool_call，就执行对应工具。
    3. 把工具结果作为 observation 放回 messages。
    4. 再问模型，直到模型输出 final answer。
    """
    model = build_chat_model()
    return create_agent(
        model=model,
        tools=[get_weather],
        system_prompt=(
            "你是一个简洁的中文助手。"
            "需要外部信息时优先调用工具，拿到工具结果后再回答。"
        ),
    )


def main() -> None:
    agent = build_agent()

    # LangChain agent 的输入是一个 messages dict。
    # 它会返回完整对话历史，所以最后一条通常就是最终回答。
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "帮我查一下杭州天气，然后给一句出门建议。",
                }
            ]
        }
    )

    # result["messages"] 里会包含：
    # user message -> assistant tool_call -> tool result -> assistant final answer
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
