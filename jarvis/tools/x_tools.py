"""X (Twitter) tools — post, read mentions, reply, and DMs.

Cost matters: X charges per API call/resource, so we do NOT hand the model a
raw API. Each tool is a deterministic wrapper with a HARD cap on how much it
fetches — the model picks intent (post / read / reply), our code bounds the
spend. Writes (post, reply, send DM) go through the confirmation gate; reads
run freely but capped.

Auth is OAuth 1.0a user-context (the user's own account) via env creds.
"""

from __future__ import annotations

from .base import Tool

_MAX_READ = 10          # hard cap on items any read tool will fetch — cost guard


class _XClient:
    """Thin tweepy wrapper. Created once; reused by all X tools."""

    def __init__(self, api_key: str, api_secret: str, access_token: str, access_secret: str):
        import tweepy

        self._client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
        )
        self._me_id: str | None = None

    def me_id(self) -> str:
        if self._me_id is None:
            self._me_id = str(self._client.get_me().data.id)
        return self._me_id

    def post(self, text: str, reply_to: str | None = None) -> str:
        resp = self._client.create_tweet(text=text, in_reply_to_tweet_id=reply_to)
        return str(resp.data.get("id", ""))

    def mentions(self, limit: int) -> list[dict]:
        resp = self._client.get_users_mentions(
            id=self.me_id(), max_results=max(5, min(limit, _MAX_READ)),
            tweet_fields=["author_id", "created_at"],
        )
        return [{"id": str(t.id), "text": t.text} for t in (resp.data or [])]

    def dms(self, limit: int) -> list[dict]:
        resp = self._client.get_direct_message_events(
            max_results=max(1, min(limit, _MAX_READ)),
            dm_event_fields=["sender_id", "text", "created_at"],
        )
        out = []
        for e in (resp.data or []):
            out.append({"sender_id": str(getattr(e, "sender_id", "")), "text": getattr(e, "text", "")})
        return out

    def send_dm(self, participant_id: str, text: str) -> str:
        resp = self._client.create_direct_message(participant_id=participant_id, text=text)
        return "sent"


class _XTool(Tool):
    def __init__(self, client: _XClient):
        self._x = client


class XPost(_XTool):
    name = "x_post"
    description = "Post a new tweet to X (Twitter) from the user's account."
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "the tweet text (<=280 chars)"}},
        "required": ["text"],
    }
    needs_confirm = True

    def confirmation(self, text: str = "", **_) -> str:
        return f'Post this tweet?\n\n"{text}"'

    def execute(self, text: str = "", **_) -> str:
        try:
            tid = self._x.post(text.strip())
            return f"Posted (tweet id {tid})."
        except Exception as e:
            return f"(x error) {e}"


class XReadMentions(_XTool):
    name = "x_read_mentions"
    description = "Read recent tweets that mention the user (capped). Read-only."
    input_schema = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": f"how many (max {_MAX_READ})"}},
    }
    needs_confirm = False

    def execute(self, limit: int = _MAX_READ, **_) -> str:
        try:
            items = self._x.mentions(int(limit))
            if not items:
                return "No recent mentions."
            return "\n".join(f"[{m['id']}] {m['text']}" for m in items)
        except Exception as e:
            return f"(x error) {e}"


class XReply(_XTool):
    name = "x_reply"
    description = "Reply to a specific tweet (by its id) from the user's account."
    input_schema = {
        "type": "object",
        "properties": {
            "tweet_id": {"type": "string", "description": "the tweet id to reply to"},
            "text": {"type": "string", "description": "the reply text"},
        },
        "required": ["tweet_id", "text"],
    }
    needs_confirm = True

    def confirmation(self, tweet_id: str = "", text: str = "", **_) -> str:
        return f'Reply to tweet {tweet_id} with:\n\n"{text}"'

    def execute(self, tweet_id: str = "", text: str = "", **_) -> str:
        try:
            tid = self._x.post(text.strip(), reply_to=tweet_id)
            return f"Replied (tweet id {tid})."
        except Exception as e:
            return f"(x error) {e}"


class XReadDMs(_XTool):
    name = "x_read_dms"
    description = "Read recent direct messages (capped). Read-only."
    input_schema = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": f"how many (max {_MAX_READ})"}},
    }
    needs_confirm = False

    def execute(self, limit: int = _MAX_READ, **_) -> str:
        try:
            items = self._x.dms(int(limit))
            if not items:
                return "No recent DMs."
            return "\n".join(f"from {d['sender_id']}: {d['text']}" for d in items)
        except Exception as e:
            return f"(x error) {e}"


class XSendDM(_XTool):
    name = "x_send_dm"
    description = "Send a direct message to a user (by their numeric X user id)."
    input_schema = {
        "type": "object",
        "properties": {
            "participant_id": {"type": "string", "description": "recipient's numeric X user id"},
            "text": {"type": "string", "description": "the message text"},
        },
        "required": ["participant_id", "text"],
    }
    needs_confirm = True

    def confirmation(self, participant_id: str = "", text: str = "", **_) -> str:
        return f'Send DM to {participant_id}:\n\n"{text}"'

    def execute(self, participant_id: str = "", text: str = "", **_) -> str:
        try:
            self._x.send_dm(participant_id, text.strip())
            return "DM sent."
        except Exception as e:
            return f"(x error) {e}"


def x_tools(api_key: str, api_secret: str, access_token: str, access_secret: str) -> list[Tool]:
    """Build the X tools sharing one client. Call only when creds are configured."""
    client = _XClient(api_key, api_secret, access_token, access_secret)
    return [XPost(client), XReadMentions(client), XReply(client), XReadDMs(client), XSendDM(client)]
