"""Regression coverage for the readable logs and confirmation card helpers."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis import config, logs
from jarvis.core.brain import Brain
from jarvis.daemon import _root_error


class ReadableLogsTests(unittest.TestCase):
    def test_journal_accepts_python_version_tag(self):
        line = "2026-09-21T11:00:00+0530 host python3[42]: you  > hello"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            logs._emit(line, chat=False, color=False, state={})
        self.assertIn("you     hello", output.getvalue())

    def test_chat_view_hides_mechanical_lines(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            logs._show("(MCP 'x': 3 tools)", "11:00", "2026-09-21",
                       chat=True, color=False, state={})
        self.assertEqual("", output.getvalue())


class ConfirmationCardTests(unittest.TestCase):
    def test_long_confirmation_is_shortened_at_colon(self):
        question = "Send this message to Aatmik: " + "hello " * 30
        spoken = Brain._spoken_confirm(question)
        self.assertIn("Send this message to Aatmik", spoken)
        self.assertNotIn("hello", spoken)

    def test_short_confirmation_stays_verbatim(self):
        question = "Turn off the lights?"
        self.assertEqual(question, Brain._spoken_confirm(question))

    def test_card_is_private_and_removed_after_use(self):
        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "card.json"
            with (mock.patch.object(config, "CARD_FILE", card),
                  mock.patch("jarvis.tray.alive", return_value=True)):
                self.assertTrue(Brain._show_card("Send it?"))
                self.assertEqual("Send it?", json.loads(card.read_text())["text"])
                self.assertEqual(0o600, card.stat().st_mode & 0o777)
                Brain._hide_card()
                self.assertFalse(card.exists())


class RootErrorTests(unittest.TestCase):
    def test_exception_group_reports_leaf(self):
        error = RuntimeError("wrapper")
        error.exceptions = [ConnectionError("refused")]
        self.assertEqual("ConnectionError: refused", _root_error(error))


if __name__ == "__main__":
    unittest.main()
