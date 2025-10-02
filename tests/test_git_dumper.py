#!/usr/bin/env python3
"""Tests for git_dumper.py - BitBucket support and HEAD validation"""
import os
import sys
import unittest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import git_dumper  # noqa: E402


class TestHEADValidation(unittest.TestCase):
    """Test validation of .git/HEAD responses for various formats"""

    def test_valid_ref_format(self):
        """Test standard ref format"""
        test_cases = [
            "ref: refs/heads/master",
            "ref: refs/heads/master\n",
            "ref: refs/heads/main",
            "ref: refs/heads/develop\n",
            "ref: refs/heads/feature/test",
        ]
        for head_content in test_cases:
            with self.subTest(content=head_content):
                self.assertTrue(
                    git_dumper.is_valid_head(head_content),
                    f"Should accept: {repr(head_content)}"
                )

    def test_valid_sha1_format(self):
        """Test detached HEAD with SHA1"""
        test_cases = [
            "a" * 40,
            "b" * 40 + "\n",
            "1234567890abcdef1234567890abcdef12345678",
            "1234567890abcdef1234567890abcdef12345678\n",
        ]
        for head_content in test_cases:
            with self.subTest(content=head_content):
                self.assertTrue(
                    git_dumper.is_valid_head(head_content),
                    f"Should accept: {repr(head_content)}"
                )

    def test_valid_with_extra_whitespace(self):
        """Test valid formats with extra whitespace (BitBucket compatibility)"""
        test_cases = [
            "ref: refs/heads/master\n\n",
            "ref: refs/heads/master  \n",
            " ref: refs/heads/master\n",
            "ref: refs/heads/master\r\n",
            "a" * 40 + "\n\n",
            "a" * 40 + "  \n",
        ]
        for head_content in test_cases:
            with self.subTest(content=head_content):
                self.assertTrue(
                    git_dumper.is_valid_head(head_content),
                    f"Should accept: {repr(head_content)}"
                )

    def test_invalid_formats(self):
        """Test invalid HEAD formats that should be rejected"""
        test_cases = [
            "",
            " ",
            "\n",
            "not a valid head",
            "<html>404</html>",
            "ref:",
            "ref: ",
            "abc123",  # too short for SHA1
            "a" * 39,  # too short
            "a" * 41,  # too long
            "gggggggg" + "a" * 32,  # invalid hex
        ]
        for head_content in test_cases:
            with self.subTest(content=head_content):
                self.assertFalse(
                    git_dumper.is_valid_head(head_content),
                    f"Should reject: {repr(head_content)}"
                )

    def test_bitbucket_specific_formats(self):
        """Test BitBucket-specific HEAD formats"""
        # BitBucket may have specific formatting quirks
        test_cases = [
            "ref: refs/heads/master\n",  # Standard with newline
            "a" * 40 + "\n",  # Detached HEAD with newline
        ]
        for head_content in test_cases:
            with self.subTest(content=head_content):
                self.assertTrue(
                    git_dumper.is_valid_head(head_content),
                    f"BitBucket format should be valid: {repr(head_content)}"
                )


class TestResponseValidation(unittest.TestCase):
    """Test verify_response function"""

    def test_verify_response_html(self):
        """Test that HTML responses are rejected"""
        class MockResponse:
            status_code = 200
            headers = {"Content-Type": "text/html", "Content-Length": "100"}

        response = MockResponse()
        valid, error_msg = git_dumper.verify_response(response)
        self.assertFalse(valid)
        self.assertIn("HTML", error_msg)

    def test_verify_response_zero_length(self):
        """Test that zero-length responses are rejected"""
        class MockResponse:
            status_code = 200
            headers = {"Content-Length": 0}

        response = MockResponse()
        valid, error_msg = git_dumper.verify_response(response)
        self.assertFalse(valid)
        self.assertIn("zero-length", error_msg)

    def test_verify_response_non_200(self):
        """Test that non-200 status codes are rejected"""
        class MockResponse:
            status_code = 404
            headers = {}

        response = MockResponse()
        valid, error_msg = git_dumper.verify_response(response)
        self.assertFalse(valid)
        self.assertIn("404", error_msg)

    def test_verify_response_valid(self):
        """Test that valid responses are accepted"""
        class MockResponse:
            status_code = 200
            headers = {"Content-Length": "100"}

        response = MockResponse()
        valid, _ = git_dumper.verify_response(response)
        self.assertTrue(valid)


if __name__ == "__main__":
    unittest.main()
