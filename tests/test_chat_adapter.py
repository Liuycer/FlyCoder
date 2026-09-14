import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from flycoder.__main__ import main
from flycoder.llm import ChatCompletionsCodingAdapter, NoRedirect, OpenAICodingAdapter


class ChatAdapterTests(unittest.TestCase):
    def adapter(self, **kwargs):
        return ChatCompletionsCodingAdapter("test-model", "fake-key", "https://provider.example/v1/", **kwargs)

    def response(self, content=None, finish="stop"):
        if content is None:
            content = json.dumps({"analysis": "fix", "files": {"calculator.py": "fixed"}})
        return io.BytesIO(json.dumps({"choices": [{"finish_reason": finish,
                            "message": {"content": content}}]}).encode())

    def test_chat_request_and_edit_contract(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = self.response()
            result = self.adapter().edit("fix average", {"calculator.py": "bug"}, ["calculator.py"], "analysis", "failed", 2)
            req = factory.return_value.open.call_args[0][0]
        self.assertEqual(result, {"calculator.py": "fixed"})
        self.assertEqual(req.full_url, "https://provider.example/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer fake-key")
        body = json.loads(req.data)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["model"], "test-model")
        self.assertFalse(body["stream"])
        self.assertNotIn("store", body)
        self.assertEqual(json.loads(body["messages"][1]["content"])["test_output"], "failed")

    def test_text_mode_omits_response_format(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = self.response()
            self.adapter(json_mode="text").read("task", {})
            req = factory.return_value.open.call_args[0][0]
        self.assertNotIn("response_format", json.loads(req.data))

    def test_empty_invalid_and_malformed_content(self):
        for content in ["", "not json", "[]", '{"analysis":"ok","files":{"a":123}}']:
            with self.subTest(content=content), patch("urllib.request.build_opener") as factory:
                factory.return_value.open.return_value = self.response(content)
                with self.assertRaises(ValueError):
                    self.adapter().read("task", {})

    def test_nonstop_response_rejected(self):
        for reason in ["length", "tool_calls", "content_filter", None]:
            with self.subTest(reason=reason), patch("urllib.request.build_opener") as factory:
                factory.return_value.open.return_value = self.response(finish=reason)
                with self.assertRaises(RuntimeError):
                    self.adapter().read("task", {})

    def test_provider_http_error_redacted(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = urllib.error.HTTPError(
                "https://provider.example", 401, "fake-key", {}, io.BytesIO(b"fake-key"))
            with self.assertRaisesRegex(RuntimeError, "401") as caught:
                self.adapter().read("task", {})
        self.assertNotIn("fake-key", str(caught.exception))

    def test_deepseek_configuration_and_key_separation(self):
        with patch.dict("os.environ", {"LLM_MODEL": "account-model", "DEEPSEEK_API_KEY": "deep-key", "OPENAI_API_KEY": "other-key"}, clear=True):
            adapter = ChatCompletionsCodingAdapter.from_env("deepseek")
            self.assertEqual(adapter.endpoint, "https://api.deepseek.com/chat/completions")
            self.assertEqual(adapter.api_key, "deep-key")
            with self.assertRaises(ValueError):
                ChatCompletionsCodingAdapter.from_env("chat-completions")

    def test_endpoints_and_configuration_validation(self):
        for base in ["https://provider.example/v1", "https://provider.example/v1/", "https://provider.example/v1/chat/completions/"]:
            self.assertEqual(ChatCompletionsCodingAdapter("m", "k", base).endpoint,
                             "https://provider.example/v1/chat/completions")
        self.assertEqual(ChatCompletionsCodingAdapter("m", "k", "http://localhost:8000/v1").endpoint,
                         "http://localhost:8000/v1/chat/completions")
        for base in ["", "http://provider.example", "https://key@provider.example", "https://provider.example?a=b", "https://provider.example/#frag"]:
            with self.subTest(base=base), self.assertRaises(ValueError):
                ChatCompletionsCodingAdapter("m", "k", base)
        for config in [{"timeout": 0}, {"timeout": float("nan")}, {"max_tokens": 0}, {"json_mode": "unknown"}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.adapter(**config)

    def test_redirects_rejected(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://elsewhere.example"))

    def test_cli_chat_demo_end_to_end_offline(self):
        fixed = 'def average(values):\n    if not values:\n        raise ValueError("empty")\n    return sum(values) / len(values)\n'
        for provider in ["deepseek", "chat-completions"]:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as tmp, patch.dict(
                    "os.environ", {"LLM_MODEL": "test-model", "LLM_API_KEY": "fake-key",
                                   "LLM_BASE_URL": "https://provider.example/v1"}, clear=True), patch(
                    "sys.argv", ["flycoder", "demo", "--llm", provider, "--runs", tmp]), patch(
                    "urllib.request.build_opener") as factory, contextlib.redirect_stdout(io.StringIO()):
                factory.return_value.open.side_effect = [
                    self.response(json.dumps({"analysis": "fix", "files": {}})),
                    self.response(json.dumps({"analysis": "fixed", "files": {"calculator.py": fixed}}))]
                self.assertEqual(main(), 0)
                summary = json.loads(next(Path(tmp).glob("*/summary.json")).read_text())
                self.assertEqual(summary["coder"], "ChatCompletionsCodingAdapter")
                self.assertEqual(summary["status"], "done")

    def test_provider_bad_envelope_size_and_timeout(self):
        for raw in [b"[]", b"{}", b"not json", b"x" * 2000001]:
            with self.subTest(size=len(raw)), patch("urllib.request.build_opener") as factory:
                factory.return_value.open.return_value = io.BytesIO(raw)
                with self.assertRaises(ValueError):
                    self.adapter().read("task", {})
        with patch("urllib.request.build_opener") as factory, patch("time.sleep") as sleeper:
            factory.return_value.open.side_effect = TimeoutError()
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                self.adapter().read("task", {})
            self.assertEqual(factory.return_value.open.call_count, 3)
            self.assertEqual([c.args[0] for c in sleeper.call_args_list], [0.5, 1.0])

    def test_retryable_http_and_network_errors_retry_then_succeed(self):
        transient = [
            urllib.error.HTTPError("https://provider.example", 429, "rate", {}, io.BytesIO(b"x")),
            urllib.error.HTTPError("https://provider.example", 503, "down", {}, io.BytesIO(b"x")),
            urllib.error.URLError("connection reset"),
        ]
        for error in transient:
            with self.subTest(error=type(error).__name__), patch("urllib.request.build_opener") as factory, patch(
                    "time.sleep") as sleeper:
                factory.return_value.open.side_effect = [error, self.response()]
                result = self.adapter(max_retries=1).read("task", {})
            self.assertEqual(result, "fix")
            self.assertEqual(factory.return_value.open.call_count, 2)
            sleeper.assert_called_once_with(0.5)

    def test_non_retryable_http_error_is_not_retried(self):
        for code in [400, 401, 402, 403, 404]:
            with self.subTest(code=code), patch("urllib.request.build_opener") as factory, patch("time.sleep") as sleeper:
                factory.return_value.open.side_effect = urllib.error.HTTPError(
                    "https://provider.example", code, "err", {}, io.BytesIO(b"secret"))
                with self.assertRaisesRegex(RuntimeError, str(code)):
                    self.adapter().read("task", {})
            self.assertEqual(factory.return_value.open.call_count, 1)
            sleeper.assert_not_called()

    def test_retries_exhausted_reports_error(self):
        with patch("urllib.request.build_opener") as factory, patch("time.sleep") as sleeper:
            factory.return_value.open.side_effect = urllib.error.HTTPError(
                "https://provider.example", 500, "down", {}, io.BytesIO(b"x"))
            with self.assertRaisesRegex(RuntimeError, "500"):
                self.adapter(max_retries=2).read("task", {})
        self.assertEqual(factory.return_value.open.call_count, 3)
        self.assertEqual([c.args[0] for c in sleeper.call_args_list], [0.5, 1.0])
        with patch("urllib.request.build_opener") as factory, patch("time.sleep"):
            factory.return_value.open.side_effect = urllib.error.URLError("dns")
            with self.assertRaisesRegex(RuntimeError, "connection failed"):
                self.adapter(max_retries=2).read("task", {})
        self.assertEqual(factory.return_value.open.call_count, 3)

    def test_zero_retries_single_attempt_and_invalid_retry_config(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = urllib.error.HTTPError(
                "https://provider.example", 503, "down", {}, io.BytesIO(b"x"))
            with self.assertRaisesRegex(RuntimeError, "503"):
                self.adapter(max_retries=0).read("task", {})
        self.assertEqual(factory.return_value.open.call_count, 1)
        for config in [{"max_retries": -1}, {"retry_backoff": -0.1}, {"retry_backoff": float("nan")}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.adapter(**config)

    def test_retry_env_defaults_and_overrides(self):
        env = {"LLM_MODEL": "m", "LLM_API_KEY": "k", "LLM_BASE_URL": "https://provider.example/v1"}
        with patch.dict("os.environ", env, clear=True):
            adapter = ChatCompletionsCodingAdapter.from_env()
            self.assertEqual((adapter.max_retries, adapter.retry_backoff), (2, 0.5))
        with patch.dict("os.environ", {"OPENAI_MODEL": "m", "OPENAI_API_KEY": "k"}, clear=True):
            adapter = OpenAICodingAdapter.from_env()
            self.assertEqual((adapter.max_retries, adapter.retry_backoff), (2, 0.5))
        env.update({"LLM_MAX_RETRIES": "4", "LLM_RETRY_BACKOFF": "0.25"})
        with patch.dict("os.environ", env, clear=True):
            adapter = ChatCompletionsCodingAdapter.from_env()
            self.assertEqual((adapter.max_retries, adapter.retry_backoff), (4, 0.25))
        for bad in [{"LLM_MAX_RETRIES": "-1"}, {"LLM_MAX_RETRIES": "abc"},
                    {"LLM_RETRY_BACKOFF": "-1"}, {"LLM_RETRY_BACKOFF": "abc"}]:
            with self.subTest(bad=bad), patch.dict("os.environ", {**env, **bad}, clear=True):
                with self.assertRaises(ValueError):
                    ChatCompletionsCodingAdapter.from_env()

    def test_retry_delay_is_capped(self):
        from flycoder.llm import _retry_delay
        self.assertEqual(_retry_delay(0.5, 0), 0.5)
        self.assertEqual(_retry_delay(0.5, 3), 4.0)
        self.assertEqual(_retry_delay(0.5, 10), 8.0)
