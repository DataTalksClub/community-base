"""Answer text helpers for choice questions."""

from __future__ import annotations


def _selected_option_index(option: str) -> int | None:
    option = option.strip()
    if not option:
        return None

    try:
        return int(option)
    except ValueError:
        return None


def _selected_option_indexes(answer_text: str | None):
    raw_answer_text = answer_text or ""
    stripped_answer_text = raw_answer_text.strip()
    options = stripped_answer_text.split(",")
    for option in options:
        index = _selected_option_index(option)
        if index is not None:
            yield index


def extract_selected_option_indexes(answer_text: str | None) -> list[int]:
    return list(_selected_option_indexes(answer_text))
