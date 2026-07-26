"""Unit tests for HIL framework (non-hardware portions)."""

import pytest
from firmforge.infrastructure.hil import HILFramework, HILTestAssertion, HILTestResult


class TestHILPatternMatching:
    """Tests for pattern matching (no hardware needed)."""

    def test_match_contains(self):
        assert HILFramework._match_pattern("Hello World", "Hello", "contains")

    def test_match_contains_not_found(self):
        assert not HILFramework._match_pattern("Hello World", "xyz", "contains")

    def test_match_exact(self):
        assert HILFramework._match_pattern("Hello", "Hello", "exact")

    def test_match_exact_with_whitespace(self):
        assert HILFramework._match_pattern("  Hello  ", "Hello", "exact")

    def test_match_exact_mismatch(self):
        assert not HILFramework._match_pattern("Hello World", "Hello", "exact")

    def test_match_regex(self):
        assert HILFramework._match_pattern("12345", r"\d{5}", "regex")

    def test_match_regex_no_match(self):
        assert not HILFramework._match_pattern("abc", r"\d{5}", "regex")

    def test_match_starts_with(self):
        assert HILFramework._match_pattern("Hello World", "Hello", "starts_with")

    def test_match_starts_with_no_match(self):
        assert not HILFramework._match_pattern("Hello World", "World", "starts_with")


class TestHILDataStructures:
    """Tests for HIL data structures."""

    def test_assertion_defaults(self):
        a = HILTestAssertion(name="test", expected="Hello")
        assert a.name == "test"
        assert a.expected == "Hello"
        assert a.success is None  # not yet evaluated

    def test_test_result_aggregation(self):
        r = HILTestResult()
        r.assertions = [
            HILTestAssertion(name="a1", success=True),
            HILTestAssertion(name="a2", success=False),
            HILTestAssertion(name="a3", success=True),
        ]
        r.assertions_passed = 2
        r.assertions_failed = 1
        r.success = False

        assert not r.success
        assert r.assertions_passed == 2
        assert r.assertions_failed == 1


class TestHILFrameworkLifecycle:
    """Tests for HIL framework connection lifecycle (no hardware)."""

    def test_not_connected_by_default(self):
        hil = HILFramework()
        assert not hil.connected

    def test_read_when_disconnected(self):
        hil = HILFramework()
        assert hil.read_line() == ""
        assert hil.read_all() == ""

    def test_assert_when_disconnected(self):
        hil = HILFramework()
        result = hil.assert_output("Hello")
        assert not result.success
        assert "not connected" in result.actual_output

    def test_disconnect_when_not_connected(self):
        hil = HILFramework()
        hil.disconnect()  # should not raise
        assert not hil.connected
