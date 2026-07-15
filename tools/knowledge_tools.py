"""把现有知识库能力包装为 LangChain 标准工具。"""

import json

from langchain_core.tools import tool

from knowledge_base import KnowledgeBaseService
from rag import RagService


def build_knowledge_tools(
    rag_service: RagService,
    knowledge_base: KnowledgeBaseService,
) -> list:
    """创建绑定当前服务实例的知识库工具集合。"""

    @tool("list_documents")
    def list_documents() -> str:
        """列出企业知识库中所有可用文档及其类别；不知道文件名时应先调用本工具。"""
        documents = knowledge_base.list_documents()
        if not documents:
            return "知识库中暂无文档。"
        return json.dumps(documents, ensure_ascii=False, indent=2)

    @tool("search_knowledge_base")
    def search_knowledge_base(
        query: str,
        category: str = "",
        source: str = "",
    ) -> str:
        """从企业知识库检索制度、产品、技术或业务资料。

        Args:
            query: 语义完整、可以独立检索的问题。
            category: 可选的资料类别；不限定时传空字符串。
            source: 可选的准确文件名；不限定时传空字符串。
        """
        where = None
        if source:
            where = {"source": source}
        elif category:
            where = {"category": category}

        documents = rag_service.retrieve_source_docs(query, where=where)
        if not documents:
            return "没有检索到足够相关的知识库资料。"
        return rag_service.format_tool_documents(documents)

    @tool("summarize_document")
    def summarize_document(source: str, request: str = "总结文档的核心内容") -> str:
        """总结知识库中的一份指定文档。

        Args:
            source: 知识库中的准确文件名；不确定时先调用 list_documents。
            request: 用户对总结范围、格式或重点的要求。
        """
        documents = rag_service.get_source_documents(source)
        if not documents:
            return f"未找到文档：{source}。请先调用 list_documents 确认文件名。"
        return "".join(rag_service.stream_document_summary(request, source))

    @tool("compare_documents")
    def compare_documents(
        source_a: str,
        source_b: str,
        request: str = "比较两份文档的共同点和差异",
    ) -> str:
        """比较知识库中的两份文档。

        Args:
            source_a: 第一份文档的准确文件名。
            source_b: 第二份文档的准确文件名。
            request: 用户要求的比较维度或输出格式。
        """
        if source_a == source_b:
            return "两份文档不能相同。"
        missing = [
            source
            for source in (source_a, source_b)
            if not rag_service.get_source_documents(source)
        ]
        if missing:
            return "未找到文档：" + "、".join(missing) + "。请先调用 list_documents。"
        return "".join(
            rag_service.stream_document_comparison(request, source_a, source_b)
        )

    return [
        list_documents,
        search_knowledge_base,
        summarize_document,
        compare_documents,
    ]
