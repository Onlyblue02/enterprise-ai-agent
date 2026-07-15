"""文档切分、去重并写入企业知识库。"""

import hashlib
import json
import os
from datetime import datetime

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config_data as config


def check_md5(md5_str: str) -> bool:
    os.makedirs(os.path.dirname(config.md5_path), exist_ok=True)
    if not os.path.exists(config.md5_path):
        open(config.md5_path, "w", encoding="utf-8").close()
        return False
    with open(config.md5_path, "r", encoding="utf-8") as file:
        return md5_str in {line.strip() for line in file if line.strip()}


def save_md5(md5_str: str) -> None:
    with open(config.md5_path, "a", encoding="utf-8") as file:
        file.write(md5_str + "\n")


def remove_md5(md5_str: str) -> None:
    if not os.path.exists(config.md5_path):
        return
    with open(config.md5_path, "r", encoding="utf-8") as file:
        hashes = [line.strip() for line in file if line.strip() and line.strip() != md5_str]
    with open(config.md5_path, "w", encoding="utf-8") as file:
        file.write("\n".join(hashes) + ("\n" if hashes else ""))


def load_registry() -> dict:
    if not os.path.exists(config.document_registry_path):
        return {}
    try:
        with open(config.document_registry_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_registry(registry: dict) -> None:
    os.makedirs(os.path.dirname(config.document_registry_path), exist_ok=True)
    temp_path = config.document_registry_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(registry, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, config.document_registry_path)


def get_string_md5(input_str: str, encoding: str = "utf-8") -> str:
    return hashlib.md5(input_str.encode(encoding)).hexdigest()


class KnowledgeBaseService:
    def __init__(self):
        os.makedirs(config.persist_directory, exist_ok=True)
        self.chroma = Chroma(                                    #负责保存文本片段、向量、文件名、类别等元数据
            collection_name=config.collection_name,
            embedding_function=DashScopeEmbeddings(model=config.embedding_model_name),#使用什么模型把文本转成向量
            persist_directory=config.persist_directory,        #向量数据库保存到哪个本地目录
        )
        self.splitter = RecursiveCharacterTextSplitter(   #长文本切分
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=config.separators,
            length_function=len,
        )

    def upload_by_str(self, data: str, filename: str, category: str = "其他") -> str:
        data = data.strip()
        if not data:
            raise ValueError("文档内容为空")
            #将文档以哈希值的形式写入
        md5_hex = get_string_md5(f"{category}:{data}")
        if check_md5(md5_hex):
            existing = self.chroma.get(
                where={"document_md5": md5_hex},
                include=[],
            )
            if existing.get("ids"):
                return "内容已存在，无需重复入库。"

            # MD5 文件可能在向量库被清空或更换后留下孤立记录。
            remove_md5(md5_hex)
            registry = load_registry()
            stale_names = [
                name
                for name, item in registry.items()
                if item.get("md5") == md5_hex
            ]
            for name in stale_names:
                registry.pop(name, None)
            if stale_names:
                save_registry(registry)

        chunks = self.splitter.split_text(data) if len(data) > config.max_spliter_char_number else [data]

        metadata = {                       #用于记录文档的基本信息
            "source": filename,
            "category": category,
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operator": "user",
        }
        # DashScope Embedding 接口单次最多接收 10 条文本，因此分批入库。
        # 只有所有批次成功后才记录 MD5，防止中途失败后无法重新上传。
        batch_size = config.embedding_batch_size
        inserted_ids = []
        try:
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                batch_ids = [f"{md5_hex}-{index}" for index in range(start, start + len(batch))]
                batch_metadatas = []
                for index in range(start, start + len(batch)):
                    chunk_metadata = metadata.copy()
                    chunk_metadata["chunk_index"] = index
                    chunk_metadata["document_md5"] = md5_hex
                    batch_metadatas.append(chunk_metadata)
                self.chroma.add_texts(
                    texts=batch,
                    metadatas=batch_metadatas,
                    ids=batch_ids,
                )
                inserted_ids.extend(batch_ids)
        except Exception:
            # 分批入库中途失败时回滚已写入片段，保证用户可以安全重试。
            if inserted_ids:
                self.chroma.delete(ids=inserted_ids)
            raise
        save_md5(md5_hex)
        registry = load_registry()
        registry[filename] = {
            "filename": filename,
            "category": category,
            "md5": md5_hex,
            "create_time": metadata["create_time"],
            "chunk_count": len(chunks),
        }
        save_registry(registry)
        return f"上传成功：已将 {len(chunks)} 个文本片段写入知识库。"

    def list_documents(self) -> list[dict]:
        """从向量库聚合文档，兼容注册表创建前上传的历史数据。"""
        result = self.chroma.get(include=["metadatas"])
        documents: dict[str, dict] = {}
        for metadata in result.get("metadatas") or []:
            metadata = metadata or {}
            filename = metadata.get("source")
            # 早期示例向量没有来源，无法按文件管理，不展示为可选文档。
            if not filename:
                continue
            item = documents.setdefault(
                filename,
                {
                    "filename": filename,
                    "category": metadata.get("category", "未分类"),
                    "create_time": metadata.get("create_time", "未知"),
                    "chunk_count": 0,
                },
            )
            item["chunk_count"] += 1
        return sorted(documents.values(), key=lambda item: item["create_time"], reverse=True)

    def delete_document(self, filename: str) -> int:
        """删除指定来源的全部向量，并清理该文档的去重记录。"""
        result = self.chroma.get(where={"source": filename}, include=[])
        ids = result.get("ids") or []
        if ids:
            self.chroma.delete(ids=ids)

        registry = load_registry()
        record = registry.pop(filename, None)  #移除对应数据
        if record:
            remove_md5(record.get("md5", ""))  #同时删除md5文件
            save_registry(registry)
        return len(ids)
