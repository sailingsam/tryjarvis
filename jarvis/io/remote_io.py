"""RemoteIO — the brain's IO channel when it runs inside the daemon.

The brain is IO-agnostic: it only calls speak()/listen(). In the daemon, a
confirmation prompt must reach the *client* process (over the socket) and its
answer must come back — so speak() sends a confirm-prompt frame to the client
and listen() blocks on the client's reply. This is what keeps the
Humans-in-control confirmation gate intact across the socket.

The main reply is NOT sent through here — the daemon returns it from think()
and frames it separately. RemoteIO carries only the mid-tool confirmation.
"""

from __future__ import annotations

import json


class RemoteIO:
    def __init__(self, conn_file):
        self._f = conn_file        # a socket .makefile("rw") object

    def speak(self, text: str) -> None:
        self._f.write(json.dumps({"type": "confirm_prompt", "text": text}) + "\n")
        self._f.flush()

    def listen(self) -> str | None:
        line = self._f.readline()
        if not line:
            return None
        try:
            return json.loads(line).get("text", "")
        except json.JSONDecodeError:
            return None
