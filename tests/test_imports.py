#!/usr/bin/env python3
"""Test that imports work correctly on Python 3.10+"""
import sys
import unittest


class TestImports(unittest.TestCase):
    """Test module imports work on Python 3.10+"""

    def test_socks_import_no_collections_error(self):
        """Test that PySocks can be imported without collections.Callable error"""
        try:
            import socks
            self.assertTrue(hasattr(socks, 'socksocket'))
        except ImportError as e:
            if 'Callable' in str(e) and 'collections' in str(e):
                self.fail(f"PySocks has collections.Callable issue (needs PySocks>=1.7.1): {e}")
            raise

    def test_collections_abc_callable_available(self):
        """Test that collections.abc.Callable is available (Python 3.3+)"""
        from collections.abc import Callable
        self.assertTrue(callable(Callable))

    def test_python_version_compatibility(self):
        """Verify we're testing on Python 3.0+"""
        version_info = sys.version_info
        self.assertGreaterEqual(
            version_info.major * 10 + version_info.minor,
            30,  # Python 3.0+
            "Should work on Python 3.0+"
        )


if __name__ == '__main__':
    unittest.main()
