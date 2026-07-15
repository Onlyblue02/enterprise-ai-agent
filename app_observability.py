"""Agent 与工作流的运行监控页面。"""

import json

import streamlit as st

from observability import ObservabilityService


STATUS_LABELS = {
    "running": "运行中",
    "waiting_approval": "待审批",
    "completed": "已完成",
    "failed": "失败",
}


def render_observability_page() -> None:
    st.title("运行监控")
    st.caption("查看 Agent 与工作流的状态、耗时、Token 用量和执行事件。")

    service = ObservabilityService()
    runs = service.list_runs(limit=50)

    clear_message = st.session_state.pop("observability_clear_message", None)
    if clear_message:
        st.success(clear_message)

    if not runs:
        st.info("暂无运行记录。请先执行一次知识问答或企业工作流。")
        return

    with st.expander("记录管理"):
        st.warning("此操作将永久删除全部运行记录及执行明细，且无法恢复。")
        confirmed = st.checkbox(
            "我确认清空全部运行监控记录",
            key="confirm_clear_observability",
        )
        if st.button(
            "清空全部记录",
            disabled=not confirmed,
            type="primary",
            use_container_width=False,
        ):
            run_count, event_count = service.clear_all()
            st.session_state["observability_clear_message"] = (
                f"已清空 {run_count} 条运行记录和 {event_count} 条执行明细。"
            )
            st.rerun()

    completed = sum(run["status"] == "completed" for run in runs)
    failed = sum(run["status"] == "failed" for run in runs)
    total_tokens = sum(run["input_tokens"] + run["output_tokens"] for run in runs)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("最近运行", len(runs))
    col2.metric("已完成", completed)
    col3.metric("失败", failed)
    col4.metric("Token 用量", total_tokens)

    table = []
    for run in runs:
        table.append(
            {
                "运行 ID": run["run_id"],
                "类型": "Agent" if run["run_type"] == "agent" else "工作流",
                "状态": STATUS_LABELS.get(run["status"], run["status"]),
                "开始时间": run["started_at"],
                "耗时(ms)": round(run["duration_ms"] or 0, 1),
                "输入 Token": run["input_tokens"],
                "输出 Token": run["output_tokens"],
                "错误": run["error"],
            }
        )
    st.dataframe(table, use_container_width=True, hide_index=True)

    labels = {
        f"{run['started_at']} · {STATUS_LABELS.get(run['status'], run['status'])} · {run['title']}": run["run_id"]
        for run in runs
    }
    selected_label = st.selectbox("查看执行明细", labels.keys())
    events = service.get_events(labels[selected_label])
    if not events:
        st.caption("该次运行没有工具或工作流节点事件。")
        return

    event_table = []
    for event in events:
        details = json.loads(event["details"] or "{}")
        event_table.append(
            {
                "时间": event["created_at"],
                "事件类型": event["event_type"],
                "名称": event["name"],
                "状态": event["status"],
                "耗时(ms)": round(event["duration_ms"] or 0, 1),
                "附加信息": details,
            }
        )
    st.dataframe(event_table, use_container_width=True, hide_index=True)
