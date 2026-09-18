"""Unit tests for app.utils.path_filter.

Run from the project root with:
    python -m unittest tests.test_check_path -v
"""

import unittest

from app.utils.path_filter import is_excluded


class TestCheckPathIsExcluded(unittest.TestCase):

    def test_no_exclude_patterns(self):
        """Test that nothing is excluded when the pattern list is empty."""
        self.assertFalse(is_excluded("C:\\Users\\test\\file.txt", []))

    def test_filename_pattern_match(self):
        """Test exclusion by filename pattern (e.g., *.tmp)."""
        patterns = ["*.tmp", "*.log"]
        self.assertTrue(is_excluded("C:\\Users\\test\\some_file.tmp", patterns))
        self.assertTrue(is_excluded("C:\\Users\\test\\another_file.log", patterns))
        self.assertFalse(is_excluded("C:\\Users\\test\\document.txt", patterns))

    def test_filename_exact_match(self):
        """Test exclusion by exact filename (e.g., Thumbs.db)."""
        patterns = ["Thumbs.db", ".DS_Store"]
        self.assertTrue(is_excluded("C:\\Users\\test\\images\\Thumbs.db", patterns))
        self.assertTrue(is_excluded("C:\\Users\\test\\.DS_Store", patterns))
        self.assertFalse(is_excluded("C:\\Users\\test\\image.jpg", patterns))

    def test_parent_folder_match(self):
        """Test exclusion by a parent directory name (e.g., .git)."""
        patterns = [".git", "node_modules"]
        self.assertTrue(is_excluded("C:\\project\\.git\\config", patterns))
        self.assertTrue(is_excluded("C:\\project\\node_modules\\library\\index.js", patterns))
        self.assertFalse(is_excluded("C:\\project\\src\\app.js", patterns))

    def test_partial_folder_match(self):
        """Test exclusion by a partial/wildcard directory name (e.g., *cache*)."""
        patterns = ["*cache*", "**/build*/*"]
        self.assertTrue(is_excluded("C:\\Users\\test\\.app-cache\\data", patterns))
        self.assertTrue(is_excluded("C:\\project\\build-output\\app.exe", patterns))
        self.assertFalse(is_excluded("C:\\project\\source\\main.py", patterns))

    def test_no_match(self):
        """Test that a path is not excluded if it doesn't match any pattern."""
        patterns = ["*.tmp", ".git", "dist"]
        self.assertFalse(is_excluded("C:\\Users\\test\\documents\\report.docx", patterns))
        self.assertFalse(is_excluded("C:\\git-project\\src\\main.c", patterns))

    def test_file_in_root(self):
        """Test a file in the root directory."""
        patterns = ["config.sys"]
        self.assertTrue(is_excluded("C:\\config.sys", patterns))
        self.assertFalse(is_excluded("C:\\boot.ini", patterns))

    def test_multiple_patterns_one_match(self):
        """Test with multiple patterns where only one should match."""
        patterns = ["*.obj", "*.pdb", "*.exe", "*.dll"]
        self.assertTrue(is_excluded("C:\\project\\release\\program.exe", patterns))

    def test_complex_path_with_match(self):
        """Test a deep path with a matching directory."""
        patterns = ["temp_files"]
        path = "D:\\data\\processing\\step1\\temp_files\\run_123\\output.log"
        self.assertTrue(is_excluded(path, patterns))

    def test_unix_style_paths(self):
        """Test with Unix-style paths."""
        patterns = ["build", "*.o"]
        self.assertTrue(is_excluded("/project/build/app", patterns))
        self.assertTrue(is_excluded("/build/app", patterns))
        self.assertFalse(is_excluded("/project/builder/app", patterns))
        self.assertTrue(is_excluded("/project/src/main.o", patterns))
        self.assertFalse(is_excluded("/project/src/main.c", patterns))

    def test_windows_style_subpaths(self):
        """Test with Unix-style paths."""
        patterns = ["**/build/app1/*"]
        self.assertTrue(is_excluded("D:\\project\\build\\app1\\blabla.txt", patterns))
        self.assertFalse(is_excluded("D:\\project\\build\\blabla.txt", patterns))
        self.assertFalse(is_excluded("D:\\project\\build\\app2\\blabla.txt", patterns))

if __name__ == '__main__':
    unittest.main()
