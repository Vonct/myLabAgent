"""Minimal LangGraph Plan-and-Execute demo.

The same base model is reused for planner, executor, and summarizer.
Their roles are separated by prompts and graph state, not by model weights.

重点：
1. LangGraph 不是替你隐藏流程，而是让你显式写状态机。
2. State 是整条工作流共享的数据。
3. Node 是一个处理函数。
4. Edge 决定执行顺序。
5. Conditional edge 决定循环或结束。
"""

from __future__ import annotations

import os
from typing import Literal, TypedDict

from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from langchain_learning.config import env_bool, load_dotenv_if_exists


load_dotenv_if_exists()

MODEL_NAME = os.getenv("LABAGENT_LEARNING_MODEL", "gpt-5.4-mini")
MODEL_PROVIDER = os.getenv("LABAGENT_LEARNING_PROVIDER", "openai")
BASE_URL = os.getenv("LABAGENT_LEARNING_BASE_URL")
API_KEY = os.getenv("LABAGENT_LEARNING_API_KEY") or os.getenv("OPENAI_API_KEY")
USE_RESPONSES_API = env_bool("LABAGENT_LEARNING_USE_RESPONSES_API")


class Plan(BaseModel):
    """Structured planner output.

    Planner 不直接自由发挥，而是必须输出这个结构。
    这就是 structured output 的价值：后面的 graph 节点可以稳定读取 plan.steps。
    """

    steps: list[str] = Field(description="执行任务需要的步骤，最多 3 步")


class PEState(TypedDict):
    """The shared state passed between LangGraph nodes.

    每个节点都会收到当前 state，并返回一个 dict 来更新 state。
    你可以把它理解成这个工作流的“运行时黑板”。
    """

    task: str
    plan: list[str]
    cursor: int
    observations: list[str]
    answer: str


def build_chat_model():
    """Create the chat model used by all LangGraph nodes.

    这里仍然可以用你自己的 OpenAI-compatible base_url。
    默认更适合 Chat Completions；如果服务明确支持 Responses API，
    再设置 LABAGENT_LEARNING_USE_RESPONSES_API=true。
    """
    kwargs = {
        "model": MODEL_NAME,
        "model_provider": MODEL_PROVIDER,
        "temperature": 0,
    }

    if BASE_URL:
        kwargs["base_url"] = BASE_URL
    if API_KEY:
        kwargs["api_key"] = API_KEY
    if USE_RESPONSES_API is not None:
        kwargs["use_responses_api"] = USE_RESPONSES_API

    return init_chat_model(**kwargs)


# 这里故意复用同一个底层模型。
# Planner / Executor / Summarizer 的区别来自 prompt、输出结构和所在节点。
model = build_chat_model()
planner = model.with_structured_output(Plan)


def plan_node(state: PEState) -> dict:
    """Planner node: turn the user task into executable steps."""
    plan = planner.invoke(
        [
            SystemMessage(content="你是 Planner。把用户任务拆成最多 3 个可执行步骤。"),
            HumanMessage(content=state["task"]),
        ]
    )

    # 返回值会 merge 回 LangGraph state。
    # 这里初始化 cursor 和 observations，准备进入 execute 循环。
    return {
        "plan": plan.steps[:3],
        "cursor": 0,
        "observations": [],
    }


def execute_node(state: PEState) -> dict:
    """Executor node: execute exactly one step each time it is called."""
    step = state["plan"][state["cursor"]]
    result = model.invoke(
        [
            SystemMessage(
                content="你是 Executor。只执行当前步骤，输出观察结果，不要总结全局。"
            ),
            HumanMessage(content=f"任务：{state['task']}\n当前步骤：{step}"),
        ]
    )

    # 每执行一步，就把观察结果追加到 observations，
    # 同时 cursor + 1，让下一轮执行下一步。
    observations = state["observations"] + [f"{step}: {result.content}"]
    return {
        "observations": observations,
        "cursor": state["cursor"] + 1,
    }


def final_node(state: PEState) -> dict:
    """Final node: summarize all observations into the final answer."""
    result = model.invoke(
        [
            SystemMessage(content="你是 Summarizer。根据执行记录给出最终答案。"),
            HumanMessage(content=f"任务：{state['task']}\n执行记录：{state['observations']}"),
        ]
    )
    return {"answer": result.content}


def should_continue(state: PEState) -> Literal["execute", "final"]:
    """Routing function used by conditional edges.

    如果还有没执行的 plan step，就回到 execute。
    如果所有 step 都执行完，就进入 final。
    """
    if state["cursor"] < len(state["plan"]):
        return "execute"
    return "final"


def build_graph():
    """Build the explicit Plan-and-Execute state graph."""
    graph_builder = StateGraph(PEState)

    # Node = 工作流里的处理步骤。
    # 每个 node 都是一个普通 Python 函数。
    graph_builder.add_node("plan", plan_node)
    graph_builder.add_node("execute", execute_node)
    graph_builder.add_node("final", final_node)

    # Edge = 下一步去哪。
    # START/END 是 LangGraph 的特殊起点和终点。
    graph_builder.add_edge(START, "plan")

    # Conditional edge = 根据 state 动态选择下一步。
    # 这两条边共同形成 execute 循环：
    # plan -> execute -> execute -> ... -> final
    graph_builder.add_conditional_edges("plan", should_continue)
    graph_builder.add_conditional_edges("execute", should_continue)
    graph_builder.add_edge("final", END)

    return graph_builder.compile()


def main() -> None:
    agent = build_graph()

    # invoke 的输入就是初始 state。
    # LangGraph 会沿着图执行节点，并不断更新 state。
    result = agent.invoke(
        {
            "task": "分析 CoT、ReAct、Plan-and-Execute 的区别，给一个面试回答。",
            "plan": [],
            "cursor": 0,
            "observations": [],
            "answer": "",
        }
    )

    # 最终 state 里包含 answer、plan、observations 等所有过程数据。
    print(result["answer"])


if __name__ == "__main__":
    main()
