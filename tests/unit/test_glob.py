"""Unit tests for path.Match-style globbing.

Most of the cases are from the tests for Go's path.Match.
"""

import pytest

from shimmer._glob import BadPatternError, compile_pattern


@pytest.mark.parametrize(
    ("pattern", "name", "matches"),
    [
        ("abc", "abc", True),
        ("*", "abc", True),
        ("*c", "abc", True),
        ("a*", "a", True),
        ("a*", "abc", True),
        ("a*", "ab/c", False),
        ("a*/b", "abc/b", True),
        ("a*/b", "a/c/b", False),
        ("a*b*c*d*e*/f", "axbxcxdxe/f", True),
        ("a*b*c*d*e*/f", "axbxcxdxe/xxx/f", False),
        ("a*b?c*x", "abxbbxdbxebxczzx", True),
        ("a*b?c*x", "abxbbxdbxebxczzy", False),
        ("ab[c]", "abc", True),
        ("ab[b-d]", "abc", True),
        ("ab[e-g]", "abc", False),
        ("ab[^c]", "abc", False),
        ("ab[^b-d]", "abc", False),
        ("ab[^e-g]", "abc", True),
        ("[!x]pp", "xpp", True),
        ("[!x]pp", "app", False),
        ("a\\*b", "a*b", True),
        ("a\\*b", "ab", False),
        ("a?b", "a☺b", True),
        ("a[^a]b", "a☺b", True),
        ("a???b", "a☺b", False),
        ("[a-ζ]*", "δ", True),
        ("*[a-ζ]", "A", False),
        ("a?b", "a/b", False),
        ("a*b", "a/b", False),
        ("[\\]a]", "]", True),
        ("[\\-]", "-", True),
        ("[x\\-]", "x", True),
        ("[x\\-]", "-", True),
        ("[x\\-]", "z", False),
        ("[\\-x]", "a", False),
        ("[z-a]", "b", False),
        ("[^z-a]", "b", True),
        ("*x", "xxx", True),
        ("*", "a\nb", True),
        ("a.c", "abc", False),
    ],
)
def test_match(pattern: str, name: str, matches: bool):
    assert bool(compile_pattern(pattern).fullmatch(name)) is matches


@pytest.mark.parametrize(
    "pattern",
    ["[]a]", "[-]", "[x-]", "[-x]", "[a-b-c]", "[", "[^", "[^bc", "a[", "[a", "[a-", "\\", "a\\"],
)
def test_bad_pattern(pattern: str):
    with pytest.raises(BadPatternError):
        compile_pattern(pattern)
