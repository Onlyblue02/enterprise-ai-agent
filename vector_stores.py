"""Chroma 向量库的检索和按来源读取封装。"""

import warnings

from langchain_chroma import Chroma
from langchain_core.documents import Document

import config_data as config


class VectorStoreService:
    def __init__(self, embedding):
        self.embedding = embedding
        self.vector_store = Chroma(
            collection_name=config.collection_name,
            embedding_function=self.embedding,
            persist_directory=config.persist_directory,
        )

    def get_retriever(self):
        """返回 Top-K 相似度结果，由提示词判断资料是否足以回答。"""
        return self.vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": config.retriever_k},
        )

    def search_with_scores(
        self,
        query: str,
        where: dict | None = None,
        k: int | None = None,
    ) -> list[Document]:
        """返回 Top-K 文档，并将相关度分数附加到元数据供界面展示。"""
        # 部分 Chroma 距离函数会产生小于 0 或大于 1 的换算分数，先抑制底层
        # 警告，再统一裁剪到展示和过滤所需的 0~1 范围。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            results = self.vector_store.similarity_search_with_relevance_scores(
                query, #问题
                k=k or config.retriever_k, #向量化
                filter=where,    #范围
            )
        docs = []
        #将分数也加入元数据
        for doc, score in results:
            doc.metadata = dict(doc.metadata or {})
            normalized_score = max(0.0, min(1.0, float(score)))
            doc.metadata["similarity_score"] = round(normalized_score, 4)
            docs.append(doc)
        return docs

    def get_documents_by_source(self, source: str) -> list[Document]:
        """按来源读取文档全部片段，供总结和对比模式使用。"""
        result = self.vector_store.get(
            where={"source": source},
            include=["documents", "metadatas"],
        )
        documents = []
        texts = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        for text, metadata in zip(texts, metadatas):
            documents.append(Document(page_content=text, metadata=metadata or {}))
        return sorted(documents, key=lambda doc: doc.metadata.get("chunk_index", 0))
