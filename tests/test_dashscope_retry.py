import unittest
from unittest.mock import patch

from requests.exceptions import SSLError

from dashscope_retry import is_retryable_network_error, network_error_message
from enterprise_agent import EnterpriseAgent


class DashScopeRetryTest(unittest.TestCase):
    def test_ssl_error_is_retryable(self):
        error = SSLError("unexpected eof")
        self.assertTrue(is_retryable_network_error(error))
        self.assertIn("检查代理或网络", network_error_message(error))

    def test_non_network_error_is_not_retryable(self):
        self.assertFalse(is_retryable_network_error(ValueError("bad input")))

    @patch("enterprise_agent.wait_before_retry")
    @patch("enterprise_agent.Generation.call")
    def test_non_stream_call_retries_temporary_ssl_error(self, call, _wait):
        expected = object()
        call.side_effect = [SSLError("temporary"), expected]

        result = EnterpriseAgent._call_with_network_retry(model="demo")

        self.assertIs(result, expected)
        self.assertEqual(call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
