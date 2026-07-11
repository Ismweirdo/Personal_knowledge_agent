import json

from app.conversation.service import encode_sse


def test_sse_event_uses_json_and_protocol_delimiters() -> None:
    event = encode_sse("delta", {"text": "你好"})

    assert event.startswith("event: delta\ndata: ")
    assert event.endswith("\n\n")
    payload = json.loads(event.split("data: ", 1)[1])
    assert payload == {"text": "你好"}
