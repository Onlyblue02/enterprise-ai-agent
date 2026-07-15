"""企业智能知识助手的 RAG 问答服务。"""

import re

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.runnables.history import RunnableWithMessageHistory

import config_data as config
from file_history_store import get_history
from vector_stores import VectorStoreService


class RagService:
    def __init__(self):
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.embedding_model_name)
        )
        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Enterprise AI Agent，一名严谨的企业知识库问答助手。"
                    "请优先依据用户上传的参考资料回答，并结合对话历史理解上下文。"
                    "严禁编造资料中不存在的事实；资料不足时必须明确说明不知道。"
                    "回答应准确、清晰、结构化，并在结尾列出依据的资料来源。\n\n"
                    "参考资料：\n{context}",
                ),
                MessagesPlaceholder("history"),
                ("user", "{input}"),
            ]
        )
        self.chat_model = ChatTongyi(model=config.chat_model_name)
        self.chain = self._build_chain()

    def retrieve_source_docs(self, question: str, where: dict | None = None):
        candidates = self.vector_service.search_with_scores(
            question,
            where=where,
            k=config.retriever_candidate_k,
        )
        candidates = [
            doc
            for doc in candidates
            if float(doc.metadata.get("similarity_score", 0.0))
            >= config.score_threshold
        ]
        return self._rerank_documents(question, candidates)[: config.retriever_k]

    @staticmethod
    def _rerank_documents(question: str, docs: list[Document]) -> list[Document]:
        """用问题中的明确词语辅助向量分数，优先保留直接规则证据。"""
        quoted_terms = re.findall(r"[“\"']([^”\"']{2,20})[”\"']", question)
        latin_terms = re.findall(r"[A-Za-z][A-Za-z0-9_.@-]{1,30}", question)
        numbers = re.findall(r"\d+(?:\.\d+)?", question)
        rule_terms = [
            term
            for term in (
                "投单", "报销", "密码", "住宿", "发票", "期限", "多少", "几日",
                "至少", "超过", "之前", "之后", "事前", "事后", "是否", "顺序",
                "用户名", "入口", "挂失", "消费记录", "图书馆", "无线网络",
            )
            if term in question
        ]
        terms = list(dict.fromkeys(quoted_terms + latin_terms + numbers + rule_terms))

        def rank(doc: Document) -> float:
            text = doc.page_content.lower()
            lexical = sum(
                (3.0 if term in quoted_terms or term in numbers else 1.5)
                for term in terms
                if term.lower() in text
            )
            similarity = float(doc.metadata.get("similarity_score", 0.0))
            doc.metadata["rerank_score"] = round(similarity + lexical, 4)
            return similarity + lexical

        return sorted(docs, key=rank, reverse=True)

    #再一次检索
    def rewrite_query(self, question: str, recent_messages: list[dict]) -> str:
        """结合最近对话，把依赖上下文的问题改写为可独立检索的查询。"""
        if not recent_messages:
            return question
        history = "\n".join(
            f"{item.get('role', 'user')}：{item.get('content', '')}"
            for item in recent_messages[-6:]      #将对话内容整理成文本，然后取最近的6条
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 RAG 查询改写器。请结合对话历史，把用户最新问题改写成一条"
                    "语义完整、可独立用于向量检索的中文查询。不得回答问题，不得添加资料中"
                    "不存在的事实，只输出改写后的查询文本。",
                ),
                ("user", "对话历史：\n{history}\n\n最新问题：{question}"),
            ]
        )
        try:
            result = (prompt | self.chat_model | StrOutputParser()).invoke(
                {"history": history, "question": question}
            )
            return result.strip() or question
        except Exception:
            return question

    def stream_knowledge_answer(
        self,
        question: str,
        docs: list[Document],
        recent_messages: list[dict],
    ):
        """基于已过滤和排序的片段生成带编号引用的流式回答。"""  
        context_parts = []
        for index, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "未知来源")
            chunk_index = doc.metadata.get("chunk_index")
            position = f"片段 {chunk_index + 1}" if isinstance(chunk_index, int) else "历史片段"
            context_parts.append(
                f"[{index}] 来源：{source}；位置：{position}\n{doc.page_content}"
            )
        context = "\n\n".join(context_parts)
        history = "\n".join(
            f"{item.get('role', 'user')}：{item.get('content', '')}"
            for item in recent_messages[-6:]
        ) or "无"
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是严谨的企业知识库问答助手。只能依据参考资料中的直接证据回答。\n"
                    "回答规则：\n"
                    "1. 先直接回答当前问题，只提供必要信息，不扩展通用知识或相邻制度。\n"
                    "2. 问题询问数字、期限、金额、顺序或条件时，必须引用明确包含该规则的片段；"
                    "不要把‘建议立即办理’当成‘最晚期限’。\n"
                    "3. 每个关键结论后标注对应引用编号，例如 [1] 或 [1][2]。\n"
                    "4. 多个片段存在不同数字或相互冲突时，逐项说明冲突及引用，不得自行猜测哪个正确。\n"
                    "5. 没有直接证据时，仅回答‘当前所选文档未提供充分信息’，并说明缺少什么；"
                    "禁止用常识补充税号、金额、流程、条件或其他细节。\n"
                    "6. 不得把其他机构、其他业务或其他类型发票的规则拼入答案。\n\n"
                    "参考资料：\n{context}",
                ),
                ("user", "最近对话：\n{history}\n\n当前问题：{question}"),
            ]
        )
        return (prompt | self.chat_model | StrOutputParser()).stream(
            {"context": context, "history": history, "question": question}
        )

    def get_source_documents(self, source: str) -> list[Document]:
        return self.vector_service.get_documents_by_source(source)

    @staticmethod
    def format_tool_documents(docs: list[Document]) -> str:
        """将召回片段转换为 Agent 工具可消费的带引用文本。"""
        parts = []
        for index, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "未知来源")
            category = doc.metadata.get("category", "未分类")
            chunk_index = doc.metadata.get("chunk_index")
            position = (
                f"片段 {chunk_index + 1}"
                if isinstance(chunk_index, int)
                else "未知位置"
            )
            score = doc.metadata.get("similarity_score", "-")
            parts.append(
                f"[{index}] 来源：{source}；类别：{category}；位置：{position}；"
                f"相似度：{score}\n{doc.page_content}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _format_full_documents(docs: list[Document]) -> str:
        text = "\n\n".join(
            f"片段 {index + 1}：\n{doc.page_content}" for index, doc in enumerate(docs)
        )
        if len(text) > config.max_document_context_chars:
            text = text[: config.max_document_context_chars]
            text += "\n\n[文档过长，以上为当前上下文允许范围内的内容]"
        return text

    def stream_document_summary(self, question: str, source: str):
        docs = self.get_source_documents(source)
        context = self._format_full_documents(docs)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是严谨的文档总结助手。只能依据给定文档总结，不得补充原文没有的事实。"
                    "请输出：核心主题、关键要点、重要结论和资料中未明确的信息。\n\n"
                    "文档名称：{source}\n文档内容：\n{context}",
                ),
                ("user", "用户要求：{question}"),
            ]
        )
        chain = prompt | self.chat_model | StrOutputParser()
        return chain.stream({"source": source, "context": context, "question": question})

    def stream_document_comparison(self, question: str, source_a: str, source_b: str):
        context_a = self._format_full_documents(self.get_source_documents(source_a))
        context_b = self._format_full_documents(self.get_source_documents(source_b))
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是严谨的多文档对比助手。只能依据给定文档进行比较，不得编造。"
                    "请先概括两份文档，再用 Markdown 表格按相同维度比较，最后总结共同点、差异和资料缺口。\n\n"
                    "文档 A：{source_a}\n{context_a}\n\n文档 B：{source_b}\n{context_b}",
                ),
                ("user", "用户要求：{question}"),
            ]
        )
        chain = prompt | self.chat_model | StrOutputParser()
        return chain.stream(
            {
                "source_a": source_a,
                "source_b": source_b,
                "context_a": context_a,
                "context_b": context_b,
                "question": question,
            }
        )

    def _build_chain(self):
        retriever = self.vector_service.get_retriever()

        def format_documents(docs: list[Document]) -> str:
            if not docs:
                return "没有检索到相关资料。"
            parts = []
            for index, doc in enumerate(docs, 1):
                source = doc.metadata.get("source", "未知来源")
                category = doc.metadata.get("category", "未分类")
                parts.append(f"[{index}] 来源：{source}；类别：{category}\n{doc.page_content}")
            return "\n\n".join(parts)

        def query(value: dict) -> str:
            return value["input"]

        def prompt_values(value: dict) -> dict:
            return {
                "input": value["input"]["input"],
                "context": value["context"],
                "history": value["input"]["history"],
            }

        chain = (
            {
                "input": RunnablePassthrough(),
                "context": RunnableLambda(query) | retriever | format_documents,
            }
            | RunnableLambda(prompt_values)
            | self.prompt_template
            | self.chat_model
            | StrOutputParser()
        )
        return RunnableWithMessageHistory(
            chain,
            get_history,
            input_messages_key="input",
            history_messages_key="history",
        )
