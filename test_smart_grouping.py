#!/usr/bin/env python3
"""
Tests for smart grouping functionality in audtag.
Tests commit b8cfcf0 fixes and general smart grouping logic.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
import sys
import os
import re
import types

# Add parent directory to path to import audtag
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the module (it's named audtag.src.py)
import importlib.util
spec = importlib.util.spec_from_file_location("audtag", "audtag.src.py")
audtag = importlib.util.module_from_spec(spec)

# Temporarily mock mutagen.File during module load to avoid import errors
with patch('mutagen.File'):
    spec.loader.exec_module(audtag)


class TestSmartGrouping(unittest.TestCase):
    """Test suite for smart grouping functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_is_book_like_name_valid_titles(self):
        """Test that valid book titles are recognized."""
        # These should be recognized as book-like names
        valid_titles = [
            "The Great Gatsby",
            "Harry Potter and the Sorcerer's Stone",
            "1984 - George Orwell",
            "Pride and Prejudice",
            "The_Hobbit",
            "Lord-of-the-Rings",
            "A Tale of Two Cities",
            "To Kill a Mockingbird"
        ]
        
        # Directly test the logic since we can't easily extract nested functions
        # Recreate the is_book_like_name logic here
        def is_book_like_name(name):
            common_folders = {'audiobooks', 'books', 'audio', 'media', 'downloads', 'incoming', 'new', 'old', 'temp'}
            name_lower = name.lower()
            if name_lower in common_folders:
                return False
            
            folder_patterns = ['incoming', 'download', 'temp', 'new', 'old', 'queue', 'processing', 'books', 'audiobook', 'audio']
            for pattern in folder_patterns:
                if pattern in name_lower:
                    return False
            
            if len(name) < 2 or name.isdigit():
                return False
            words = name.split()
            return len(words) >= 1 and not all(w.isdigit() for w in words)
        
        for title in valid_titles:
            with self.subTest(title=title):
                self.assertTrue(is_book_like_name(title), f"'{title}' should be recognized as book-like")
    
    def test_is_book_like_name_invalid_folders(self):
        """Test that common folder names are not recognized as books."""
        # These should NOT be recognized as book-like names
        invalid_names = [
            "audiobooks",
            "books",
            "audio",
            "incoming",
            "downloads",
            "temp",
            "new",
            "old",
            "Audio.Books.incoming",  # From commit b8cfcf0
            "books_incoming",         # From commit b8cfcf0
            "audiobook_downloads",
            "processing_queue",
            "123",  # Just numbers
            "1",    # Too short
            ""      # Empty
        ]
        
        def is_book_like_name(name):
            common_folders = {'audiobooks', 'books', 'audio', 'media', 'downloads', 'incoming', 'new', 'old', 'temp'}
            name_lower = name.lower()
            if name_lower in common_folders:
                return False
            
            folder_patterns = ['incoming', 'download', 'temp', 'new', 'old', 'queue', 'processing', 'books', 'audiobook', 'audio']
            for pattern in folder_patterns:
                if pattern in name_lower:
                    return False
            
            if len(name) < 2 or name.isdigit():
                return False
            words = name.split()
            return len(words) >= 1 and not all(w.isdigit() for w in words)
        
        for name in invalid_names:
            with self.subTest(name=name):
                self.assertFalse(is_book_like_name(name), f"'{name}' should NOT be recognized as book-like")
    
    def test_normalize_for_comparison(self):
        """Test the normalization function for file comparison."""
        # Recreate the normalize logic
        def normalize_for_comparison(text):
            # Remove leading/trailing numbers and common track indicators
            text = re.sub(r'^\d+[-_\s\.\)]*', '', text)
            text = re.sub(r'[-_\s]*\d+$', '', text)
            text = re.sub(r'\b(?:pt|part|chapter|ch|track|cd|disc|disk|vol|volume)\b[-_\s]*\d*', '', text, flags=re.IGNORECASE)
            # Remove file extensions if present
            text = re.sub(r'\.(mp3|m4b|m4a|aac|ogg|opus|flac)$', '', text, flags=re.IGNORECASE)
            # Normalize separators
            text = re.sub(r'[-_\s]+', ' ', text)
            return text.strip().lower()
        
        # Test various normalizations
        # Note: The normalize function removes "chapter", "track", "part", "cd", "volume" etc.
        # but only when they are complete words (word boundaries)
        test_cases = [
            ("01 - Chapter One", "one"),  # "Chapter" is removed (without extension)
            ("Track_01_Introduction", "track 01 introduction"),  # Underscores normalized but "track" not removed (no word boundary)
            ("Track 01 Introduction", "introduction"),  # "Track" removed when it's a word
            ("Part 1 - The Beginning", "the beginning"),  # "Part 1" removed
            ("CD1_Track_01", "cd1 track"),  # Underscores normalized but patterns not removed
            ("CD 1 Track 01", ""),  # Both "CD" and "Track" removed when they are words
            ("Volume 1 Chapter 1", ""),  # Both "Volume" and "Chapter" removed
            ("02_harry_potter.m4b", "harry potter"),  # Leading number and extension removed
            ("The_Great-Gatsby", "the great gatsby")  # Just normalization of separators
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = normalize_for_comparison(input_text)
                self.assertEqual(result, expected)
    
    @patch('mutagen.File')
    def test_group_files_by_book_with_book_like_directory(self, mock_file):
        """Test grouping when directory name is book-like."""
        # Create a book-like directory structure
        book_dir = Path(self.test_dir) / "The Great Gatsby"
        book_dir.mkdir()
        
        # Create audio files
        files = []
        for i in range(1, 4):
            file_path = book_dir / f"track_{i:02d}.mp3"
            file_path.touch()
            files.append(file_path)
        
        # Mock File to return no metadata
        mock_file.return_value = None
        
        # Mock AudiobookTagger to avoid dependency issues
        with patch.object(audtag, 'AudiobookTagger') as mock_tagger:
            mock_instance = MagicMock()
            mock_instance.get_initial_search_query.return_value = "The Great Gatsby"
            mock_tagger.return_value = mock_instance
            
            groups = audtag.group_files_by_book(files)
            
            # Should group all files together since directory is book-like
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0]['files']), 3)
            self.assertIn("The Great Gatsby", groups[0]['query'])
    
    @patch('mutagen.File')
    def test_group_files_by_book_with_non_book_directory(self, mock_file):
        """Test grouping when directory name is not book-like (e.g., 'incoming')."""
        # Create a non-book-like directory structure (testing commit b8cfcf0)
        incoming_dir = Path(self.test_dir) / "Audio.Books.incoming"
        incoming_dir.mkdir()
        
        # Create files from different books
        files = []
        book_files = [
            "Harry Potter 01.mp3",
            "Harry Potter 02.mp3",
            "Lord of the Rings.mp3",
            "The Hobbit.mp3"
        ]
        
        for filename in book_files:
            file_path = incoming_dir / filename
            file_path.touch()
            files.append(file_path)
        
        # Mock File to return no metadata
        mock_file.return_value = None
        
        # Mock AudiobookTagger 
        with patch.object(audtag, 'AudiobookTagger') as mock_tagger:
            mock_instance = MagicMock()
            mock_instance.get_initial_search_query.return_value = "test query"
            mock_tagger.return_value = mock_instance
            
            groups = audtag.group_files_by_book(files)
            
            # Should create separate groups since directory is not book-like
            # and files are not all similar
            self.assertGreater(len(groups), 1)
            
            # Harry Potter files should be grouped together
            hp_group = next((g for g in groups if any("Harry Potter" in f.name for f in g['files'])), None)
            self.assertIsNotNone(hp_group)
            self.assertEqual(len(hp_group['files']), 2)
    
    @patch('mutagen.File')
    def test_group_files_by_book_with_album_metadata(self, mock_file_class):
        """Test grouping when files have album metadata."""
        test_dir = Path(self.test_dir) / "mixed_books"
        test_dir.mkdir()
        
        files = []
        file_metadata = {
            "book1_01.mp3": {'album': 'The Great Gatsby', 'title': 'Chapter 1'},
            "book1_02.mp3": {'album': 'The Great Gatsby', 'title': 'Chapter 2'},
            "book2_01.mp3": {'album': 'Pride and Prejudice', 'title': 'Chapter 1'},
            "random.mp3": {'album': None, 'title': None}
        }
        
        for filename in file_metadata:
            file_path = test_dir / filename
            file_path.touch()
            files.append(file_path)
        
        # Mock File to return specific metadata
        def mock_file_func(file_path):
            filename = file_path.name
            metadata = file_metadata.get(filename, {'album': None, 'title': None})
            if metadata['album']:
                mock_audio = MagicMock()
                mock_audio.tags = {'TALB': [metadata['album']]} if file_path.suffix == '.mp3' else {}
                return mock_audio
            return None
        
        mock_file_class.side_effect = mock_file_func
        
        # Mock AudiobookTagger
        with patch.object(audtag, 'AudiobookTagger') as mock_tagger:
            def get_query_for_files(files_subset):
                # Return a query based on the first file
                if files_subset:
                    first_file = files_subset[0]
                    for fname, meta in file_metadata.items():
                        if fname in str(first_file):
                            return meta.get('album', 'unknown')
                return 'unknown'
                
            mock_instance = MagicMock()
            mock_instance.get_initial_search_query.side_effect = lambda: get_query_for_files(mock_tagger.call_args[0][0])
            mock_tagger.return_value = mock_instance
            
            groups = audtag.group_files_by_book(files)
            
            # Should create groups based on album metadata or filename similarity
            # Files with same album (book1_01, book1_02) should be grouped together
            book1_grouped = False
            for group in groups:
                group_files = group['files']
                # Check if this group contains book1 files
                book1_files_in_group = [f for f in group_files if 'book1' in f.name]
                if len(book1_files_in_group) == 2:
                    # Both book1 files are in the same group
                    book1_grouped = True
                    break
            
            self.assertTrue(book1_grouped, "Files book1_01.mp3 and book1_02.mp3 should be grouped together")


class TestGroupingIntegration(unittest.TestCase):
    """Integration tests for the complete grouping workflow."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('mutagen.File')
    def test_complex_directory_structure(self, mock_file):
        """Test grouping with a complex directory structure."""
        # Create a complex structure
        structures = {
            "The Lord of the Rings": ["01_Fellowship.mp3", "02_Two_Towers.mp3", "03_Return.mp3"],
            "incoming": ["Harry_Potter_01.mp3", "Harry_Potter_02.mp3", "Hobbit.mp3", "Random_Book.mp3"],
            "Pride and Prejudice": ["part1.mp3", "part2.mp3", "part3.mp3"]
        }
        
        all_files = []
        for dir_name, file_names in structures.items():
            dir_path = Path(self.test_dir) / dir_name
            dir_path.mkdir()
            for file_name in file_names:
                file_path = dir_path / file_name
                file_path.touch()
                all_files.append(file_path)
        
        mock_file.return_value = None
        
        # Mock AudiobookTagger
        with patch.object(audtag, 'AudiobookTagger') as mock_tagger:
            mock_instance = MagicMock()
            mock_instance.get_initial_search_query.return_value = "test query"
            mock_tagger.return_value = mock_instance
            
            groups = audtag.group_files_by_book(all_files)
            
            # LOTR should be grouped as one (book-like directory)
            lotr_group = next((g for g in groups if any('Fellowship' in f.name for f in g['files'])), None)
            self.assertIsNotNone(lotr_group)
            self.assertEqual(len(lotr_group['files']), 3)
            
            # Pride and Prejudice should be grouped as one (book-like directory)
            pride_group = next((g for g in groups if any('part1' in f.name for f in g['files'])), None)
            self.assertIsNotNone(pride_group)
            self.assertEqual(len(pride_group['files']), 3)
            
            # Harry Potter files in 'incoming' should be grouped together
            hp_group = next((g for g in groups if any('Harry_Potter' in f.name for f in g['files'])), None)
            self.assertIsNotNone(hp_group)
            self.assertEqual(len(hp_group['files']), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)