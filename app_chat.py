"""知识库聊天与 Agent 执行过程页面。"""

from time import perf_counter
from uuid import uuid4

import streamlit as st

import config_data as config
from enterprise_agent import EnterpriseAgent
from knowledge_base import KnowledgeBaseService
from observability import ObservabilityService
from rag import RagService


def render_chat_page(knowledge_base: KnowledgeBaseService) -> None:
    """渲染聊天页面；业务能力继续由 RagService 提供。"""
    st.header("💬 知识库问答")
    st.caption("选择处理模式，或让 Agent 自动判断任务并调用对应能力。")

    documents = knowledge_base.list_documents()
    document_names = [item["filename"] for item in documents]
    mode = st.radio(
        "回答模式",
        ["Agent 自动选择", "知识库问答", "文档总结", "多文档对比"],
        horizontal=True,
        help="自动模式根据问题中的总结、比较等意图选择执行流程。",
    )

    search_where = None
    scope_mode = "由 Agent 决定"
    if mode == "知识库问答":
        st.markdown("**知识检索范围**")
        scope_mode = st.radio(
            "知识检索范围",
            ["全部资料", "按类别", "指定文档"],
            horizontal=True,
            label_visibility="collapsed",
        )
        if scope_mode == "按类别":
            categories = sorted({item["category"] for item in documents})
            selected_category = st.radio(
                "资料类别",
                categories,
                index=0 if categories else None,
                disabled=not categories,
            )
            if selected_category:
                search_where = {"category": selected_category}
        elif scope_mode == "指定文档":
            selected_search_document = st.radio(
                "检索文档",
                document_names,
                index=0 if document_names else None,
                disabled=not document_names,
            )
            if selected_search_document:
                search_where = {"source": selected_search_document}

    source_a = None
    source_b = None
    if mode in {"文档总结", "多文档对比"}:
        source_a = st.radio(
            "主要文档",
            document_names,
            index=0 if document_names else None,
            disabled=not document_names,
        )
    if mode == "多文档对比":
        second_options = [name for name in document_names if name != source_a]
        source_b_choice = st.radio(
            "对比文档（仅对比任务需要）",
            ["不选择"] + second_options,
            index=0,
            disabled=not second_options,
        )
        source_b = None if source_b_choice == "不选择" else source_b_choice

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("例如：总结这份文档，或比较两份文档的核心差异。")
    if not prompt:
        return

    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        config.require_dashscope_api_key()
        observability = ObservabilityService()
        observation_run_id = None
        with st.chat_message("assistant"):
            total_started = perf_counter()
            with st.spinner("正在分析任务并读取资料……"):
                rag = RagService()
                route_started = perf_counter()
                if mode == "Agent 自动选择":
                    selected_mode = "Agent 自动选择"
                    selected_tool = "由模型动态选择"
                    decision_reason = "Qwen 根据工具描述和对话上下文自主决策"
                    route_source = "tool_calling"
                    agent = EnterpriseAgent(rag, knowledge_base)
                else:
                    selected_mode = mode
                    selected_tool = {
                        "知识库问答": "search_knowledge_base",
                        "文档总结": "summarize_document",
                        "多文档对比": "compare_documents",
                    }[mode]
                    decision_reason = "用户手动指定执行模式"
                    route_source = "manual"
                route_elapsed = perf_counter() - route_started
                source_docs = []
                agent_result = None

            execution_started = perf_counter()
            recent_messages = st.session_state["messages"][:-1]

            if selected_mode == "Agent 自动选择":
                observation_run_id = observability.start_run(
                    "agent", "Agent 知识问答"
                )
                answer_placeholder = st.empty()
                streamed_answer = ""
                with st.status("Agent 正在分析并调用工具……", expanded=True) as status:
                    for event in agent.stream(prompt, recent_messages):
                        if event["type"] == "token":
                            streamed_answer += event["content"]
                            answer_placeholder.markdown(streamed_answer + "▌")
                        elif event["type"] == "tool_start":
                            status.write(
                                f"第 {event['round']} 轮：调用 `{event['name']}`"
                            )
                        elif event["type"] == "tool_end":
                            tool_status = "完成" if event["success"] else "失败"
                            status.write(f"`{event['name']}`：{tool_status}")
                            observability.log_event(
                                observation_run_id,
                                "tool",
                                event["name"],
                                "completed" if event["success"] else "failed",
                                event.get("duration_ms", 0),
                            )
                        elif event["type"] == "done":
                            agent_result = event["result"]
                    status.update(label="Agent 执行完成", state="complete")
                response = agent_result.answer
                observability.add_usage(
                    observation_run_id,
                    agent_result.input_tokens,
                    agent_result.output_tokens,
                )
                observability.finish_run(observation_run_id, "completed")
                answer_placeholder.markdown(response)
                selected_tool = (
                    " → ".join(item.name for item in agent_result.tool_executions)
                    or "未调用工具"
                )
            elif selected_mode == "文档总结":
                if not source_a:
                    response = "请先选择一份需要总结的文档。"
                    st.warning(response)
                else:
                    st.caption(f"使用文档：{source_a}")
                    response = st.write_stream(
                        rag.stream_document_summary(prompt, source_a)
                    )
            elif selected_mode == "多文档对比":
                if not source_a or not source_b:
                    response = "多文档对比需要选择两份不同的文档。"
                    st.warning(response)
                else:
                    st.caption(f"使用文档：{source_a} ↔ {source_b}")
                    response = st.write_stream(
                        rag.stream_document_comparison(prompt, source_a, source_b)
                    )
            else:
                rewritten_query = rag.rewrite_query(prompt, recent_messages)
                source_docs = rag.retrieve_source_docs(
                    rewritten_query, where=search_where
                )
                if not source_docs:
                    response = (
                        "当前知识库中没有检索到足够相关的资料。"
                        "请先上传文档，或换一种方式提问。"
                    )
                    st.warning(response)
                else:
                    response = st.write_stream(
                        rag.stream_knowledge_answer(
                            prompt, source_docs, recent_messages
                        )
                    )

            st.caption(f"执行模式：{selected_mode} · 工具：{selected_tool}")
            execution_elapsed = perf_counter() - execution_started
            total_elapsed = perf_counter() - total_started
            with st.expander("查看 Agent 执行过程"):
                st.write(f"**决策原因：** {decision_reason}")
                st.write(f"**路由方式：** {route_source}")
                st.write(f"**调用工具：** `{selected_tool}`")
                if agent_result is not None:
                    st.write(f"**Agent 轮数：** {agent_result.rounds}")
                    st.write(
                        f"**Token：** 输入 {agent_result.input_tokens} · "
                        f"输出 {agent_result.output_tokens}"
                    )
                    if not agent_result.tool_executions:
                        st.info("本轮模型直接回答，没有调用工具。")
                    for index, execution in enumerate(
                        agent_result.tool_executions, 1
                    ):
                        status = "成功" if execution.success else "失败"
                        st.markdown(
                            f"**步骤 {index}：`{execution.name}` · {status} · "
                            f"{execution.duration_ms:.0f} ms**"
                        )
                        st.json(execution.arguments)
                if source_a and selected_mode in {"文档总结", "多文档对比"}:
                    st.write(f"**主要文档：** {source_a}")
                if source_b and selected_mode == "多文档对比":
                    st.write(f"**对比文档：** {source_b}")
                st.write(f"**召回片段：** {len(source_docs)}")
                if selected_mode == "知识库问答":
                    st.write(f"**检索范围：** {scope_mode}")
                    st.write(f"**原始问题：** {prompt}")
                    st.write(f"**改写查询：** {rewritten_query}")
                st.write(f"**路由耗时：** {route_elapsed:.2f} 秒")
                st.write(f"**工具执行：** {execution_elapsed:.2f} 秒")
                st.write(f"**总耗时：** {total_elapsed:.2f} 秒")

            if agent_result is not None and agent_result.knowledge_evidence:
                with st.expander(
                    f"查看 {len(agent_result.knowledge_evidence)} 条知识库检索依据"
                ):
                    for evidence in agent_result.knowledge_evidence:
                        header, _, content = evidence.partition("\n")
                        st.markdown(f"**{header}**")
                        if content:
                            st.write(content[:1200])
                        st.divider()

            if source_docs:
                with st.expander(f"查看 {len(source_docs)} 条检索依据"):
                    for index, doc in enumerate(source_docs, 1):
                        source = doc.metadata.get("source", "未知来源")
                        category = doc.metadata.get("category", "未分类")
                        score = doc.metadata.get("similarity_score", "-")
                        chunk_index = doc.metadata.get("chunk_index")
                        position = (
                            f"片段 {chunk_index + 1}"
                            if isinstance(chunk_index, int)
                            else "历史片段"
                        )
                        st.markdown(
                            f"**[{index}] {source}** · {category} · "
                            f"{position} · 相似度 `{score}`"
                        )
                        st.write(doc.page_content[:800])
                        st.divider()

        st.session_state["messages"].append(
            {"role": "assistant", "content": response}
        )
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {str(exc) or '未提供错误信息'}"
        if "observability" in locals() and observation_run_id:
            observability.finish_run(
                observation_run_id, "failed", error=error_message
            )
        st.error(f"问答失败：{error_message}")


if __name__ == "__main__":
    st.set_page_config(page_title="知识库问答", page_icon="💬", layout="wide")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("session_id", f"user_{uuid4().hex[:10]}")
    render_chat_page(KnowledgeBaseService())
