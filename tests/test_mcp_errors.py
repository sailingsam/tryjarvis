"""Regression coverage for what a failed MCP server startup tells the user."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from jarvis.tools.mcp_client import (
    MCPClient,
    _last_stderr_line,
    _root_cause,
    _startup_error,
)


class _Group(Exception):
    """An exception group, minus the 3.11 builtin — we still support 3.10."""

    def __init__(self, *exceptions):
        super().__init__(f"unhandled errors in a TaskGroup ({len(exceptions)} sub-exception)")
        self.exceptions = list(exceptions)


class _BaseGroup(BaseException):
    """A group holding a cancellation: a BaseException, so `except Exception` misses it."""

    def __init__(self, *exceptions):
        super().__init__("unhandled errors in a TaskGroup (1 sub-exception)")
        self.exceptions = list(exceptions)


class RootCauseTests(unittest.TestCase):
    def test_plain_exception_is_its_own_cause(self):
        err = FileNotFoundError("no such file: 'npx'")
        self.assertIs(_root_cause(err), err)

    def test_nested_groups_are_unwrapped(self):
        err = ConnectionError("Connection closed")
        self.assertIs(_root_cause(_Group(_Group(err))), err)

    def test_cancelled_siblings_are_stepped_over(self):
        err = PermissionError("bad credentials")
        group = _Group(asyncio.CancelledError(), err)
        self.assertIs(_root_cause(group), err)

    def test_nested_cancelled_group_is_stepped_over(self):
        err = PermissionError("bad credentials")
        group = _Group(_Group(asyncio.CancelledError()), err)
        self.assertIs(_root_cause(group), err)


class StartupErrorTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.log = Path(self._dir.name) / "mcp-gmail.log"
        self.addCleanup(self._dir.cleanup)

    def test_message_names_the_cause_not_the_task_group(self):
        group = _Group(_Group(ConnectionError("Connection closed")))
        message = _startup_error(group, None)
        self.assertNotIn("TaskGroup", message)
        self.assertIn("ConnectionError: Connection closed", message)

    def test_message_carries_the_servers_last_words_and_its_log(self):
        self.log.write_text("re-keying session\nboom: bad credentials\n")
        message = _startup_error(_Group(ConnectionError("Connection closed")), str(self.log))
        self.assertIn("boom: bad credentials", message)
        self.assertIn(str(self.log), message)
        self.assertEqual(1, len(message.splitlines()))

    def test_remote_server_has_no_log_to_point_at(self):
        message = _startup_error(_Group(PermissionError("401 Unauthorized")), None)
        self.assertIn("401 Unauthorized", message)
        self.assertNotIn("full log", message)

    def test_stderr_from_an_older_attempt_is_not_reused(self):
        self.log.write_text("old failure: expired token\n")
        start = self.log.stat().st_size
        message = _startup_error(
            _Group(FileNotFoundError("missing binary")), str(self.log), start
        )
        self.assertNotIn("expired token", message)

    def test_only_current_attempts_stderr_is_reported(self):
        self.log.write_text("old failure: expired token\n")
        start = self.log.stat().st_size
        with self.log.open("a") as stream:
            stream.write("current failure: bad credentials\n")
        message = _startup_error(
            _Group(ConnectionError("Connection closed")), str(self.log), start
        )
        self.assertIn("current failure: bad credentials", message)
        self.assertNotIn("expired token", message)

    def test_missing_log_is_not_an_error_of_its_own(self):
        self.assertEqual("", _last_stderr_line(str(self.log / "nope")))
        self.assertEqual("", _last_stderr_line(None))


class _DeadClient(MCPClient):
    def __init__(self, error, errlog_path=None):
        super().__init__("broken", errlog_path=errlog_path)
        self._error_to_raise = error

    async def _serve(self):
        raise self._error_to_raise


class StartReportsTheCauseTests(unittest.TestCase):
    def test_startup_failure_is_reported_in_full(self):
        client = _DeadClient(_Group(ConnectionError("Connection closed")))
        with self.assertRaises(RuntimeError) as caught:
            client.start(timeout=5)
        self.assertIn("ConnectionError: Connection closed", str(caught.exception))

    def test_a_cancelled_group_does_not_become_a_timeout(self):
        # It is not an Exception, so the old handler let it past and nothing
        # set _ready — start() then waited out the timeout and blamed the clock.
        client = _DeadClient(_BaseGroup(asyncio.CancelledError()))
        with self.assertRaises(RuntimeError):
            client.start(timeout=5)

    def test_start_does_not_report_stale_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "mcp-broken.log"
            log.write_text("old failure: expired token\n")
            client = _DeadClient(
                _Group(ConnectionError("Connection closed")), str(log)
            )
            with self.assertRaises(RuntimeError) as caught:
                client.start(timeout=5)
            self.assertNotIn("expired token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
