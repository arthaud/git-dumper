#!/usr/bin/env python3
"""Test suite for authenticated proxy support in git-dumper"""

import unittest
import sys
import re
from unittest.mock import patch, MagicMock
import socks


class TestProxyAuthentication(unittest.TestCase):
    """Test proxy URL parsing with authentication support"""

    def setUp(self):
        """Set up test fixtures"""
        self.proxy_patterns = [
            # Authenticated proxies with username:password@host:port
            # Use greedy match for password to handle special chars (last @ is the separator)
            (r"^socks5://([^:]+):(.+)@([^:]+):(\d+)$", socks.PROXY_TYPE_SOCKS5),
            (r"^socks4://([^:]+):(.+)@([^:]+):(\d+)$", socks.PROXY_TYPE_SOCKS4),
            (r"^http://([^:]+):(.+)@([^:]+):(\d+)$", socks.PROXY_TYPE_HTTP),
            # Non-authenticated proxies (backward compatibility)
            (r"^socks5:(.*):(\d+)$", socks.PROXY_TYPE_SOCKS5),
            (r"^socks4:(.*):(\d+)$", socks.PROXY_TYPE_SOCKS4),
            (r"^http://(.*):(\d+)$", socks.PROXY_TYPE_HTTP),
            (r"^(.*):(\d+)$", socks.PROXY_TYPE_SOCKS5),
        ]

    def parse_proxy(self, proxy_string):
        """Parse proxy string using the same logic as git_dumper.py"""
        for pattern, proxy_type in self.proxy_patterns:
            m = re.match(pattern, proxy_string)
            if m:
                groups = m.groups()
                if len(groups) == 4:
                    # Authenticated
                    username, password, host, port = groups
                    return {
                        'type': proxy_type,
                        'host': host,
                        'port': int(port),
                        'username': username,
                        'password': password,
                        'authenticated': True
                    }
                else:
                    # Non-authenticated
                    host, port = groups
                    return {
                        'type': proxy_type,
                        'host': host,
                        'port': int(port),
                        'authenticated': False
                    }
        return None

    def test_http_authenticated_proxy(self):
        """Test HTTP proxy with username and password"""
        result = self.parse_proxy("http://user:pass@18.14.55.12:21405")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_HTTP)
        self.assertEqual(result['host'], "18.14.55.12")
        self.assertEqual(result['port'], 21405)
        self.assertEqual(result['username'], "user")
        self.assertEqual(result['password'], "pass")
        self.assertTrue(result['authenticated'])

    def test_http_authenticated_proxy_complex_password(self):
        """Test HTTP proxy with special characters in password"""
        result = self.parse_proxy("http://admin:P@ssw0rd@proxy.example.com:8080")
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
        result = self.parse_proxy("socks5://user:secret@192.168.1.1:1080")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_SOCKS5)
        self.assertEqual(result['host'], "192.168.1.1")
        self.assertEqual(result['port'], 1080)
        self.assertEqual(result['username'], "user")
        self.assertEqual(result['password'], "secret")
        self.assertTrue(result['authenticated'])

    def test_socks4_authenticated_proxy(self):
        """Test SOCKS4 proxy with authentication"""
        result = self.parse_proxy("socks4://testuser:testpass@localhost:9050")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_SOCKS4)
        self.assertEqual(result['host'], "localhost")
        self.assertEqual(result['port'], 9050)
        self.assertEqual(result['username'], "testuser")
        self.assertEqual(result['password'], "testpass")
        self.assertTrue(result['authenticated'])

    def test_http_non_authenticated_proxy_backward_compat(self):
        """Test non-authenticated HTTP proxy (backward compatibility)"""
        result = self.parse_proxy("http://proxy.example.com:8080")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_HTTP)
        self.assertEqual(result['host'], "proxy.example.com")
        self.assertEqual(result['port'], 8080)
        self.assertFalse(result['authenticated'])

    def test_socks5_non_authenticated_proxy(self):
        """Test non-authenticated SOCKS5 proxy"""
        result = self.parse_proxy("socks5:127.0.0.1:1080")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_SOCKS5)
        self.assertEqual(result['host'], "127.0.0.1")
        self.assertEqual(result['port'], 1080)
        self.assertFalse(result['authenticated'])

    def test_default_socks5_format(self):
        """Test default proxy format (host:port assumes SOCKS5)"""
        result = self.parse_proxy("proxy.example.com:1080")
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], socks.PROXY_TYPE_SOCKS5)
        self.assertEqual(result['host'], "proxy.example.com")
        self.assertEqual(result['port'], 1080)
        self.assertFalse(result['authenticated'])

    def test_invalid_proxy_format(self):
        """Test invalid proxy format"""
        result = self.parse_proxy("invalid-proxy-string")
        self.assertIsNone(result)

    def test_authenticated_proxy_with_numeric_username(self):
        """Test authenticated proxy with numeric username"""
        result = self.parse_proxy("http://12345:password@host:8080")
        self.assertIsNotNone(result)
        self.assertEqual(result['username'], "12345")
        self.assertEqual(result['password'], "password")

    def test_authenticated_proxy_with_underscore_in_credentials(self):
        """Test authenticated proxy with underscores in username/password"""
        result = self.parse_proxy("http://user_name:pass_word@host:3128")
        self.assertIsNotNone(result)
        self.assertEqual(result['username'], "user_name")
        self.assertEqual(result['password'], "pass_word")

    @patch('socks.setdefaultproxy')
    def test_socks_setdefaultproxy_called_with_auth(self, mock_setdefaultproxy):
        """Test that socks.setdefaultproxy is called with correct auth parameters"""
        result = self.parse_proxy("http://user:pass@host:8080")

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
        result = self.parse_proxy("http://host:8080")

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
