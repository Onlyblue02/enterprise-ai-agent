"""Enterprise AI Agent 的统一 Streamlit 入口。"""

from pathlib import Path
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from app_chat import render_chat_page
from app_observability import render_observability_page
from app_upload import render_upload_page
from app_workflow import render_workflow_page
import config_data as config
from knowledge_base import KnowledgeBaseService
from ui_theme import apply_global_styles


st.set_page_config(page_title="Enterprise AI Agent", page_icon="🤖", layout="wide")
apply_global_styles()


def init_state() -> None:
    """初始化当前浏览器会话所需的状态。"""
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("session_id", f"user_{uuid4().hex[:10]}")


def get_knowledge_base() -> KnowledgeBaseService:
    """在一个 Streamlit 会话中复用知识库服务。"""
    if "knowledge_base" not in st.session_state:
        st.session_state["knowledge_base"] = KnowledgeBaseService()
    return st.session_state["knowledge_base"]


def render_home() -> None:
    st.markdown(
        """
        <div class="agent-hero">
            <div class="hero-badge">ENTERPRISE INTELLIGENCE PLATFORM</div>
            <h1>企业智能知识助手</h1>
            <p>连接企业知识、业务数据与自动化工作流，让每一次回答有据可查，让每一项任务清晰可控。</p>
            <div class="hero-tags"><span>RAG 知识检索</span><span>Agent 工具调用</span><span>LangGraph 工作流</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("Agent 工具", "8 个")
    col2.metric("文档格式", "4 种")
    col3.metric("自动化测试", "24 项")

    st.subheader("核心能力")
    card1, card2, card3 = st.columns(3)
    card1.markdown(
        '<div class="capability-card"><div class="card-icon">01</div><h3>企业知识检索</h3><p>上传企业资料并建立本地向量库，提供带来源引用的可靠问答。</p></div>',
        unsafe_allow_html=True,
    )
    card2.markdown(
        '<div class="capability-card"><div class="card-icon">02</div><h3>Agent 工具调用</h3><p>由 Qwen 自主选择知识库、业务数据库和计算工具完成任务。</p></div>',
        unsafe_allow_html=True,
    )
    card3.markdown(
        '<div class="capability-card"><div class="card-icon">03</div><h3>企业工作流</h3><p>通过 LangGraph 完成报告规划、取数、生成、审核和人工审批。</p></div>',
        unsafe_allow_html=True,
    )

    st.caption("Python · Streamlit · LangChain · LangGraph · Chroma · DashScope / Qwen")


init_state()

with st.sidebar:
    st.markdown(
        '<div class="sidebar-brand"><div class="brand-mark">EA</div><div><strong>Enterprise AI Agent</strong><span>企业智能知识助手</span></div></div>',
        unsafe_allow_html=True,
    )
    st.caption(f"Demo v{config.APP_VERSION}")
    page = st.radio("导航", ["首页", "资料中心", "知识问答", "企业工作流", "运行监控"])
    st.divider()
    if st.button("清空当前对话"):
        st.session_state["messages"] = []
        st.session_state["session_id"] = f"user_{uuid4().hex[:10]}"
        st.rerun()

if page == "首页":
    render_home()
elif page == "资料中心":
    render_upload_page(get_knowledge_base())
elif page == "知识问答":
    render_chat_page(get_knowledge_base())
elif page == "企业工作流":
    render_workflow_page()
else:
    render_observability_page()
