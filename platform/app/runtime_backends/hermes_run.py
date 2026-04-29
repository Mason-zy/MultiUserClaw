from __future__ import annotations

import json
import re
from typing import Any


_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</think>", re.IGNORECASE)


class HermesEventSanitizer:
    def __init__(self):
        self._in_thinking_block = False

    def filter_delta(self, text: str) -> str:
        output: list[str] = []
        pos = 0
        changed = False

        while pos < len(text):
            if self._in_thinking_block:
                close_match = _THINK_CLOSE_RE.search(text, pos)
                changed = True
                if close_match is None:
                    return "".join(output)
                pos = close_match.end()
                self._in_thinking_block = False

            open_match = _THINK_OPEN_RE.search(text, pos)
            if open_match is None:
                output.append(text[pos:])
                break

            output.append(text[pos : open_match.start()])
            close_match = _THINK_CLOSE_RE.search(text, open_match.end())
            changed = True
            if close_match is None:
                self._in_thinking_block = True
                break
            pos = close_match.end()

        filtered = "".join(output)
        return filtered.strip() if changed else filtered

    def sanitize_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = event.get("type") or event.get("event")
        sanitized = dict(event)

        if isinstance(event_type, str) and event_type.startswith("reasoning."):
            return None

        if event_type == "message.delta":
            delta = event.get("delta")
            if not isinstance(delta, str):
                return sanitized
            filtered = self.filter_delta(delta)
            if not filtered:
                return None
            sanitized["delta"] = filtered
            return sanitized

        if event_type == "message.completed" and isinstance(event.get("message"), dict):
            sanitized["message"] = sanitize_hermes_message(event["message"])
            return sanitized

        if event_type == "run.completed":
            output = event.get("output")
            if isinstance(output, str):
                sanitized["output"] = strip_thinking_blocks(output)
            elif isinstance(output, dict):
                sanitized["output"] = sanitize_hermes_message(output)
            return sanitized

        return sanitized


def strip_thinking_blocks(text: str) -> str:
    return HermesEventSanitizer().filter_delta(text)


def sanitize_hermes_message(message: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(message)
    if sanitized.get("role") == "assistant":
        content = sanitized.get("content")
        if isinstance(content, str):
            sanitized["content"] = strip_thinking_blocks(content)
        sanitized.pop("reasoning", None)
    return sanitized


def sanitize_hermes_messages(messages: list[Any]) -> list[Any]:
    return [sanitize_hermes_message(message) if isinstance(message, dict) else message for message in messages]


def sanitize_run_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitizer = HermesEventSanitizer()
    sanitized_events: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        sanitized = sanitizer.sanitize_event(event)
        if sanitized is not None:
            sanitized_events.append(sanitized)
    return sanitized_events


def sanitize_sse_block(raw_event: str, sanitizer: HermesEventSanitizer) -> str | None:
    data_lines = [line[5:].lstrip() for line in raw_event.splitlines() if line.startswith("data:")]
    if not data_lines:
        return None
    data = "\n".join(data_lines)
    if data == "[DONE]":
        return "data: [DONE]\n\n"
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return f"{raw_event}\n\n"
    if not isinstance(parsed, dict):
        return f"{raw_event}\n\n"
    sanitized = sanitizer.sanitize_event(parsed)
    if sanitized is None:
        return None
    return f"data: {json.dumps(sanitized, ensure_ascii=False, separators=(',', ':'))}\n\n"


def summarize_run_events(events: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    final_message: dict[str, Any] = {}
    status_text = "pending"

    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "message.completed" and isinstance(event.get("message"), dict):
            final_message = sanitize_hermes_message(event["message"])
        if event_type == "run.completed":
            status_text = "completed"
            if not final_message:
                output = event.get("output")
                if isinstance(output, str) and output:
                    final_message = {"role": "assistant", "content": strip_thinking_blocks(output)}
                elif isinstance(output, dict):
                    content = output.get("content")
                    if isinstance(content, str) and content:
                        final_message = {"role": "assistant", "content": strip_thinking_blocks(content)}
        elif event_type == "run.failed":
            status_text = "failed"

    return status_text, final_message
