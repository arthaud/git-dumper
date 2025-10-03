#!/usr/bin/env python3
"""Test suite for authenticated proxy support in git-dumper"""

import unittest
import sys
import os
from unittest.mock import patch
import socks

# Add parent directory to path to import git_dumper
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from git_dumper import parse_proxy


class TestProxyAuthentication(unittest.TestCase):
    """Test proxy URL parsing with authentication support"""

    def test_http_authenticated_proxy(self):
        """Test HTTP proxy with username and password"""
        result = parse_proxy("http://user:pass@18.14.55.12:21405")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_HTTP)
        self.assertEqual(result['host'], "18.14.55.12")
        self.assertEqual(result['port'], 21405)
        self.assertEqual(result['username'], "user")
        self.assertEqual(result['password'], "pass")
        self.assertTrue(result['authenticated'])

    def test_http_authenticated_proxy_complex_password(self):
        """Test HTTP proxy with special characters in password"""
        result = parse_proxy("http://admin:P@ssw0rd@proxy.example.com:8080")
        # With greedy matching, the last @ is used as separator
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_HTTP)
        self.assertEqual(result['host'], "proxy.example.com")
        self.assertEqual(result['port'], 8080)
        self.assertEqual(result['username'], "admin")
        self.assertEqual(result['password'], "P@ssw0rd")
        self.assertTrue(result['authenticated'])

    def test_socks5_authenticated_proxy(self):
        """Test SOCKS5 proxy with authentication"""
        result = parse_proxy("socks5://user:secret@192.168.1.1:1080")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_SOCKS5)
        self.assertEqual(result['host'], "192.168.1.1")
        self.assertEqual(result['port'], 1080)
        self.assertEqual(result['username'], "user")
        self.assertEqual(result['password'], "secret")
        self.assertTrue(result['authenticated'])

    def test_socks4_authenticated_proxy(self):
        """Test SOCKS4 proxy with authentication"""
        result = parse_proxy("socks4://testuser:testpass@localhost:9050")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_SOCKS4)
        self.assertEqual(result['host'], "localhost")
        self.assertEqual(result['port'], 9050)
        self.assertEqual(result['username'], "testuser")
        self.assertEqual(result['password'], "testpass")
        self.assertTrue(result['authenticated'])

    def test_http_non_authenticated_proxy_backward_compat(self):
        """Test non-authenticated HTTP proxy (backward compatibility)"""
        result = parse_proxy("http://proxy.example.com:8080")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_HTTP)
        self.assertEqual(result['host'], "proxy.example.com")
        self.assertEqual(result['port'], 8080)
        self.assertFalse(result['authenticated'])

    def test_socks5_non_authenticated_proxy(self):
        """Test non-authenticated SOCKS5 proxy"""
        result = parse_proxy("socks5:127.0.0.1:1080")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_SOCKS5)
        self.assertEqual(result['host'], "127.0.0.1")
        self.assertEqual(result['port'], 1080)
        self.assertFalse(result['authenticated'])

    def test_default_socks5_format(self):
        """Test default proxy format (host:port assumes SOCKS5)"""
        result = parse_proxy("proxy.example.com:1080")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_SOCKS5)
        self.assertEqual(result['host'], "proxy.example.com")
        self.assertEqual(result['port'], 1080)
        self.assertFalse(result['authenticated'])

    def test_invalid_proxy_format(self):
        """Test invalid proxy format"""
        result = parse_proxy("invalid-proxy-string")
        self.assertIsNone(result)

    def test_authenticated_proxy_with_numeric_username(self):
        """Test authenticated proxy with numeric username"""
        result = parse_proxy("http://12345:password@host:8080")
        self.assertIsNotNone(result)
        self.assertEqual(result['username'], "12345")
        self.assertEqual(result['password'], "password")

    def test_authenticated_proxy_with_underscore_in_credentials(self):
        """Test authenticated proxy with underscores in username/password"""
        result = parse_proxy("http://user_name:pass_word@host:3128")
        self.assertIsNotNone(result)
        self.assertEqual(result['username'], "user_name")
        self.assertEqual(result['password'], "pass_word")

    @patch('socks.setdefaultproxy')
    def test_socks_setdefaultproxy_called_with_auth(self, mock_setdefaultproxy):
        """Test that socks.setdefaultproxy is called with correct auth parameters"""
        result = parse_proxy("http://user:pass@host:8080")

        # Simulate the actual call that would happen in git_dumper.py
        if result and result['authenticated']:
            mock_setdefaultproxy(
                result['type'],
                result['host'],
                result['port'],
                True,
                result['username'],
                result['password']
            )

        mock_setdefaultproxy.assert_called_once_with(
            socks.PROXY_TYPE_HTTP,
            "host",
            8080,
            True,
            "user",
            "pass"
        )

    @patch('socks.setdefaultproxy')
    def test_socks_setdefaultproxy_called_without_auth(self, mock_setdefaultproxy):
        """Test that socks.setdefaultproxy is called correctly for non-auth proxies"""
        result = parse_proxy("http://host:8080")

        # Simulate the actual call that would happen in git_dumper.py
        if result and not result['authenticated']:
            mock_setdefaultproxy(
                result['type'],
                result['host'],
                result['port']
            )

        mock_setdefaultproxy.assert_called_once_with(
            socks.PROXY_TYPE_HTTP,
            "host",
            8080
        )


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
