"""Enterprise AI Agent 的集中配置。"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = "Enterprise AI Agent"
APP_VERSION = "1.0.1"

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

md5_path = str(DATA_DIR / "document_hashes.txt")
document_registry_path = str(DATA_DIR / "documents.json")
collection_name = "rag"
persist_directory = str(DATA_DIR / "chroma_db")
chat_history_directory = str(DATA_DIR / "chat_history")
enterprise_database_path = str(DATA_DIR / "enterprise.db")
workflow_checkpoint_path = str(DATA_DIR / "workflow_checkpoints.db")
observability_database_path = str(DATA_DIR / "observability.db")

chunk_size = 1000
chunk_overlap = 100
separators = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
max_spliter_char_number = 1000
retriever_k = 4
# 先扩大候选范围，再按问题中的专有名词、数字和规则词进行本地重排。
retriever_candidate_k = 10
score_threshold = 0.1
# DashScope text-embedding-v4 在当前接口中单批最多接收 10 条文本。
embedding_batch_size = 10
max_document_context_chars = 30000

embedding_model_name = "text-embedding-v4"
chat_model_name = "qwen3-max"

session_config = {"configurable": {"session_id": "user_default"}}


def require_dashscope_api_key() -> str:
    """在调用模型前给出可理解的配置错误，而不是底层 SDK 异常。"""
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，请检查项目根目录的 .env 文件")
    return api_key
