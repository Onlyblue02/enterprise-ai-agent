"""基于 LangGraph 的企业经营分析报告工作流。"""

import json
import os
import re
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Callable, TypedDict
from uuid import uuid4

from dashscope import Generation
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

import config_data as config
from database_service import DatabaseService
from rag import RagService


class ReportState(TypedDict, total=False):
    request: str
    plan: dict
    knowledge_context: str
    sales_context: str
    draft_report: str
    review_feedback: str
    review_passed: bool
    revised_report: str
    approval_decision: str
    approval_feedback: str
    final_report: str
    trace: list[dict]


@dataclass
class ReportWorkflowResult:
    final_report: str
    current_report: str
    plan: dict
    review_feedback: str
    awaiting_approval: bool
    thread_id: str
    trace: list[dict]
    knowledge_context: str
    sales_context: str
    input_tokens: int = 0
    output_tokens: int = 0


class EnterpriseReportWorkflow:
    """规划、取数、检索、写作、复核并汇总企业报告。"""

    def __init__(
        self,
        rag_service: RagService,
        database_service: DatabaseService,
        llm_call: Callable[[list[dict]], str] | None = None,
        llm_stream: Callable[[list[dict], Callable[[str], None]], str] | None = None,
        checkpoint_path: str | None = None,
    ):
        self.rag_service = rag_service
        self.database_service = database_service
        self.llm_call = llm_call or self._dashscope_call
        if llm_stream is not None:
            self.llm_stream = llm_stream
        elif llm_call is not None:
            self.llm_stream = self._nonstream_as_stream
        else:
            self.llm_stream = self._dashscope_stream
        self.progress_callback: Callable[[str, str], None] | None = None
        self.token_callback: Callable[[str, str], None] | None = None
        self._input_tokens = 0
        self._output_tokens = 0
        self.checkpoint_path = checkpoint_path or config.workflow_checkpoint_path
        if self.checkpoint_path != ":memory:":
            Path(self.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
        self.checkpointer = SqliteSaver.from_conn_string(self.checkpoint_path)
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(ReportState)
        builder.add_node("plan_task", self._plan_task)
        builder.add_node("retrieve_knowledge", self._retrieve_knowledge)
        builder.add_node("query_sales", self._query_sales)
        builder.add_node("write_draft", self._draft_report)
        builder.add_node("review_report", self._review_report)
        builder.add_node("revise_report", self._revise_report)
        builder.add_node("human_approval", self._human_approval)
        builder.add_node("apply_human_revision", self._apply_human_revision)
        builder.add_node("finalize", self._finalize)

        builder.set_entry_point("plan_task")
        builder.add_conditional_edges(
            "plan_task",
            self._route_after_plan,
            {
                "retrieve_knowledge": "retrieve_knowledge",
                "query_sales": "query_sales",
            },
        )
        builder.add_edge("retrieve_knowledge", "query_sales")
        builder.add_edge("query_sales", "write_draft")
        builder.add_edge("write_draft", "review_report")
        builder.add_conditional_edges(
            "review_report",
            self._route_after_review,
            {
                "revise_report": "revise_report",
                "human_approval": "human_approval",
            },
        )
        builder.add_edge("revise_report", "human_approval")
        builder.add_conditional_edges(
            "human_approval",
            self._route_after_human_approval,
            {
                "apply_human_revision": "apply_human_revision",
                "finalize": "finalize",
            },
        )
        builder.add_edge("apply_human_revision", "human_approval")
        builder.add_edge("finalize", END)
        return builder.compile(
            checkpointer=self.checkpointer,
            interrupt_before=["human_approval"],
        )

    def start(
        self,
        request: str,
        thread_id: str | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
        token_callback: Callable[[str, str], None] | None = None,
    ) -> ReportWorkflowResult:
        thread_id = thread_id or uuid4().hex
        config = self._config(thread_id)
        self._reset_usage()
        self._set_callbacks(progress_callback, token_callback)
        try:
            self.graph.invoke(
                {
                    "request": request,
                    "trace": [],
                    "approval_decision": "",
                    "approval_feedback": "",
                },
                config,
            )
            return self._result(thread_id)
        finally:
            self._set_callbacks(None, None)

    def resume(
        self,
        thread_id: str,
        decision: str,
        feedback: str = "",
        progress_callback: Callable[[str, str], None] | None = None,
        token_callback: Callable[[str, str], None] | None = None,
    ) -> ReportWorkflowResult:
        if decision not in {"approved", "revise"}:
            raise ValueError("审批决定必须是 approved 或 revise")
        if decision == "revise" and not feedback.strip():
            raise ValueError("要求修改时必须填写修改意见")

        config = self._config(thread_id)
        snapshot = self.graph.get_state(config)
        if "human_approval" not in snapshot.next:
            raise ValueError("当前工作流不在等待人工审批状态")

        self._reset_usage()
        self._set_callbacks(progress_callback, token_callback)
        try:
            self.graph.update_state(
                config,
                {
                    "approval_decision": decision,
                    "approval_feedback": feedback.strip(),
                },
            )
            self.graph.invoke(None, config)
            return self._result(thread_id)
        finally:
            self._set_callbacks(None, None)

    def _result(self, thread_id: str) -> ReportWorkflowResult:
        snapshot = self.graph.get_state(self._config(thread_id))
        state = snapshot.values
        if not state:
            raise ValueError(f"未找到工作流 checkpoint：{thread_id}")
        current_report = (
            state.get("revised_report") or state.get("draft_report", "")
        )
        return ReportWorkflowResult(
            final_report=state.get("final_report", ""),
            current_report=current_report,
            plan=state.get("plan", {}),
            review_feedback=state.get("review_feedback", ""),
            awaiting_approval="human_approval" in snapshot.next,
            thread_id=thread_id,
            trace=state.get("trace", []),
            knowledge_context=state.get("knowledge_context", ""),
            sales_context=state.get("sales_context", ""),
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )

    def load(self, thread_id: str) -> ReportWorkflowResult:
        """从持久化 checkpoint 恢复指定工作流。"""
        return self._result(thread_id)

    def close(self) -> None:
        """关闭 SQLite checkpoint 连接。"""
        self.checkpointer.conn.close()

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def _plan_task(self, state: ReportState) -> dict:
        self._notify_progress("plan_task", "正在分析任务并生成执行计划")
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是企业报告规划器。把用户要求转换为执行计划，只输出合法 JSON。"
                    "字段必须包含 title、needs_knowledge、knowledge_query、year、"
                    "start_month、end_month、region、focus。"
                    "year 和月份必须是数字；region 不限定时为空字符串。"
                ),
            },
            {"role": "user", "content": state["request"]},
        ]
        try:
            plan = self._parse_json(self.llm_call(prompt))
        except Exception:
            plan = {}
        plan = self._normalize_plan(plan, state["request"])
        return {
            "plan": plan,
            "trace": self._append_trace(state, "plan_task", "已生成报告执行计划"),
        }

    @staticmethod
    def _route_after_plan(state: ReportState) -> str:
        return (
            "retrieve_knowledge"
            if state.get("plan", {}).get("needs_knowledge")
            else "query_sales"
        )

    def _retrieve_knowledge(self, state: ReportState) -> dict:
        self._notify_progress("retrieve_knowledge", "正在检索知识库资料")
        query = state["plan"].get("knowledge_query") or state["request"]
        documents = self.rag_service.retrieve_source_docs(query)
        context = (
            self.rag_service.format_tool_documents(documents)
            if documents
            else "未检索到相关知识库资料。"
        )
        return {
            "knowledge_context": context,
            "trace": self._append_trace(
                state, "retrieve_knowledge", f"召回 {len(documents)} 个知识片段"
            ),
        }

    def _query_sales(self, state: ReportState) -> dict:
        self._notify_progress("query_sales", "正在查询企业销售数据")
        plan = state["plan"]
        rows = self.database_service.query_sales(
            year=plan["year"],
            start_month=plan["start_month"],
            end_month=plan["end_month"],
            region=plan.get("region", ""),
        )
        summary = self.database_service.sales_summary(
            plan["year"], plan["start_month"], plan["end_month"]
        )
        context = json.dumps(
            {"details": rows, "summary_by_region": summary},
            ensure_ascii=False,
            indent=2,
        )
        return {
            "sales_context": context,
            "trace": self._append_trace(
                state, "query_sales", f"读取 {len(rows)} 条销售记录"
            ),
        }

    def _draft_report(self, state: ReportState) -> dict:
        self._notify_progress("write_draft", "正在流式生成报告初稿")
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是企业经营分析师。只依据提供的数据和知识资料写 Markdown 报告。"
                    "报告包含执行摘要、数据概览、关键发现、制度或资料依据、风险和建议。"
                    "知识资料结论保留 [1][2] 引用；不得虚构缺失数据。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户要求：{state['request']}\n\n执行计划："
                    f"{json.dumps(state['plan'], ensure_ascii=False)}\n\n"
                    f"销售数据：\n{state.get('sales_context', '无')}\n\n"
                    f"知识资料：\n{state.get('knowledge_context', '未要求检索')}"
                ),
            },
        ]
        draft = self._stream_text(prompt, "write_draft")
        return {
            "draft_report": draft,
            "trace": self._append_trace(state, "draft_report", "已生成报告初稿"),
        }

    def _review_report(self, state: ReportState) -> dict:
        self._notify_progress("review_report", "正在执行报告质量审核")
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是企业报告质量审核员。检查报告是否忠于数据、是否回答用户要求、"
                    "是否包含关键结论和风险、知识结论是否有引用。只输出 JSON："
                    '{"passed":true或false,"feedback":"具体修改意见"}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户要求：{state['request']}\n\n"
                    f"销售数据：{state.get('sales_context', '')}\n\n"
                    f"报告初稿：{state.get('draft_report', '')}"
                ),
            },
        ]
        try:
            review = self._parse_json(self.llm_call(prompt))
            passed = bool(review.get("passed", False))
            feedback = str(review.get("feedback") or "未提供审核意见")
        except Exception:
            passed = False
            feedback = "审核输出无法解析，需要按原始数据重新检查并修订。"
        return {
            "review_passed": passed,
            "review_feedback": feedback,
            "trace": self._append_trace(
                state, "review_report", "审核通过" if passed else "审核要求修订"
            ),
        }

    @staticmethod
    def _route_after_review(state: ReportState) -> str:
        return "human_approval" if state.get("review_passed") else "revise_report"

    def _revise_report(self, state: ReportState) -> dict:
        self._notify_progress("revise_report", "正在根据模型审核意见流式修订")
        prompt = [
            {
                "role": "system",
                "content": "你是企业报告编辑。依据审核意见修订报告，只输出完整 Markdown 报告。",
            },
            {
                "role": "user",
                "content": (
                    f"审核意见：{state.get('review_feedback', '')}\n\n"
                    f"原报告：{state.get('draft_report', '')}\n\n"
                    f"销售数据：{state.get('sales_context', '')}\n\n"
                    f"知识资料：{state.get('knowledge_context', '')}"
                ),
            },
        ]
        revised = self._stream_text(prompt, "revise_report")
        return {
            "revised_report": revised,
            "trace": self._append_trace(state, "revise_report", "已根据审核意见修订"),
        }

    def _human_approval(self, state: ReportState) -> dict:
        self._notify_progress("human_approval", "正在处理人工审批决定")
        decision = state.get("approval_decision", "")
        detail = "人工批准报告" if decision == "approved" else "人工要求修改报告"
        return {
            "trace": self._append_trace(state, "human_approval", detail),
        }

    @staticmethod
    def _route_after_human_approval(state: ReportState) -> str:
        return (
            "finalize"
            if state.get("approval_decision") == "approved"
            else "apply_human_revision"
        )

    def _apply_human_revision(self, state: ReportState) -> dict:
        self._notify_progress(
            "apply_human_revision", "正在根据人工意见流式修订报告"
        )
        current_report = state.get("revised_report") or state.get("draft_report", "")
        prompt = [
            {
                "role": "system",
                "content": "你是企业报告编辑。严格按人工意见修订，只输出完整 Markdown 报告。",
            },
            {
                "role": "user",
                "content": (
                    f"人工修改意见：{state.get('approval_feedback', '')}\n\n"
                    f"当前报告：{current_report}\n\n"
                    f"销售数据：{state.get('sales_context', '')}\n\n"
                    f"知识资料：{state.get('knowledge_context', '')}"
                ),
            },
        ]
        revised = self._stream_text(prompt, "apply_human_revision")
        return {
            "revised_report": revised,
            "approval_decision": "",
            "trace": self._append_trace(
                state, "apply_human_revision", "已按人工意见修订，等待再次审批"
            ),
        }

    def _finalize(self, state: ReportState) -> dict:
        self._notify_progress("finalize", "正在汇总并完成最终报告")
        final_report = state.get("revised_report") or state.get("draft_report", "")
        return {
            "final_report": final_report,
            "trace": self._append_trace(state, "finalize", "报告已汇总完成"),
        }

    def _set_callbacks(
        self,
        progress_callback: Callable[[str, str], None] | None,
        token_callback: Callable[[str, str], None] | None,
    ) -> None:
        self.progress_callback = progress_callback
        self.token_callback = token_callback

    def _notify_progress(self, node: str, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(node, message)

    def _stream_text(self, messages: list[dict], node: str) -> str:
        def emit(token: str) -> None:
            if self.token_callback is not None and token:
                self.token_callback(node, token)

        return self.llm_stream(messages, emit)

    def _nonstream_as_stream(
        self,
        messages: list[dict],
        on_token: Callable[[str], None],
    ) -> str:
        """让测试或自定义非流式模型兼容流式回调接口。"""
        content = self.llm_call(messages)
        if content:
            on_token(content)
        return content

    def _reset_usage(self) -> None:
        self._input_tokens = 0
        self._output_tokens = 0

    def _record_usage(self, usage) -> None:
        if not usage:
            return
        plain = dict(usage) if hasattr(usage, "items") else {}
        self._input_tokens += int(plain.get("input_tokens", 0) or 0)
        self._output_tokens += int(plain.get("output_tokens", 0) or 0)

    @staticmethod
    def _normalize_plan(plan: dict, request: str) -> dict:
        start_month = max(1, min(12, int(plan.get("start_month") or 1)))
        end_month = max(1, min(12, int(plan.get("end_month") or 6)))
        if end_month < start_month:
            start_month, end_month = end_month, start_month
        return {
            "title": str(plan.get("title") or "企业经营分析报告"),
            "needs_knowledge": bool(plan.get("needs_knowledge", True)),
            "knowledge_query": str(plan.get("knowledge_query") or request),
            "year": int(plan.get("year") or 2026),
            "start_month": start_month,
            "end_month": end_month,
            "region": str(plan.get("region") or ""),
            "focus": str(plan.get("focus") or request),
        }

    @staticmethod
    def _append_trace(state: ReportState, node: str, detail: str) -> list[dict]:
        return [*(state.get("trace") or []), {"node": node, "detail": detail}]

    @staticmethod
    def _parse_json(content: str) -> dict:
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                raise ValueError("模型未返回 JSON")
            return json.loads(match.group(0))

    def _dashscope_call(self, messages: list[dict]) -> str:
        response = Generation.call(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            model=config.chat_model_name,
            messages=messages,
            result_format="message",
        )
        if response.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"DashScope 调用失败：{response.code} - {response.message}"
            )
        self._record_usage(getattr(response, "usage", None))
        return str(response.output.choices[0].message.content or "")

    def _dashscope_stream(
        self,
        messages: list[dict],
        on_token: Callable[[str], None],
    ) -> str:
        chunks = []
        responses = Generation.call(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            model=config.chat_model_name,
            messages=messages,
            result_format="message",
            stream=True,
            incremental_output=True,
        )
        final_usage = None
        for response in responses:
            if response.status_code != HTTPStatus.OK:
                raise RuntimeError(
                    f"DashScope 调用失败：{response.code} - {response.message}"
                )
            final_usage = getattr(response, "usage", final_usage)
            token = str(response.output.choices[0].message.content or "")
            if token:
                chunks.append(token)
                on_token(token)
        if not chunks:
            raise RuntimeError("DashScope 流式调用未返回内容")
        self._record_usage(final_usage)
        return "".join(chunks)
