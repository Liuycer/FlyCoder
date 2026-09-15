import io
import http.client
import json
import unittest
import urllib.error
from unittest.mock import patch
from flycoder.llm import ChatCompletionsCodingAdapter

class MeteringTests(unittest.TestCase):
    def adapter(self):
        return ChatCompletionsCodingAdapter('model','fake-key','https://example.com/v1',max_retries=2,retry_backoff=0)
    def response(self,usage=None):
        return io.BytesIO(json.dumps({'usage':usage,'choices':[{'finish_reason':'stop','message':{'content':'{"analysis":"ok","files":{}}'}}]}).encode())
    def test_retries_consume_budget_before_network_request(self):
        coder=self.adapter(); count=[0]
        def guard():
            if count[0]>=1: raise RuntimeError('budget exhausted')
            count[0]+=1
        coder.request_budget=guard
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=urllib.error.URLError('offline')
            with self.assertRaisesRegex(RuntimeError,'budget exhausted'): coder.read('task',{})
            self.assertEqual(factory.return_value.open.call_count,1)
        self.assertEqual(coder.http_attempts,1)
    def test_usage_counts_are_preserved_and_missing_is_not_zero(self):
        coder=self.adapter()
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=[self.response({'prompt_tokens':12,'completion_tokens':7}),self.response()]
            coder.read('task',{});coder.read('task',{})
        self.assertEqual(coder.usage_records,[{'input_tokens':12,'output_tokens':7},{}])
        self.assertEqual(coder.http_attempts,2)

    def test_remote_disconnect_retries_within_the_same_budget(self):
        coder=self.adapter()
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=[http.client.RemoteDisconnected('closed'),self.response({'prompt_tokens':1,'completion_tokens':2})]
            coder.read('task',{})
        self.assertEqual(coder.http_attempts,2)
        self.assertEqual(coder.usage_records,[{'input_tokens':1,'output_tokens':2}])
