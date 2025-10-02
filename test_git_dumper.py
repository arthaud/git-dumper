#!/usr/bin/env python3
"""Tests for git_dumper.py - focusing on redirect handling"""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock
import sys

# Import the module to test
import git_dumper


class TestRecursiveDownloadWorkerRedirects(unittest.TestCase):
    """Test redirect handling in RecursiveDownloadWorker"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.url = "http://example.com"
        self.worker = git_dumper.RecursiveDownloadWorker(
            pending_tasks=MagicMock(),
            tasks_done=MagicMock(),
            args=(self.url, self.temp_dir, 3, 10, {})
        )
        self.worker.init(self.url, self.temp_dir, 3, 10, {})

    def tearDown(self):
        """Clean up test fixtures"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch('git_dumper.printf')
    def test_redirect_to_same_path_creates_loop_prevention(self, mock_printf):
        """Test that redirecting to same path is detected and prevented"""
        # Simulate a 301 redirect that points back to itself
        mock_response = Mock()
        mock_response.status_code = 301
        mock_response.headers = {
            'Location': '.git/objects/info/packs/'
        }

        with patch.object(self.worker.session, 'get', return_value=mock_response) as mock_get:
            mock_get.return_value.__enter__ = Mock(return_value=mock_response)
            mock_get.return_value.__exit__ = Mock(return_value=False)

            # First call - should return the redirect
            result1 = self.worker.do_task(
                '.git/objects/info/packs',
                self.url,
                self.temp_dir,
                3,
                10,
                {}
            )

            # Should queue the redirect
            self.assertEqual(result1, ['.git/objects/info/packs/'])

            # Second call with same redirect - should detect circular redirect
            result2 = self.worker.do_task(
                '.git/objects/info/packs/',
                self.url,
                self.temp_dir,
                3,
                10,
                {}
            )

            # Should stop the loop (return empty)
            self.assertEqual(result2, [])

    @patch('git_dumper.printf')
    def test_max_redirect_limit(self, mock_printf):
        """Test that max redirect counter prevents infinite loops"""
        # Simulate the same path redirecting to itself repeatedly
        mock_response = Mock()
        mock_response.status_code = 301
        mock_response.headers = {
            'Location': '.git/test/'
        }
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch.object(self.worker.session, 'get', return_value=mock_response):
            # Process the same redirect multiple times
            filepath = '.git/test'
            results = []
            
            for i in range(10):
                result = self.worker.do_task(
                    filepath,
                    self.url,
                    self.temp_dir,
                    3,
                    10,
                    {}
                )
                results.append(result)
                
                # After first redirect, it should detect circular redirect and stop
                if i == 0:
                    self.assertEqual(result, ['.git/test/'])
                else:
                    # Subsequent attempts should be blocked
                    self.assertEqual(result, [])
                    break

    @patch('git_dumper.printf')
    def test_valid_redirect_is_allowed(self, mock_printf):
        """Test that valid redirects (e.g., dir -> dir/) are allowed once"""
        mock_response = Mock()
        mock_response.status_code = 301
        mock_response.headers = {
            'Location': '.git/objects/info/'
        }
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch.object(self.worker.session, 'get', return_value=mock_response):
            result = self.worker.do_task(
                '.git/objects/info',
                self.url,
                self.temp_dir,
                3,
                10,
                {}
            )

            # Should return the redirected path
            self.assertEqual(result, ['.git/objects/info/'])

    @patch('git_dumper.printf')
    def test_redirect_to_different_location_stops(self, mock_printf):
        """Test that redirect to unrelated location (e.g., homepage) stops processing"""
        mock_response = Mock()
        mock_response.status_code = 301
        mock_response.headers = {
            'Location': '/index.html'  # Redirects to homepage, not filepath + "/"
        }
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch.object(self.worker.session, 'get', return_value=mock_response):
            result = self.worker.do_task(
                '.git/objects/info/packs',
                self.url,
                self.temp_dir,
                3,
                10,
                {}
            )

            # Should not follow redirect to unrelated location
            self.assertEqual(result, [])

    @patch('git_dumper.printf')
    def test_multiple_different_paths_max_redirects(self, mock_printf):
        """Test that each path has its own redirect counter"""
        mock_response = Mock()
        mock_response.status_code = 301
        
        def set_location(*args, **kwargs):
            # Extract filepath from URL
            url_path = args[0] if args else kwargs.get('url', '')
            if '.git/path1' in url_path:
                mock_response.headers = {'Location': '.git/path1/'}
            elif '.git/path2' in url_path:
                mock_response.headers = {'Location': '.git/path2/'}
            return mock_response
        
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch.object(self.worker.session, 'get', side_effect=set_location):
            # First path should work
            result1 = self.worker.do_task('.git/path1', self.url, self.temp_dir, 3, 10, {})
            self.assertEqual(result1, ['.git/path1/'])
            
            # Different path should also work
            result2 = self.worker.do_task('.git/path2', self.url, self.temp_dir, 3, 10, {})
            self.assertEqual(result2, ['.git/path2/'])


if __name__ == '__main__':
    unittest.main()
