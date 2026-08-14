"""Regression coverage for MCP action-risk classification."""

import unittest

from jarvis.tools.mcp_client import _infer_confirm


class _Meta:
    def __init__(self, name: str, annotations=None):
        self.name = name
        self.annotations = annotations


class _Annotations:
    def __init__(self, *, read_only=None, destructive=None):
        self.readOnlyHint = read_only
        self.destructiveHint = destructive


class MCPConfirmationTests(unittest.TestCase):
    def test_harmless_controls_run_without_confirmation(self):
        for name in ("play_track", "turn_on_light", "get_status"):
            self.assertFalse(_infer_confirm(_Meta(name)))

    def test_consequential_actions_require_confirmation(self):
        for name in ("send_message", "transfer_money", "book_appointment"):
            self.assertTrue(_infer_confirm(_Meta(name)))

    def test_unknown_action_requires_confirmation(self):
        self.assertTrue(_infer_confirm(_Meta("run_workflow")))
        self.assertTrue(_infer_confirm(_Meta("forget_note")))

    def test_read_only_metadata_runs_without_confirmation(self):
        meta = _Meta("fetch_account", _Annotations(read_only=True))
        self.assertFalse(_infer_confirm(meta))

    def test_critical_name_overrides_non_destructive_metadata(self):
        meta = _Meta("send_email", _Annotations(destructive=False))
        self.assertTrue(_infer_confirm(meta))


if __name__ == "__main__":
    unittest.main()
