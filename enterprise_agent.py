"""基于 DashScope 原生 function calling 的企业知识助手。"""

import json
import os
import re
from dataclasses import dataclass, field
from http import HTTPStatus
from time import perf_counter

from dashscope import Generation
from langchain_core.utils.function_calling import convert_to_openai_tool

import config_data as config
from database_service import DatabaseService
from knowledge_base import KnowledgeBaseService
from rag import RagService
from tools import build_business_tools, build_calculator_tools, build_knowledge_tools
from dashscope_retry import (
    MAX_NETWORK_ATTEMPTS,
    is_retryable_network_error,
    network_error_message,
    wait_before_retry,
)


@dataclass
class ToolExecution:
    name: str
    arguments: dict
    success: bool = True
    duration_ms: float = 0


@dataclass
class AgentResult:
    answer: str
    tool_executions: list[ToolExecution] = field(default_factory=list)
    knowledge_evidence: list[str] = field(default_factory=list)
    rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class EnterpriseAgent:
    """让 Qwen 自主选择工具，并根据工具结果继续推理。"""

    def __init__(
        self,
        rag_service: RagService,
        knowledge_base: KnowledgeBaseService,
        database_service: DatabaseService | None = None,
        max_rounds: int = 5,
    ):
        self.rag_service = rag_service
        self.knowledge_base = knowledge_base
        self.database_service = database_service or DatabaseService()
        self.max_rounds = max_rounds
        self.tools = [
            *build_knowledge_tools(rag_service, knowledge_base),
            *build_business_tools(self.database_service),
            *build_calculator_tools(),
        ]
        self.tools_by_name = {item.name: item for item in self.tools}
        self.tool_schemas = [convert_to_openai_tool(item) for item in self.tools]

    def run(self, question: str, recent_messages: list[dict]) -> AgentResult:
        """兼容非流式调用方，内部消费流式事件并返回最终结果。"""
        final_result = None
        for event in self.stream(question, recent_messages):
            if event["type"] == "done":
                final_result = event["result"]
        if final_result is None:
            raise RuntimeError("Agent 未返回最终结果")
        return final_result

    def stream(self, question: str, recent_messages: list[dict]):
        """流式执行模型—工具反馈循环，并产生 token、工具和完成事件。"""
        self._input_tokens = 0
        self._output_tokens = 0
        messages = [
            {
                "role": "system",
                "content": (
                    "你是企业内部智能知识助手。涉及公司制度、产品、技术、业务资料或"
                    "知识库文档时，必须优先调用工具，不得依靠常识编造。"
                    "不知道准确文件名时先调用 list_documents。"
                    "业务数据问题调用销售或项目查询工具，精确数值运算调用 calculate。"
                    "可以连续调用多个工具完成任务。根据知识工具结果回答时保留 [1][2] 引用。"
                    "资料不足时明确说明缺少什么信息。"
                ),
            }
        ]
        messages.extend(self._history_messages(recent_messages))
        messages.append({"role": "user", "content": question})
        executions: list[ToolExecution] = []
        knowledge_evidence: list[str] = []

        for round_number in range(1, self.max_rounds + 1):
            assistant_output = yield from self._invoke_model_stream(
                messages, include_tools=True
            )
            messages.append(assistant_output)
            tool_calls = assistant_output.get("tool_calls") or []

            if not tool_calls:
                result = AgentResult(
                    answer=str(assistant_output.get("content") or ""),
                    tool_executions=executions,
                    knowledge_evidence=knowledge_evidence,
                    rounds=round_number,
                    input_tokens=self._input_tokens,
                    output_tokens=self._output_tokens,
                )
                yield {"type": "done", "result": result}
                return

            for call_index, call in enumerate(tool_calls):
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                arguments = self._parse_arguments(function.get("arguments"))
                call_id = call.get("id") or f"tool_call_{round_number}_{call_index}"
                tool_instance = self.tools_by_name.get(name)
                tool_started = perf_counter()
                yield {
                    "type": "tool_start",
                    "name": name or "unknown",
                    "arguments": arguments,
                    "round": round_number,
                }

                if tool_instance is None:
                    result = f"未知工具：{name}"
                    success = False
                else:
                    try:
                        result = str(tool_instance.invoke(arguments))
                        success = True
                    except Exception as exc:
                        result = f"工具执行失败：{exc}"
                        success = False

                executions.append(
                    ToolExecution(
                        name=name or "unknown",
                        arguments=arguments,
                        success=success,
                        duration_ms=(perf_counter() - tool_started) * 1000,
                    )
                )
                if name == "search_knowledge_base" and success:
                    knowledge_evidence.extend(self._extract_evidence(result))
                yield {
                    "type": "tool_end",
                    "name": name or "unknown",
                    "success": success,
                    "round": round_number,
                    "duration_ms": executions[-1].duration_ms,
                }
                messages.append(
                    {
                        "role": "tool",
                        "content": result,
                        "tool_call_id": call_id,
                    }
                )

        messages.append(
            {
                "role": "user",
                "content": "停止继续调用工具，请根据已有工具结果生成最终回答。",
            }
        )
        final_output = yield from self._invoke_model_stream(
            messages, include_tools=False
        )
        result = AgentResult(
            answer=str(final_output.get("content") or ""),
            tool_executions=executions,
            knowledge_evidence=knowledge_evidence,
            rounds=self.max_rounds,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )
        yield {"type": "done", "result": result}

    @staticmethod
    def _extract_evidence(result: str) -> list[str]:
        """从知识检索工具结果中拆出独立的带编号依据。"""
        if not re.search(r"(?m)^\[\d+\] 来源：", result):
            return []
        return [
            block.strip()
            for block in re.split(r"\n\n(?=\[\d+\] 来源：)", result)
            if block.strip()
        ]

    def _invoke_model(self, messages: list[dict], include_tools: bool) -> dict:
        kwargs = {
            "api_key": os.getenv("DASHSCOPE_API_KEY"),
            "model": config.chat_model_name,
            "messages": messages,
            "result_format": "message",
        }
        if include_tools:
            kwargs["tools"] = self.tool_schemas

        response = self._call_with_network_retry(**kwargs)
        if response.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"DashScope 调用失败：{response.code} - {response.message}"
            )
        output = response.output.choices[0].message
        self._add_usage(getattr(response, "usage", None))
        return self._plain_dict(output)

    def _invoke_model_stream(self, messages: list[dict], include_tools: bool):
        """使用 DashScope 累积式流响应，返回完整消息并逐段产生文本。"""
        kwargs = {
            "api_key": os.getenv("DASHSCOPE_API_KEY"),
            "model": config.chat_model_name,
            "messages": messages,
            "result_format": "message",
            "stream": True,
            "incremental_output": False,
        }
        if include_tools:
            kwargs["tools"] = self.tool_schemas

        previous_content = ""
        final_output = None
        final_usage = None
        for attempt in range(1, MAX_NETWORK_ATTEMPTS + 1):
            try:
                for response in Generation.call(**kwargs):
                    if response.status_code != HTTPStatus.OK:
                        raise RuntimeError(
                            f"DashScope 调用失败：{response.code} - {response.message}"
                        )
                    output = self._plain_dict(response.output.choices[0].message)
                    final_output = output
                    final_usage = getattr(response, "usage", final_usage)
                    content = str(output.get("content") or "")
                    if content.startswith(previous_content):
                        delta = content[len(previous_content) :]
                    else:
                        delta = content
                    previous_content = content
                    if delta:
                        yield {"type": "token", "content": delta}
                break
            except Exception as exc:
                # 已向页面输出内容后不重新请求，避免生成结果重复或前后不一致。
                can_retry = not previous_content and is_retryable_network_error(exc)
                if not can_retry or attempt == MAX_NETWORK_ATTEMPTS:
                    if is_retryable_network_error(exc):
                        raise RuntimeError(network_error_message(exc)) from exc
                    raise
                wait_before_retry(attempt)

        if final_output is None:
            raise RuntimeError("DashScope 流式调用未返回内容")
        self._add_usage(final_usage)
        return final_output

    @staticmethod
    def _call_with_network_retry(**kwargs):
        for attempt in range(1, MAX_NETWORK_ATTEMPTS + 1):
            try:
                return Generation.call(**kwargs)
            except Exception as exc:
                if not is_retryable_network_error(exc) or attempt == MAX_NETWORK_ATTEMPTS:
                    if is_retryable_network_error(exc):
                        raise RuntimeError(network_error_message(exc)) from exc
                    raise
                wait_before_retry(attempt)

    def _add_usage(self, usage) -> None:
        if not usage:
            return
        plain = self._plain_value(usage)
        self._input_tokens += int(plain.get("input_tokens", 0) or 0)
        self._output_tokens += int(plain.get("output_tokens", 0) or 0)

    @staticmethod
    def _history_messages(recent_messages: list[dict]) -> list[dict]:
        messages = []
        for item in recent_messages[-6:]:
            role = "assistant" if item.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": str(item.get("content", ""))})
        return messages

    @staticmethod
    def _parse_arguments(value) -> dict:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @classmethod
    def _plain_dict(cls, value) -> dict:
        """将 DashScope 的 DictMixin 响应递归转换为普通字典。"""
        if hasattr(value, "items"):
            return {key: cls._plain_value(item) for key, item in value.items()}
        return dict(value)

    @classmethod
    def _plain_value(cls, value):
        if hasattr(value, "items"):
            return {key: cls._plain_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._plain_value(item) for item in value]
        return value
