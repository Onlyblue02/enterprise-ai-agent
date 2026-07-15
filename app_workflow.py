"""LangGraph 企业报告工作流与人工审批页面。"""

from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from time import perf_counter
from typing import Callable

import streamlit as st

import config_data as config
from database_service import DatabaseService
from observability import ObservabilityService
from rag import RagService
from report_workflow import EnterpriseReportWorkflow, ReportWorkflowResult


WORKFLOW_KEY = "enterprise_report_workflow"
RESULT_KEY = "enterprise_report_result"


def render_workflow_page() -> None:
    st.header("🧭 企业报告工作流")
    st.caption("任务规划、知识检索、业务取数、报告审核完成后，将暂停等待人工审批。")
    observability = ObservabilityService()

    request = st.text_area(
        "报告任务",
        value=(
            "结合知识库资料与2026年上半年各区域销售数据，生成经营分析报告，"
            "说明关键发现、风险和改进建议。"
        ),
        height=120,
    )
    start_clicked = st.button(
        "生成待审批报告",
        type="primary",
        disabled=not request.strip(),
    )
    if start_clicked:
        started = perf_counter()
        run_id = None
        try:
            config.require_dashscope_api_key()
            run_id = observability.start_run("workflow", "企业经营分析报告")
            stream_placeholder = st.empty()
            with st.status("正在启动企业工作流……", expanded=True) as status:
                previous_workflow = st.session_state.get(WORKFLOW_KEY)
                if previous_workflow is not None:
                    previous_workflow.close()
                workflow = EnterpriseReportWorkflow(RagService(), DatabaseService())
                result = _run_with_streaming(
                    lambda on_progress, on_token: workflow.start(
                        request.strip(),
                        thread_id=run_id,
                        progress_callback=on_progress,
                        token_callback=on_token,
                    ),
                    status,
                    stream_placeholder,
                    observability,
                    run_id,
                )
                st.session_state[WORKFLOW_KEY] = workflow
                st.session_state[RESULT_KEY] = result
                observability.add_usage(
                    run_id, result.input_tokens, result.output_tokens
                )
                observability.set_status(run_id, "waiting_approval")
                status.update(label="待审批报告生成完成", state="complete")
            stream_placeholder.empty()
            st.success(f"待审批报告已生成，用时 {perf_counter() - started:.2f} 秒")
        except Exception as exc:
            error_message = _format_exception(exc)
            if run_id:
                observability.finish_run(run_id, "failed", error=error_message)
            st.error(f"工作流执行失败：{error_message}")
            return

    result: ReportWorkflowResult | None = st.session_state.get(RESULT_KEY)
    if result is None:
        st.info("填写任务并点击“生成待审批报告”开始执行。")
        _render_pending_workflows(observability)
        return

    st.divider()
    st.subheader(result.plan.get("title", "企业经营分析报告"))
    if result.awaiting_approval:
        st.warning("工作流已暂停：当前报告等待人工审批。")
        st.markdown(result.current_report)
        _render_approval_controls(result, observability)
    else:
        st.success("报告已通过人工审批并完成发布。")
        st.markdown(result.final_report)

    _render_workflow_details(result, observability)


def _render_approval_controls(
    result: ReportWorkflowResult,
    observability: ObservabilityService,
) -> None:
    st.markdown("### 人工审批")
    feedback_key = f"approval_feedback_{result.thread_id}"
    feedback = st.text_area(
        "修改意见（选择“要求修改”时必填）",
        key=feedback_key,
        placeholder="例如：补充华南区域风险分析，并将建议按优先级排序。",
    )
    approve_col, revise_col = st.columns(2)

    if approve_col.button("批准并完成报告", type="primary", use_container_width=True):
        _resume_workflow(result, "approved", "", observability)

    if revise_col.button("要求修改", use_container_width=True):
        if not feedback.strip():
            st.error("请先填写具体修改意见。")
        else:
            _resume_workflow(result, "revise", feedback, observability)


def _resume_workflow(
    result: ReportWorkflowResult,
    decision: str,
    feedback: str,
    observability: ObservabilityService,
) -> None:
    workflow: EnterpriseReportWorkflow | None = st.session_state.get(WORKFLOW_KEY)
    if workflow is None:
        st.error("工作流 checkpoint 已丢失，请重新生成报告。")
        return

    try:
        message = "正在完成审批……" if decision == "approved" else "正在按人工意见修订……"
        stream_placeholder = st.empty()
        with st.status(message, expanded=True) as status:
            updated_result = _run_with_streaming(
                lambda on_progress, on_token: workflow.resume(
                    result.thread_id,
                    decision,
                    feedback,
                    progress_callback=on_progress,
                    token_callback=on_token,
                ),
                status,
                stream_placeholder,
                observability,
                result.thread_id,
            )
            st.session_state[RESULT_KEY] = updated_result
            observability.add_usage(
                result.thread_id,
                updated_result.input_tokens,
                updated_result.output_tokens,
            )
            if updated_result.awaiting_approval:
                observability.set_status(result.thread_id, "waiting_approval")
            else:
                observability.finish_run(result.thread_id, "completed")
            status.update(label="审批处理完成", state="complete")
        stream_placeholder.empty()
        st.rerun()
    except Exception as exc:
        error_message = _format_exception(exc)
        observability.finish_run(result.thread_id, "failed", error=error_message)
        st.error(f"审批处理失败：{error_message}")


def _render_pending_workflows(observability: ObservabilityService) -> None:
    pending_runs = [
        item
        for item in observability.list_runs("workflow")
        if item["status"] == "waiting_approval"
    ]
    if not pending_runs:
        return

    st.subheader("待审批任务")
    selected_run = st.selectbox(
        "选择要恢复的任务",
        pending_runs,
        format_func=lambda item: f"{item['started_at']} · {item['title']} · {item['run_id'][:8]}",
    )
    if st.button("恢复待审批任务"):
        try:
            previous_workflow = st.session_state.get(WORKFLOW_KEY)
            if previous_workflow is not None:
                previous_workflow.close()
            workflow = EnterpriseReportWorkflow(RagService(), DatabaseService())
            result = workflow.load(selected_run["run_id"])
            st.session_state[WORKFLOW_KEY] = workflow
            st.session_state[RESULT_KEY] = result
            st.rerun()
        except Exception as exc:
            st.error(f"恢复失败：{_format_exception(exc)}")


def _format_exception(exc: Exception) -> str:
    """确保没有异常消息时仍展示异常类型，便于定位问题。"""
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _run_with_streaming(
    operation: Callable[[Callable, Callable], ReportWorkflowResult],
    status,
    stream_placeholder,
    observability: ObservabilityService,
    run_id: str,
) -> ReportWorkflowResult:
    """后台执行 LangGraph，并只在 Streamlit 主线程更新页面。"""
    events: Queue[tuple[str, str, str]] = Queue()
    streamed_content: dict[str, str] = {}

    def on_progress(node: str, message: str) -> None:
        events.put(("progress", node, message))

    def on_token(node: str, token: str) -> None:
        events.put(("token", node, token))

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(operation, on_progress, on_token)
        while not future.done() or not events.empty():
            try:
                event_type, node, content = events.get(timeout=0.05)
            except Empty:
                continue
            if event_type == "progress":
                status.write(f"`{node}` — {content}")
                observability.log_event(
                    run_id,
                    "node",
                    node,
                    "started",
                    details={"message": content},
                )
            else:
                streamed_content[node] = streamed_content.get(node, "") + content
                stream_placeholder.markdown(streamed_content[node] + "▌")
        return future.result()


def _render_workflow_details(
    result: ReportWorkflowResult,
    observability: ObservabilityService,
) -> None:
    with st.expander("查看工作流执行轨迹", expanded=True):
        for index, item in enumerate(result.trace, 1):
            st.write(f"{index}. `{item['node']}` — {item['detail']}")

    with st.expander("查看任务计划"):
        st.json(result.plan)

    with st.expander("查看模型质量审核"):
        st.write(result.review_feedback)

    run = observability.get_run(result.thread_id)
    events = observability.get_events(result.thread_id)
    if run:
        with st.expander("查看可观测性指标", expanded=True):
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("状态", run["status"])
            col2.metric("输入 Token", run["input_tokens"])
            col3.metric("输出 Token", run["output_tokens"])
            col4.metric("事件数", len(events))
            if run["duration_ms"]:
                st.write(f"**总耗时：** {run['duration_ms'] / 1000:.2f} 秒")
            if events:
                st.dataframe(events, hide_index=True, use_container_width=True)

    with st.expander("查看销售数据上下文"):
        st.code(result.sales_context, language="json")

    with st.expander("查看知识检索上下文"):
        st.text(result.knowledge_context)


if __name__ == "__main__":
    st.set_page_config(page_title="企业报告工作流", page_icon="🧭", layout="wide")
    render_workflow_page()
