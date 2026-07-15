"""可观测性 SQLite 存储的离线测试。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from observability import ObservabilityService


class ObservabilityServiceTest(unittest.TestCase):
    def test_run_event_usage_and_finish(self):
        with TemporaryDirectory() as temp_dir:
            service = ObservabilityService(Path(temp_dir) / "observability.db")
            run_id = service.start_run("agent", "测试运行")
            service.log_event(
                run_id,
                "tool",
                "calculate",
                duration_ms=12.5,
                details={"operation": "percentage_change"},
            )
            service.add_usage(run_id, 100, 20)
            service.add_usage(run_id, 10, 5)
            service.finish_run(run_id, "completed")

            run = service.get_run(run_id)
            events = service.get_events(run_id)
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["input_tokens"], 110)
            self.assertEqual(run["output_tokens"], 25)
            self.assertEqual(events[0]["name"], "calculate")
            self.assertGreaterEqual(run["duration_ms"], 0)
