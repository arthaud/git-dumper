#!/usr/bin/env python3
"""Tests for git_dumper.py"""

import unittest
from unittest.mock import Mock
import git_dumper


class TestIsHTML(unittest.TestCase):
    """Test is_html() function"""

    def test_is_html_with_html_content_type(self):
        """HTML content-type should return True"""
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        self.assertTrue(git_dumper.is_html(response))

    def test_is_html_with_charset(self):
        """HTML content-type with charset should return True"""
        response = Mock()
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.assertTrue(git_dumper.is_html(response))

    def test_is_html_without_html_content_type(self):
        """Non-HTML content-type should return False"""
        response = Mock()
        response.headers = {"Content-Type": "application/octet-stream"}
        self.assertFalse(git_dumper.is_html(response))

    def test_is_html_missing_content_type(self):
        """Missing content-type should return False"""
        response = Mock()
        response.headers = {}
        self.assertFalse(git_dumper.is_html(response))


class TestValidateGitContent(unittest.TestCase):
    """Test validate_git_content() function"""

    def test_validate_git_head_with_ref(self):
        """Valid HEAD file with ref should pass"""
        content = b"ref: refs/heads/master\n"
        self.assertTrue(git_dumper.validate_git_content(content, "HEAD"))

    def test_validate_git_head_with_sha1(self):
        """Valid HEAD file with SHA1 should pass"""
        content = b"a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0\n"
        self.assertTrue(git_dumper.validate_git_content(content, "HEAD"))

    def test_validate_git_head_with_html(self):
        """HEAD file with HTML should fail"""
        content = b"<html><body>404 Not Found</body></html>"
        self.assertFalse(git_dumper.validate_git_content(content, "HEAD"))

    def test_validate_git_ref_with_sha1(self):
        """Valid ref file with SHA1 should pass"""
        content = b"a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0\n"
        self.assertTrue(git_dumper.validate_git_content(content, ".git/refs/heads/master"))

    def test_validate_git_ref_with_html(self):
        """Ref file with HTML should fail"""
        content = b"<html><body>Not Found</body></html>"
        self.assertFalse(git_dumper.validate_git_content(content, ".git/refs/heads/master"))

    def test_validate_git_object_allows_any_binary(self):
        """Object files should allow any content (validated later by dulwich)"""
        content = b"\x78\x9c\x15\xc8\xc1\x09\x00\x00\x08\xc3"  # zlib compressed data
        self.assertTrue(git_dumper.validate_git_content(content, ".git/objects/ab/cdef"))

    def test_validate_git_config_allows_any(self):
        """Config files should allow any content"""
        content = b"[core]\n\trepositoryformatversion = 0\n"
        self.assertTrue(git_dumper.validate_git_content(content, ".git/config"))

    def test_validate_git_unknown_file_allows_any(self):
        """Unknown git files should allow any content"""
        content = b"some random content"
        self.assertTrue(git_dumper.validate_git_content(content, ".git/unknown"))


class TestVerifyResponse(unittest.TestCase):
    """Test verify_response() function"""

    def test_verify_response_200_ok(self):
        """Valid 200 response should pass"""
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/octet-stream"}
        valid, _ = git_dumper.verify_response(response)
        self.assertTrue(valid)

    def test_verify_response_404_fails(self):
        """404 response should fail"""
        response = Mock()
        response.status_code = 404
        response.headers = {}
        valid, msg = git_dumper.verify_response(response)
        self.assertFalse(valid)
        self.assertIn("404", msg)

    def test_verify_response_zero_length_fails(self):
        """Zero-length response should fail"""
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "0"}
        valid, msg = git_dumper.verify_response(response)
        self.assertFalse(valid)
        self.assertIn("zero-length", msg)

    def test_verify_response_html_with_git_validation_passes(self):
        """HTML content-type with valid git content should pass when validated"""
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html"}
        response.content = b"ref: refs/heads/master\n"
        valid, _ = git_dumper.verify_response(response, filepath=".git/HEAD")
        self.assertTrue(valid)

    def test_verify_response_html_with_invalid_git_content_fails(self):
        """HTML content-type with invalid git content should fail"""
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html"}
        response.content = b"<html><body>404 Not Found</body></html>"
        valid, msg = git_dumper.verify_response(response, filepath=".git/HEAD")
        self.assertFalse(valid)
        self.assertIn("HTML", msg)

    def test_verify_response_html_without_validation_fails(self):
        """HTML content-type without git validation should fail"""
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html"}
        response.content = b"ref: refs/heads/master\n"
        valid, msg = git_dumper.verify_response(response)
        self.assertFalse(valid)
        self.assertIn("HTML", msg)

    def test_verify_response_git_content_with_correct_content_type(self):
        """Git content with correct content-type should pass"""
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/octet-stream"}
        response.content = b"ref: refs/heads/master\n"
        valid, _ = git_dumper.verify_response(response, filepath=".git/HEAD")
        self.assertTrue(valid)


if __name__ == "__main__":
    unittest.main()
