"""使用大模型完成单步工具路由，并提供确定性的降级策略。"""

import json
import re
from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate

#其中agent自动选择模式是先让agent判断选择哪个模式
TOOL_TO_MODE = {
    "search_knowledge_base": "知识库问答",
    "summarize_document": "文档总结",
    "compare_documents": "多文档对比",
}


@dataclass
class AgentDecision:
    tool: str
    mode: str
    reason: str
    required_documents: int
    route_source: str = "llm"


class AgentRouter:
    def __init__(self, chat_model):
        self.chat_model = chat_model
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是企业知识库 Agent 的任务路由器。你只负责选择一个工具，不回答用户问题。\n"
                    "可用工具：\n"
                    "1. search_knowledge_base：查询事实、解释资料内容或一般知识库问答，需要 0 份指定文档。\n"
                    "2. summarize_document：总结、归纳、提炼一份文档，需要 1 份文档。\n"
                    "3. compare_documents：比较两份文档的共同点、区别或优缺点，需要 2 份文档。\n"
                    "只输出合法 JSON，不要输出 Markdown："
                    '{{"tool":"工具名","reason":"简短中文原因","required_documents":数字}}',
                ),
                (
                    "user",
                    "用户问题：{question}\n当前可用文档：{documents}",
                ),
            ]
        )

    def decide(self, question: str, documents: list[str]) -> AgentDecision:
        message = (self.prompt | self.chat_model).invoke(
            {"question": question, "documents": documents or ["暂无文档"]}
        )
        content = message.content if hasattr(message, "content") else str(message)
        data = self._parse_json(content)
        tool = data.get("tool")
        if tool not in TOOL_TO_MODE:
            raise ValueError(f"Agent 返回了未知工具：{tool}")
        expected_count = {
            "search_knowledge_base": 0,
            "summarize_document": 1,
            "compare_documents": 2,
        }[tool]
        return AgentDecision(
            tool=tool,
            mode=TOOL_TO_MODE[tool],
            reason=str(data.get("reason") or "根据用户任务选择对应工具"),
            required_documents=expected_count,
        )

    @staticmethod
    def _parse_json(content: str) -> dict:
        content = content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                raise ValueError("Agent 未返回有效 JSON")
            return json.loads(match.group(0))

    @staticmethod
    def fallback(question: str) -> AgentDecision:  #备用方案，使用关键词进行判断
        normalized = question.lower()
        if any(word in normalized for word in ("对比", "比较", "区别", "差异", "不同")):
            return AgentDecision(
                "compare_documents", "多文档对比", "规则识别到对比意图", 2, "fallback"
            )
        if any(word in normalized for word in ("总结", "概括", "摘要", "归纳", "提炼")):
            return AgentDecision(
                "summarize_document", "文档总结", "规则识别到总结意图", 1, "fallback"
            )
        return AgentDecision(
            "search_knowledge_base", "知识库问答", "默认执行知识库检索", 0, "fallback"
        )
