from query_parse.utils import cache, find_regex, flatten_tree


class TestFindRegex:
    def test_yields_start_end_match_triples(self):
        assert list(find_regex(r"\d+", "ab 12 cd 34")) == [
            (3, 5, "12"),
            (9, 11, "34"),
        ]

    def test_strips_surrounding_whitespace_and_adjusts_span(self):
        # Leading/trailing spaces in the match are trimmed and `start` advanced.
        (start, end, text), = list(find_regex(r"\s*hello\s*", "xx  hello  yy"))
        assert text == "hello"
        assert (start, end) == (4, 9)

    def test_case_insensitive(self):
        assert [m[2] for m in find_regex(r"cat", "CAT cat Cat")] == ["CAT", "cat", "Cat"]

    def test_no_match_yields_nothing(self):
        assert list(find_regex(r"\d+", "no digits here")) == []


class TestFlattenTree:
    def test_string_passthrough(self):
        assert flatten_tree("plain") == "plain"


class TestCache:
    def test_memoises_in_memory(self):
        calls = {"n": 0}

        @cache
        def double(x):
            calls["n"] += 1
            return x * 2

        assert double(3) == 6
        assert double(3) == 6  # served from cache
        assert calls["n"] == 1

    def test_distinct_args_recompute(self):
        calls = {"n": 0}

        @cache
        def ident(x):
            calls["n"] += 1
            return x

        ident(1)
        ident(2)
        ident(1)
        assert calls["n"] == 2
