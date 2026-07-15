"""知识库工具的离线单元测试，不访问 DashScope 或 Chroma。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from langchain_core.documents import Document

from database_service import DatabaseService
from enterprise_agent import EnterpriseAgent
from tools import build_business_tools, build_calculator_tools, build_knowledge_tools


class FakeKnowledgeBase:
    def list_documents(self):
        return [
            {
                "filename": "员工手册.pdf",
                "category": "公司制度",
                "create_time": "2026-07-13 10:00:00",
                "chunk_count": 2,
            }
        ]


class FakeRagService:
    def retrieve_source_docs(self, query, where=None):
        return [
            Document(
                page_content=f"检索内容：{query}",
                metadata={
                    "source": "员工手册.pdf",
                    "category": "公司制度",
                    "chunk_index": 0,
                    "similarity_score": 0.9,
                },
            )
        ]

    def get_source_documents(self, source):
        if source == "员工手册.pdf":
            return [Document(page_content="员工制度", metadata={"source": source})]
        return []

    @staticmethod
    def format_tool_documents(documents):
        return f"[1] 来源：员工手册.pdf\n{documents[0].page_content}"

    @staticmethod
    def stream_document_summary(request, source):
        yield f"{source}：{request}"

    @staticmethod
    def stream_document_comparison(request, source_a, source_b):
        yield f"{source_a} vs {source_b}：{request}"


class KnowledgeToolsTest(unittest.TestCase):
    def setUp(self):
        self.tools = {
            item.name: item
            for item in build_knowledge_tools(FakeRagService(), FakeKnowledgeBase())
        }

    def test_tool_names(self):
        self.assertEqual(
            set(self.tools),
            {
                "list_documents",
                "search_knowledge_base",
                "summarize_document",
                "compare_documents",
            },
        )

    def test_list_documents(self):
        result = self.tools["list_documents"].invoke({})
        self.assertIn("员工手册.pdf", result)

    def test_search_knowledge_base(self):
        result = self.tools["search_knowledge_base"].invoke(
            {"query": "报销期限", "category": "公司制度", "source": ""}
        )
        self.assertIn("来源：员工手册.pdf", result)
        self.assertIn("报销期限", result)

    def test_missing_summary_document(self):
        result = self.tools["summarize_document"].invoke(
            {"source": "不存在.pdf", "request": "总结"}
        )
        self.assertIn("未找到文档", result)


class BusinessToolsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        database = DatabaseService(Path(self.temp_dir.name) / "enterprise.db")
        self.tools = {item.name: item for item in build_business_tools(database)}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sales_summary(self):
        result = self.tools["query_sales_summary"].invoke(
            {"year": 2026, "start_month": 1, "end_month": 6}
        )
        self.assertIn("华东", result)
        self.assertIn("total_amount", result)

    def test_project_status(self):
        result = self.tools["query_project_status"].invoke(
            {"project_name": "企业知识助手"}
        )
        self.assertIn("开发中", result)
        self.assertIn("72.0", result)


class CalculatorToolsTest(unittest.TestCase):
    def setUp(self):
        self.calculate = build_calculator_tools()[0]

    def test_percentage_change(self):
        result = self.calculate.invoke(
            {"operation": "percentage_change", "a": 120, "b": 100}
        )
        self.assertIn("20.0000", result)

    def test_division_by_zero(self):
        result = self.calculate.invoke(
            {"operation": "divide", "a": 10, "b": 0}
        )
        self.assertIn("不能为 0", result)


class AgentEvidenceTest(unittest.TestCase):
    def test_extract_knowledge_evidence(self):
        result = (
            "[1] 来源：制度.pdf；类别：制度；位置：片段 1；相似度：0.9\n第一条\n\n"
            "[2] 来源：手册.md；类别：手册；位置：片段 3；相似度：0.8\n第二条"
        )
        evidence = EnterpriseAgent._extract_evidence(result)
        self.assertEqual(len(evidence), 2)
        self.assertIn("制度.pdf", evidence[0])
        self.assertIn("手册.md", evidence[1])

    def test_ignore_non_knowledge_result(self):
        self.assertEqual(EnterpriseAgent._extract_evidence("计算结果：20"), [])

    def test_agent_stream_emits_tokens_and_result(self):
        agent = EnterpriseAgent.__new__(EnterpriseAgent)
        agent.max_rounds = 2
        agent.tools_by_name = {}

        def fake_model_stream(messages, include_tools):
            yield {"type": "token", "content": "流式"}
            yield {"type": "token", "content": "回答"}
            return {"role": "assistant", "content": "流式回答", "tool_calls": []}

        agent._invoke_model_stream = fake_model_stream
        events = list(agent.stream("测试", []))
        tokens = "".join(
            event["content"] for event in events if event["type"] == "token"
        )
        done = [event for event in events if event["type"] == "done"]
        self.assertEqual(tokens, "流式回答")
        self.assertEqual(done[0]["result"].answer, "流式回答")


if __name__ == "__main__":
    unittest.main()
