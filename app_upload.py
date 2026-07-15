"""知识库资料管理页面。"""

import streamlit as st

import config_data as config
from document_parser import extract_text
from knowledge_base import KnowledgeBaseService


def render_upload_page(service: KnowledgeBaseService) -> None:
    """渲染文档上传、统计和删除页面。"""
    st.header("📁 知识库资料中心")
    st.caption("资料只会写入本地 Chroma 向量库。请勿上传不希望由模型处理的敏感信息。")

    category = st.selectbox(
        "资料类别", ["公司制度", "产品文档", "技术资料", "业务资料", "项目资料", "其他"]
    )
    uploaded_file = st.file_uploader(
        "上传 TXT、Markdown、PDF 或 DOCX", type=["txt", "md", "pdf", "docx"]
    )

    if uploaded_file and st.button("解析并写入知识库", type="primary"):
        try:
            with st.spinner("正在解析、切分并向量化……"):
                config.require_dashscope_api_key()
                text = extract_text(uploaded_file)
                result = service.upload_by_str(text, uploaded_file.name, category)
            st.success(result)
            with st.expander("查看解析结果预览"):
                st.text(text[:2000])
        except Exception as exc:
            st.error(f"处理失败：{type(exc).__name__}: {str(exc) or '未提供错误信息'}")

    st.divider()
    st.subheader("已入库文档")
    try:
        documents = service.list_documents()
        total_chunks = sum(item["chunk_count"] for item in documents)
        metric1, metric2 = st.columns(2)
        metric1.metric("文档数量", len(documents))
        metric2.metric("文本片段", total_chunks)

        if not documents:
            st.info("知识库中还没有文档。")
            return

        st.dataframe(
            documents,
            column_config={
                "filename": "文件名",
                "category": "类别",
                "create_time": "上传时间",
                "chunk_count": "片段数",
            },
            hide_index=True,
            use_container_width=True,
        )
        selected = st.selectbox(
            "选择要删除的文档",
            [item["filename"] for item in documents],
            index=None,
            placeholder="请选择文档",
        )
        confirm = st.checkbox(
            "我确认删除该文档及其全部向量片段", disabled=not selected
        )
        if st.button("删除文档", disabled=not (selected and confirm)):
            deleted_count = service.delete_document(selected)
            st.success(f"已删除 {selected}，共清理 {deleted_count} 个向量片段。")
            st.rerun()
    except Exception as exc:
        st.error(
            f"读取文档列表失败：{type(exc).__name__}: "
            f"{str(exc) or '未提供错误信息'}"
        )


if __name__ == "__main__":
    st.set_page_config(page_title="知识库资料中心", page_icon="📁", layout="wide")
    render_upload_page(KnowledgeBaseService())
