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
Integration tests for audtag.
Tests complete workflows and CLI interactions.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
from click.testing import CliRunner
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Import with mocked mutagen
with patch('mutagen.File'):
    import audtag


class TestCLICommands(unittest.TestCase):
    """Test CLI command structure and execution."""
    
    def setUp(self):
        self.runner = CliRunner()
        self.test_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_cli_help(self):
        """Test CLI help command."""
        result = self.runner.invoke(audtag.cli, ['--help'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Tag audio files', result.output)
    
    @patch('mutagen.File')
    def test_info_command(self, mock_file):
        """Test info command."""
        # Create test file
        test_file = Path(self.test_dir) / "test.mp3"
        test_file.write_text("")
        
        # Mock audio file
        mock_audio = MagicMock()
        mock_audio.mime = ['audio/mpeg']
        mock_audio.info.length = 3600
        mock_audio.info.bitrate = 128000
        mock_audio.get.return_value = None
        mock_file.return_value = mock_audio
        
        result = self.runner.invoke(audtag.cli, ['info', str(test_file)])
        self.assertEqual(result.exit_code, 0)
    
    @patch('mutagen.File')
    @patch.object(audtag.AudibleScraper, 'search')
    @patch('inquirer.prompt')
    def test_tag_command_skip(self, mock_prompt, mock_search, mock_file):
        """Test tag command with skip action."""
        # Create test file
        test_file = Path(self.test_dir) / "test.mp3"
        test_file.write_text("")
        
        # Mock no search results
        mock_search.return_value = []
        
        # User chooses to skip
        mock_prompt.return_value = {'action': 'skip'}
        
        # Mock mutagen
        mock_file.return_value = MagicMock()
        
        result = self.runner.invoke(audtag.cli, ['tag', str(test_file)])
        self.assertEqual(result.exit_code, 0)


class TestTaggingWorkflow(unittest.TestCase):
    """Test complete tagging workflows."""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def create_test_file(self, name):
        """Helper to create test audio file."""
        file_path = Path(self.test_dir) / name
        file_path.write_text("")
        return file_path
    
    @patch('mutagen.File')
    @patch.object(audtag.AudibleScraper, 'search')
    @patch.object(audtag.AudibleScraper, 'get_book_details')
    @patch('inquirer.prompt')
    def test_single_file_tagging(self, mock_prompt, mock_details, mock_search, mock_file):
        """Test tagging a single file."""
        test_file = self.create_test_file("audiobook.mp3")
        
        # Mock search results
        mock_search.return_value = [
            {
                'title': 'Test Book',
                'authors': ['Test Author'],
                'url': 'http://audible.com/pd/test',
                'narrators': ['Test Narrator']
            }
        ]
        
        # Mock book details
        mock_details.return_value = {
            'title': 'Test Book Complete',
            'authors': ['Test Author'],
            'narrators': ['Test Narrator'],
            'year': '2024',
            'publisher': 'Test Publisher'
        }
        
        # User selects first result
        mock_prompt.return_value = {'selection': 0}
        
        # Mock mutagen file
        mock_audio = MagicMock()
        mock_audio.save = MagicMock()
        mock_file.return_value = mock_audio
        
        # Run tagging
        with patch('audtag.download_and_save_cover', return_value=True):
            audtag.tag_files([test_file])
        
        # Verify calls
        mock_search.assert_called_once()
        mock_details.assert_called_once()
        mock_audio.save.assert_called()
    
    @patch('mutagen.File')
    @patch.object(audtag.AudibleScraper, 'search')
    @patch('inquirer.prompt')
    def test_retry_search(self, mock_prompt, mock_search, mock_file):
        """Test retry search functionality."""
        test_file = self.create_test_file("book.mp3")
        
        # First search returns nothing, second returns results
        mock_search.side_effect = [
            [],  # No results first time
            [{'title': 'Found Book', 'url': 'url', 'authors': ['Author']}]  # Results on retry
        ]
        
        # User chooses to retry, then selects result
        mock_prompt.side_effect = [
            {'action': 'retry'},
            {'query': 'New Search'},
            {'selection': 0}
        ]
        
        mock_file.return_value = MagicMock()
        
        with patch.object(audtag.AudibleScraper, 'get_book_details', return_value={}):
            audtag.tag_files([test_file])
        
        # Verify search was called twice
        self.assertEqual(mock_search.call_count, 2)
    
    @patch('mutagen.File')
    def test_batch_processing(self, mock_file):
        """Test processing multiple files."""
        # Create multiple files
        files = []
        for i in range(5):
            files.append(self.create_test_file(f"book_{i}.mp3"))
        
        mock_audio = MagicMock()
        mock_audio.get.return_value = None
        mock_audio.tags = None
        mock_file.return_value = mock_audio
        
        # Test with skip all
        with patch.object(audtag.AudibleScraper, 'search', return_value=[]):
            with patch('inquirer.prompt', return_value={'action': 'skip'}):
                audtag.tag_files(files, workers=2)
        
        # All files should be processed
        self.assertEqual(mock_file.call_count, len(files))


class TestErrorHandling(unittest.TestCase):
    """Test error handling."""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.scraper = audtag.AudibleScraper()
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('requests.Session.get')
    def test_network_error_handling(self, mock_get):
        """Test handling of network errors."""
        mock_get.side_effect = Exception("Network error")
        
        # Should return empty list on error
        with patch('audtag.console.print'):
            results = self.scraper.search("Test")
            self.assertEqual(results, [])
    
    @patch('mutagen.File')
    def test_corrupted_file_handling(self, mock_file):
        """Test handling of corrupted audio files."""
        mock_file.side_effect = Exception("Invalid file")
        
        test_file = Path(self.test_dir) / "corrupted.mp3"
        test_file.write_text("corrupted data")
        
        # Should handle error gracefully
        with patch('audtag.console.print'):
            tagger = audtag.AudiobookTagger([test_file])
            # Should not crash
            self.assertIsNotNone(tagger)
    
    def test_missing_file_handling(self):
        """Test handling of missing files."""
        missing_file = Path(self.test_dir) / "nonexistent.mp3"
        
        # Should handle gracefully
        with patch('audtag.console.print'):
            with patch('mutagen.File'):
                tagger = audtag.AudiobookTagger([missing_file])
                self.assertIsNotNone(tagger)


if __name__ == '__main__':
    unittest.main(verbosity=2)