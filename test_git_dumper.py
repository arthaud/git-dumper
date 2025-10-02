#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock

# Mock requests_pkcs12 before importing git_dumper
sys.modules['requests_pkcs12'] = MagicMock()

import time
import requests
import git_dumper


class TestFindObjectsWorker(unittest.TestCase):
    """Test FindObjectsWorker for timeout handling"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.url = "http://example.com/.git"
        self.timeout = 3
        self.retry = 3
        self.http_headers = {}

    @patch('dulwich.objects.ShaFile.from_path')
    def test_chunked_download_works(self, mock_sha_file):
        """Test that chunked download works for valid objects"""
        # Mock the git object parsing to return empty references
        mock_obj = Mock()
        mock_sha_file.return_value = mock_obj

        with patch('git_dumper.get_referenced_sha1', return_value=[]):
            # Create a mock session
            mock_session = Mock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"Content-Type": "application/octet-stream"}

            # Simulate chunked content
            mock_response.iter_content = Mock(return_value=[b"test ", b"object ", b"content"])
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)
            mock_session.get.return_value = mock_response

            # Create worker and inject mock session
            worker = git_dumper.FindObjectsWorker(None, None, None)
            worker.session = mock_session

            # Test downloading an object
            obj = "1234567890abcdef1234567890abcdef12345678"
            result = worker.do_task(
                obj, self.url, self.temp_dir, self.retry, self.timeout, self.http_headers
            )

            # Verify file was created
            filepath = os.path.join(
                self.temp_dir, ".git", "objects", obj[:2], obj[2:]
            )
            self.assertTrue(os.path.exists(filepath))

            # Verify iter_content was called (chunked download)
            mock_response.iter_content.assert_called_once_with(4096)

    def test_timeout_on_hanging_response(self):
        """Test that timeout is triggered on hanging response"""
        # Create a mock session that hangs
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/octet-stream"}

        # Simulate hanging by raising timeout exception
        mock_session.get.side_effect = requests.exceptions.Timeout("Timeout")

        # Create worker and inject mock session
        worker = git_dumper.FindObjectsWorker(None, None, None)
        worker.session = mock_session

        # Test should handle timeout gracefully
        obj = "abcdef1234567890abcdef1234567890abcdef12"

        with self.assertRaises(requests.exceptions.Timeout):
            worker.do_task(
                obj, self.url, self.temp_dir, self.retry, self.timeout, self.http_headers
            )

    def test_404_object_handled_gracefully(self):
        """Test that 404 responses are handled without hanging"""
        # Create a mock session
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.headers = {}
        mock_session.get.return_value = mock_response

        # Create worker and inject mock session
        worker = git_dumper.FindObjectsWorker(None, None, None)
        worker.session = mock_session

        # Test downloading a missing object
        obj = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        result = worker.do_task(
            obj, self.url, self.temp_dir, self.retry, self.timeout, self.http_headers
        )

        # Should return empty list (no new objects found)
        self.assertEqual(result, [])

    def tearDown(self):
        # Cleanup temp directory
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)


class TestDownloadWorkerChunked(unittest.TestCase):
    """Verify DownloadWorker already uses chunked downloads"""

    def test_download_worker_uses_iter_content(self):
        """Verify DownloadWorker uses iter_content for chunked reading"""
        import inspect
        source = inspect.getsource(git_dumper.DownloadWorker.do_task)
        self.assertIn("iter_content", source)

    def test_find_objects_worker_should_use_iter_content(self):
        """Test that FindObjectsWorker uses iter_content (not response.content)"""
        import inspect
        source = inspect.getsource(git_dumper.FindObjectsWorker.do_task)
        # This test will FAIL until we fix the code
        self.assertIn("iter_content", source, 
                     "FindObjectsWorker should use iter_content for chunked downloads to prevent hanging")


if __name__ == "__main__":
    unittest.main()
