#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
#     "mutagen",
#     "rich",
#     "click",
#     "inquirer",
# ]
# ///
"""
Core functionality tests for audtag.
Tests the main components without complex mocking.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
import sys
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Import with mocked mutagen
with patch('mutagen.File'):
    import audtag


class TestAudibleScraper(unittest.TestCase):
    """Test AudibleScraper functionality."""
    
    def setUp(self):
        self.scraper = audtag.AudibleScraper()
    
    def test_initialization(self):
        """Test scraper initializes correctly."""
        self.assertIsNotNone(self.scraper.session)
        self.assertEqual(self.scraper.BASE_URL, "https://www.audible.com")
        self.assertIn('User-Agent', self.scraper.session.headers)
    
    @patch('requests.Session.get')
    def test_search_returns_list(self, mock_get):
        """Test search always returns a list."""
        mock_response = Mock()
        mock_response.text = "<html><body></body></html>"
        mock_get.return_value = mock_response
        
        results = self.scraper.search("test query")
        self.assertIsInstance(results, list)
    
    @patch('requests.Session.get')
    def test_search_parses_results(self, mock_get):
        """Test search parses HTML correctly."""
        mock_response = Mock()
        mock_response.text = '''
        <html><body>
            <li class="productListItem">
                <h3 class="bc-heading">
                    <a href="/pd/Test-Book/1234567890">Test Book Title</a>
                </h3>
                <li class="authorLabel">
                    <a href="/author/Test-Author">Test Author</a>
                </li>
                <li class="narratorLabel">
                    <a href="/search?searchNarrator=Test+Narrator">Test Narrator</a>
                </li>
            </li>
        </body></html>
        '''
        mock_get.return_value = mock_response
        
        results = self.scraper.search("test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Test Book Title')
        self.assertEqual(results[0]['authors'], ['Test Author'])
        self.assertEqual(results[0]['narrators'], ['Test Narrator'])
    
    @patch('requests.Session.get')
    def test_get_book_details(self, mock_get):
        """Test fetching book details."""
        mock_response = Mock()
        mock_response.text = '''
        <html><body>
            <h1 slot="title">Detailed Book Title</h1>
            <li class="authorLabel">
                <a>Author Name</a>
            </li>
            <li class="narratorLabel">
                <a>Narrator Name</a>
            </li>
            <li class="publisherLabel">
                <a>Publisher Name</a>
            </li>
        </body></html>
        '''
        mock_get.return_value = mock_response
        
        details = self.scraper.get_book_details("https://audible.com/pd/test")
        
        self.assertIsInstance(details, dict)
        self.assertEqual(details['title'], 'Detailed Book Title')
        self.assertEqual(details['authors'], ['Author Name'])
        self.assertEqual(details['narrators'], ['Narrator Name'])
        self.assertEqual(details['publisher'], 'Publisher Name')


class TestAudiobookTagger(unittest.TestCase):
    """Test AudiobookTagger functionality."""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_file = Path(self.test_dir) / "test.mp3"
        self.test_file.write_text("")
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('mutagen.File')
    def test_initialization(self, mock_file):
        """Test tagger initializes correctly."""
        mock_file.return_value = MagicMock()
        tagger = audtag.AudiobookTagger([self.test_file])
        
        self.assertEqual(tagger.files, [self.test_file])
        self.assertIn('.mp3', tagger.formats)
    
    @patch('mutagen.File')
    def test_apply_metadata(self, mock_file):
        """Test applying metadata to files."""
        mock_audio = MagicMock()
        mock_audio.save = MagicMock()
        mock_file.return_value = mock_audio
        
        tagger = audtag.AudiobookTagger([self.test_file])
        
        metadata = {
            'title': 'Test Book',
            'authors': ['Test Author'],
            'narrators': ['Test Narrator'],
            'year': '2024',
            'publisher': 'Test Publisher'
        }
        
        # Should not raise an exception
        tagger.apply_metadata(metadata, self.test_file)
        mock_audio.save.assert_called()


class TestFileGrouping(unittest.TestCase):
    """Test file grouping functionality."""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('mutagen.File')
    def test_group_single_file(self, mock_file):
        """Test grouping a single file."""
        test_file = Path(self.test_dir) / "book.mp3"
        test_file.write_text("")
        
        mock_file.return_value = MagicMock(get=lambda *args: None, tags=None)
        
        groups = audtag.group_files_by_book([test_file])
        
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]['files']), 1)
        self.assertEqual(groups[0]['files'][0], test_file)
    
    @patch('mutagen.File')
    def test_group_files_by_directory(self, mock_file):
        """Test grouping files by directory."""
        # Create subdirectories with files
        book1_dir = Path(self.test_dir) / "Book1"
        book2_dir = Path(self.test_dir) / "Book2"
        book1_dir.mkdir()
        book2_dir.mkdir()
        
        files = []
        for i in range(2):
            file1 = book1_dir / f"chapter{i+1}.mp3"
            file2 = book2_dir / f"part{i+1}.mp3"
            file1.write_text("")
            file2.write_text("")
            files.extend([file1, file2])
        
        mock_file.return_value = MagicMock(get=lambda *args: None, tags=None)
        
        groups = audtag.group_files_by_book(files)
        
        # Should create 2 groups (one per directory)
        self.assertEqual(len(groups), 2)
        
        # Each group should have 2 files
        for group in groups:
            self.assertEqual(len(group['files']), 2)
    
    @patch('mutagen.File')
    def test_group_files_same_directory(self, mock_file):
        """Test grouping files in same directory."""
        files = []
        for i in range(3):
            test_file = Path(self.test_dir) / f"chapter{i+1}.mp3"
            test_file.write_text("")
            files.append(test_file)
        
        mock_file.return_value = MagicMock(get=lambda *args: None, tags=None)
        
        groups = audtag.group_files_by_book(files)
        
        # Files in same directory with similar names should group together
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]['files']), 3)


class TestCoverDownload(unittest.TestCase):
    """Test cover art download functionality."""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('requests.get')
    def test_download_success(self, mock_get):
        """Test successful cover download."""
        # Create fake image data (>1000 bytes)
        fake_image = b'FAKE_IMAGE_DATA' * 100
        
        mock_response = Mock()
        mock_response.content = fake_image
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        save_path = Path(self.test_dir) / "cover.jpg"
        result = audtag.download_and_save_cover("http://example.com/image.jpg", save_path)
        
        self.assertTrue(result)
        self.assertTrue(save_path.exists())
        self.assertEqual(save_path.read_bytes(), fake_image)
    
    @patch('requests.get')
    def test_download_small_file_rejected(self, mock_get):
        """Test that small files (placeholders) are rejected."""
        # Create small data (<1000 bytes)
        small_data = b'SMALL'
        
        mock_response = Mock()
        mock_response.content = small_data
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        save_path = Path(self.test_dir) / "cover.jpg"
        result = audtag.download_and_save_cover("http://example.com/image.jpg", save_path)
        
        self.assertFalse(result)
        self.assertFalse(save_path.exists())
    
    @patch('requests.get')
    def test_download_network_error(self, mock_get):
        """Test handling network errors gracefully."""
        mock_get.side_effect = Exception("Network error")
        
        save_path = Path(self.test_dir) / "cover.jpg"
        result = audtag.download_and_save_cover("http://example.com/image.jpg", save_path)
        
        self.assertFalse(result)
        self.assertFalse(save_path.exists())


class TestUtilityFunctions(unittest.TestCase):
    """Test utility functions."""
    
    def test_get_optimal_workers(self):
        """Test optimal worker calculation."""
        workers = audtag.get_optimal_workers()
        
        self.assertIsInstance(workers, int)
        self.assertGreater(workers, 0)
        self.assertLessEqual(workers, 16)
    
    @patch('os.cpu_count')
    def test_get_optimal_workers_different_cpus(self, mock_cpu):
        """Test optimal workers with different CPU counts."""
        # Test with 4 CPUs
        mock_cpu.return_value = 4
        self.assertEqual(audtag.get_optimal_workers(), 8)
        
        # Test with 16 CPUs (should cap at 16)
        mock_cpu.return_value = 16
        self.assertEqual(audtag.get_optimal_workers(), 16)
        
        # Test with None (fallback)
        mock_cpu.return_value = None
        self.assertEqual(audtag.get_optimal_workers(), 4)


if __name__ == '__main__':
    unittest.main(verbosity=2)