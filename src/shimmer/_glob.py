"""Glob matching with the semantics of Go's ``path.Match``.

Pebble filters ``list_files`` patterns with ``path.Match``, which differs from
Python's ``fnmatch``: negation is ``[^x]`` rather than ``[!x]``, a backslash escapes
the next character, and a malformed pattern is an error.
"""

from __future__ import annotations

import re


class BadPatternError(ValueError):
    """The pattern is malformed."""


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Translate a ``path.Match`` pattern into a regular expression for ``fullmatch``."""
    regex: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            regex.append("[^/]*")
            i += 1
        elif char == "?":
            regex.append("[^/]")
            i += 1
        elif char == "[":
            class_regex, i = _compile_class(pattern, i + 1)
            regex.append(class_regex)
        else:
            if char == "\\":
                i += 1
                if i == len(pattern):
                    raise BadPatternError(pattern)
            regex.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(regex), re.DOTALL)


def _compile_class(pattern: str, i: int) -> tuple[str, int]:
    """Translate the character class whose body starts at ``i``.

    Returns the regular expression and the index just past the closing bracket.
    """
    negated = pattern[i : i + 1] == "^"
    if negated:
        i += 1
    ranges: list[str] = []
    seen_any = False
    while not (seen_any and pattern[i : i + 1] == "]"):
        low, i = _class_char(pattern, i)
        high = low
        if pattern[i : i + 1] == "-":
            high, i = _class_char(pattern, i + 1)
        seen_any = True
        # A backwards range such as [z-a] is valid, but matches nothing.
        if low <= high:
            ranges.append(f"{re.escape(low)}-{re.escape(high)}")
    if ranges:
        regex = f"[{'^' if negated else ''}{''.join(ranges)}]"
    else:
        regex = "." if negated else "(?!)"
    return regex, i + 1


def _class_char(pattern: str, i: int) -> tuple[str, int]:
    """Read one, possibly escaped, character of a character class."""
    if pattern[i : i + 1] in ("", "-", "]"):
        raise BadPatternError(pattern)
    if pattern[i] == "\\":
        i += 1
    # Something, at the very least the closing bracket, has to follow.
    if i + 1 >= len(pattern):
        raise BadPatternError(pattern)
    return pattern[i], i + 1
