from __future__ import annotations

import re

from .contracts import HeaderCard


def parse_header_text(text: str) -> list[HeaderCard]:
    """Parse raw FITS header text into structured cards for display."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not normalized:
        return []

    cards: list[HeaderCard] = []
    for line_number, line in enumerate(normalized.split("\n"), start=1):
        card = _parse_header_line(line_number, line)
        if card.kind == "continue" and cards and cards[-1].kind in {"keyword", "hierarch", "continue"}:
            _merge_continue(cards[-1], card)
            continue
        if card.kind in {"comment", "history"} and cards and cards[-1].kind == card.kind:
            _merge_comment_block(cards[-1], card)
            continue
        cards.append(card)
    return cards


def _parse_header_line(line_number: int, line: str) -> HeaderCard:
    stripped = line.strip()
    if not stripped:
        return HeaderCard(
            index=line_number,
            kind="blank",
            raw_text=line,
            raw_lines=(line_number,),
        )

    if _starts_with_keyword(line, "COMMENT"):
        return HeaderCard(
            index=line_number,
            key="COMMENT",
            value=line[7:].strip(),
            kind="comment",
            raw_text=line,
            raw_lines=(line_number,),
        )

    if _starts_with_keyword(line, "HISTORY"):
        return HeaderCard(
            index=line_number,
            key="HISTORY",
            value=line[7:].strip(),
            kind="history",
            raw_text=line,
            raw_lines=(line_number,),
        )

    if _starts_with_keyword(line, "CONTINUE"):
        value_text, comment = _split_value_and_comment(line[len("CONTINUE"):].strip())
        return HeaderCard(
            index=line_number,
            key="CONTINUE",
            value=_display_value(value_text),
            comment=comment,
            kind="continue",
            raw_text=line,
            raw_lines=(line_number,),
        )

    if line.startswith("HIERARCH"):
        key, value, comment = _split_keyword_value_comment(line)
        return HeaderCard(
            index=line_number,
            key=key,
            value=value,
            comment=comment,
            kind="hierarch",
            raw_text=line,
            raw_lines=(line_number,),
        )

    key, value, comment = _split_keyword_value_comment(line)
    return HeaderCard(
        index=line_number,
        key=key,
        value=value,
        comment=comment,
        kind="keyword",
        raw_text=line,
        raw_lines=(line_number,),
    )


def _starts_with_keyword(line: str, keyword: str) -> bool:
    return line.startswith(keyword) and (len(line) == len(keyword) or line[len(keyword)] == " ")


def _split_keyword_value_comment(line: str) -> tuple[str, str, str]:
    if "=" not in line:
        return line.strip(), "", ""
    key_part, value_part = line.split("=", 1)
    value_text, comment = _split_value_and_comment(value_part)
    return key_part.strip(), _display_value(value_text), comment


def _split_value_and_comment(text: str) -> tuple[str, str]:
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "'":
            if in_string and index + 1 < len(text) and text[index + 1] == "'":
                index += 2
                continue
            in_string = not in_string
        elif char == "/" and not in_string:
            return text[:index].strip(), text[index + 1:].strip()
        index += 1
    return text.strip(), ""


def _display_value(value_text: str) -> str:
    text = value_text.strip()
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    return text


def _merge_continue(target: HeaderCard, continuation: HeaderCard) -> None:
    base_value = _strip_continue_marker(target.value)
    extra_value = _strip_continue_marker(continuation.value)
    target.value = f"{base_value}{extra_value}"
    target.comment = _merge_text(target.comment, continuation.comment)
    target.kind = "continue"
    target.raw_text = _merge_raw_text(target.raw_text, continuation.raw_text)
    target.raw_lines = target.raw_lines + continuation.raw_lines


def _merge_comment_block(target: HeaderCard, continuation: HeaderCard) -> None:
    target.value = _merge_text(target.value, continuation.value)
    target.raw_text = _merge_raw_text(target.raw_text, continuation.raw_text)
    target.raw_lines = target.raw_lines + continuation.raw_lines


def _strip_continue_marker(value: str) -> str:
    return value[:-1] if value.endswith("&") else value


def _merge_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if re.search(r"[\s-]$", left):
        return f"{left}{right}"
    return f"{left} {right}"


def _merge_raw_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    return f"{left}\n{right}"


__all__ = ["parse_header_text"]
