"""LangGraph 报告工作流的离线分支测试。"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from langchain_core.documents import Document

from report_workflow import EnterpriseReportWorkflow


class FakeRagService:
    def retrieve_source_docs(self, query):
        return [
            Document(
                page_content="销售分析必须说明数据范围。",
                metadata={"source": "经营分析制度.md", "chunk_index": 0},
            )
        ]

    @staticmethod
    def format_tool_documents(documents):
        return f"[1] {documents[0].page_content}"


class FakeDatabaseService:
    def query_sales(self, year, start_month, end_month, region=""):
        return [{"year": year, "month": 1, "region": "华东", "amount": 100}]

    def sales_summary(self, year, start_month, end_month):
        return [{"region": "华东", "total_amount": 100}]


def fake_llm(needs_knowledge: bool, review_passed: bool):
    def call(messages):
        system = messages[0]["content"]
        if "报告规划器" in system:
            return json.dumps(
                {
                    "title": "测试经营报告",
                    "needs_knowledge": needs_knowledge,
                    "knowledge_query": "经营分析制度",
                    "year": 2026,
                    "start_month": 1,
                    "end_month": 6,
                    "region": "",
                    "focus": "销售表现",
                },
                ensure_ascii=False,
            )
        if "质量审核员" in system:
            return json.dumps(
                {"passed": review_passed, "feedback": "补充风险说明"},
                ensure_ascii=False,
            )
        if "报告编辑" in system:
            return "# 修订后的报告\n已补充风险说明。"
        return "# 报告初稿\n销售表现稳定。"

    return call


class ReportWorkflowTest(unittest.TestCase):
    def build_workflow(self, needs_knowledge=True, review_passed=False):
        return EnterpriseReportWorkflow(
            FakeRagService(),
            FakeDatabaseService(),
            llm_call=fake_llm(needs_knowledge, review_passed),
            checkpoint_path=":memory:",
        )

    def test_retrieve_and_revise_branch(self):
        workflow = self.build_workflow(True, False)
        result = workflow.start("生成报告")
        nodes = [item["node"] for item in result.trace]
        self.assertIn("retrieve_knowledge", nodes)
        self.assertIn("revise_report", nodes)
        self.assertTrue(result.awaiting_approval)
        self.assertEqual(result.final_report, "")
        self.assertIn("修订后的报告", result.current_report)

        approved = workflow.resume(result.thread_id, "approved")
        self.assertFalse(approved.awaiting_approval)
        self.assertIn("修订后的报告", approved.final_report)
        self.assertIn("human_approval", [item["node"] for item in approved.trace])

    def test_skip_knowledge_and_finalize_branch(self):
        workflow = self.build_workflow(False, True)
        result = workflow.start("仅根据销售数据生成报告")
        nodes = [item["node"] for item in result.trace]
        self.assertNotIn("retrieve_knowledge", nodes)
        self.assertNotIn("revise_report", nodes)
        self.assertTrue(result.awaiting_approval)
        self.assertIn("报告初稿", result.current_report)

        approved = workflow.resume(result.thread_id, "approved")
        self.assertIn("报告初稿", approved.final_report)

    def test_human_revision_requires_second_approval(self):
        workflow = self.build_workflow(False, True)
        first = workflow.start("生成报告")
        revised = workflow.resume(first.thread_id, "revise", "补充风险说明")
        revised_nodes = [item["node"] for item in revised.trace]
        self.assertTrue(revised.awaiting_approval)
        self.assertIn("apply_human_revision", revised_nodes)
        self.assertEqual(revised.final_report, "")

        approved = workflow.resume(revised.thread_id, "approved")
        self.assertFalse(approved.awaiting_approval)
        self.assertTrue(approved.final_report)

    def test_human_revision_requires_feedback(self):
        workflow = self.build_workflow(False, True)
        result = workflow.start("生成报告")
        with self.assertRaises(ValueError):
            workflow.resume(result.thread_id, "revise", "")

    def test_workflow_emits_progress_and_report_tokens(self):
        workflow = self.build_workflow(False, True)
        progress = []
        tokens = []
        workflow.start(
            "生成报告",
            progress_callback=lambda node, message: progress.append(node),
            token_callback=lambda node, token: tokens.append((node, token)),
        )
        self.assertIn("plan_task", progress)
        self.assertIn("write_draft", progress)
        self.assertTrue(any(node == "write_draft" for node, _ in tokens))

    def test_checkpoint_survives_workflow_recreation(self):
        with TemporaryDirectory() as temp_dir:
            checkpoint_path = str(Path(temp_dir) / "checkpoints.db")
            first_workflow = EnterpriseReportWorkflow(
                FakeRagService(),
                FakeDatabaseService(),
                llm_call=fake_llm(False, True),
                checkpoint_path=checkpoint_path,
            )
            pending = first_workflow.start("生成报告")
            self.assertTrue(pending.awaiting_approval)
            first_workflow.close()

            restored_workflow = EnterpriseReportWorkflow(
                FakeRagService(),
                FakeDatabaseService(),
                llm_call=fake_llm(False, True),
                checkpoint_path=checkpoint_path,
            )
            restored = restored_workflow.load(pending.thread_id)
            self.assertTrue(restored.awaiting_approval)
            approved = restored_workflow.resume(restored.thread_id, "approved")
            self.assertTrue(approved.final_report)
            restored_workflow.close()


if __name__ == "__main__":
    unittest.main()
