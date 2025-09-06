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
#     "pyyaml",
# ]
# ///

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import quote_plus

import click
import inquirer
import requests
from bs4 import BeautifulSoup
from mutagen import File
from mutagen.easyid3 import EasyID3
from mutagen.easymp4 import EasyMP4
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC, COMM, TALB, TCOM, TCON, TDRC, TDRL, TIT1, TIT2, TPE1, TPE2, TPOS, TPUB, TRCK, TSOP, TXXX
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

# Import task system if available
try:
    from task_system import TaskSystem
    TASK_SYSTEM_AVAILABLE = True
except ImportError:
    TASK_SYSTEM_AVAILABLE = False

console = Console()

# Global debug flag
DEBUG = False


def get_optimal_workers():
    """Determine optimal number of workers based on CPU cores."""
    try:
        # Get CPU count
        cpu_count = os.cpu_count() or 4
        # For I/O bound tasks like file tagging, we can use more workers than CPU cores
        # But cap it at a reasonable number to avoid overwhelming the system
        optimal = min(cpu_count * 2, 16)
        return optimal
    except:
        return 4  # Fallback to 4 if we can't determine CPU count


class AudibleScraper:
    """Scrapes Audible.com for audiobook metadata."""
    
    BASE_URL = "https://www.audible.com"
    SEARCH_URL = f"{BASE_URL}/search?ipRedirectOverride=true&overrideBaseCountry=true&keywords="
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def search(self, query: str) -> List[Dict]:
        """Search Audible for books matching the query."""
        url = f"{self.SEARCH_URL}{quote_plus(query)}"
        console.print(f"[cyan]Searching Audible for: {query}[/cyan]")
        
        response = self.session.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        results = []
        # Find all product containers
        products = soup.find_all('li', class_='productListItem')
        
        if not products:
            # Try alternative structure
            products = soup.find_all('div', {'data-widget': 'productList'})
            if products:
                products = products[0].find_all('li', class_='bc-list-item')
        
        for product in products[:20]:  # Limit to 20 results
            try:
                result = self._parse_search_result(product)
                if result:
                    results.append(result)
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to parse result: {e}[/yellow]")
        
        return results
    
    def _parse_search_result(self, product) -> Optional[Dict]:
        """Parse a single search result."""
        result = {}
        
        # Title and URL
        title_elem = product.find('h3', class_='bc-heading') or product.find('a', class_='bc-link')
        if not title_elem:
            return None
        
        if title_elem.name == 'h3':
            link = title_elem.find('a')
            if link:
                result['title'] = link.text.strip()
                result['url'] = self.BASE_URL + link.get('href', '').split('?')[0] + '?ipRedirectOverride=true&overrideBaseCountry=true'
        else:
            result['title'] = title_elem.text.strip()
            result['url'] = self.BASE_URL + title_elem.get('href', '').split('?')[0] + '?ipRedirectOverride=true&overrideBaseCountry=true'
        
        # Subtitle
        subtitle = product.find('li', class_='subtitle')
        if subtitle:
            result['title'] += f" - {subtitle.text.strip()}"
        
        # Author
        author_elem = product.find('li', class_='authorLabel')
        if author_elem:
            author_link = author_elem.find('a')
            result['author'] = author_link.text.strip() if author_link else 'Unknown'
        else:
            result['author'] = 'Unknown'
        
        # Narrator
        narrator_elem = product.find('li', class_='narratorLabel')
        if narrator_elem:
            narrator_link = narrator_elem.find('a')
            result['narrator'] = narrator_link.text.strip() if narrator_link else ''
        else:
            result['narrator'] = ''
        
        # Duration - compress format from "11 hrs and 41 mins" to "11:41:00"
        runtime = product.find('li', class_='runtimeLabel')
        if runtime:
            duration_text = runtime.text.replace('Length:', '').strip()
            # Parse "X hrs and Y mins" format
            import re
            hours_match = re.search(r'(\d+)\s*hr', duration_text)
            mins_match = re.search(r'(\d+)\s*min', duration_text)
            
            hours = int(hours_match.group(1)) if hours_match else 0
            mins = int(mins_match.group(1)) if mins_match else 0
            
            # Format as HH:MM:SS
            result['duration'] = f"{hours:02d}:{mins:02d}:00"
        else:
            result['duration'] = ''
        
        # Release date/year - extract year from MM-DD-YYYY format
        release_elem = product.find('li', class_='releaseDateLabel')
        if release_elem:
            release_text = release_elem.text.replace('Release date:', '').strip()
            # Try to extract just the year from various formats
            import re
            # Match patterns like MM-DD-YY or MM-DD-YYYY
            if '-' in release_text:
                parts = release_text.split('-')
                if len(parts) >= 3:
                    # Last part should be the year
                    year_part = parts[-1].strip()
                    # Handle 2-digit year (e.g., 24 -> 2024)
                    if len(year_part) == 2 and year_part.isdigit():
                        year_num = int(year_part)
                        if year_num < 50:
                            result['year'] = f"20{year_part}"
                        else:
                            result['year'] = f"19{year_part}"
                    elif len(year_part) == 4 and year_part.isdigit():
                        result['year'] = year_part
                    else:
                        # Try regex as fallback
                        year_match = re.search(r'(19\d{2}|20\d{2})', release_text)
                        result['year'] = year_match.group() if year_match else ''
                else:
                    result['year'] = ''
            else:
                # Try to find a 4-digit year
                year_match = re.search(r'(19\d{2}|20\d{2})', release_text)
                result['year'] = year_match.group() if year_match else ''
        else:
            result['year'] = ''
        
        return result if result.get('title') else None
    
    def get_book_details(self, url: str) -> Dict:
        """Fetch detailed metadata for a specific book."""
        if DEBUG:
            console.print(f"[dim]Debug: Fetching from {url}[/dim]")
        else:
            console.print(f"[cyan]Fetching book details...[/cyan]")
        
        response = self.session.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        details = {'url': url}
        
        # Cover image
        image_elem = soup.find('img', class_='bc-image-inset-border')
        if image_elem:
            cover_url = image_elem.get('src', '')
            # Upgrade to high resolution
            cover_url = cover_url.replace('_SL175_', '_SS500_').replace('_SL300_', '_SS500_')
            details['cover_url'] = cover_url
        
        # ASIN
        asin_input = soup.find('input', {'name': 'asin'})
        if asin_input:
            details['asin'] = asin_input.get('value', '')
        
        # Title and subtitle
        title_elem = soup.find('h1', class_='bc-heading')
        if title_elem:
            title_text = title_elem.text.strip()
            if ':' in title_text:
                parts = title_text.split(':', 1)
                details['title'] = parts[0].strip()
                details['subtitle'] = parts[1].strip()
            else:
                details['title'] = title_text
                details['subtitle'] = ''
        
        # Author - try multiple methods
        author_elem = soup.find('li', class_='authorLabel')
        if author_elem:
            authors = []
            for link in author_elem.find_all('a'):
                authors.append(link.text.strip())
            details['author'] = ', '.join(authors)
            if DEBUG:
                console.print(f"[dim]Debug: Found author(s) from li: {details['author']}[/dim]")
        else:
            # Try finding author from meta tags or title
            title_elem = soup.find('title')
            if title_elem and ' by ' in title_elem.text:
                # Format is usually "Book Title Audiobook by Author Name"
                author_part = title_elem.text.split(' by ')[-1].strip()
                details['author'] = author_part
                if DEBUG:
                    console.print(f"[dim]Debug: Found author from title: {details['author']}[/dim]")
            elif DEBUG:
                console.print("[dim]Debug: No author found[/dim]")
        
        # Narrator - try multiple methods
        narrator_elem = soup.find('li', class_='narratorLabel')
        if narrator_elem:
            narrators = []
            for link in narrator_elem.find_all('a'):
                narrators.append(link.text.strip())
            details['narrator'] = ', '.join(narrators)
            if DEBUG:
                console.print(f"[dim]Debug: Found narrator(s) from li: {details['narrator']}[/dim]")
        else:
            # Try finding from meta description
            meta_desc = soup.find('meta', {'name': 'description'})
            if meta_desc:
                content = meta_desc.get('content', '')
                if 'narrated by' in content.lower():
                    # Format is usually "Audiobook by Author, narrated by Narrator. ..."
                    parts = content.lower().split('narrated by')
                    if len(parts) > 1:
                        narrator_part = parts[1].split('.')[0].strip()
                        # Clean up the narrator name
                        details['narrator'] = narrator_part.title()
                        if DEBUG:
                            console.print(f"[dim]Debug: Found narrator from meta: {details['narrator']}[/dim]")
                elif DEBUG:
                    console.print("[dim]Debug: No narrator in meta description[/dim]")
            elif DEBUG:
                console.print("[dim]Debug: No narrator found[/dim]")
        
        # Clean up narrator field - remove "introduction by" and similar
        if details.get('narrator'):
            narrator = details['narrator']
            # Remove introduction/foreword by patterns
            narrator = re.sub(r'[;,]\s*(introduction|foreword|afterword|preface)\s+by.*', '', narrator, flags=re.IGNORECASE)
            # If there are multiple narrators separated by comma, take only the first
            if ',' in narrator and 'introduction' not in narrator.lower():
                narrator = narrator.split(',')[0].strip()
            details['narrator'] = narrator.strip()
            if DEBUG:
                console.print(f"[dim]Debug: Cleaned narrator to: {details['narrator']}[/dim]")
        
        # Series
        series_elem = soup.find('li', class_='seriesLabel')
        if series_elem:
            series_link = series_elem.find('a')
            if series_link:
                details['series'] = series_link.text.strip()
                # Try to extract book number
                series_text = series_elem.text
                match = re.search(r'Book (\d+)', series_text)
                if match:
                    details['series_part'] = match.group(1)
        
        # Categories/Genres
        categories_elem = soup.find('li', class_='categoriesLabel')
        if categories_elem:
            categories = []
            for link in categories_elem.find_all('a'):
                categories.append(link.text.strip())
            details['genre'] = '/'.join(categories[:2])  # Max 2 genres
        
        # Publisher's Summary
        summary_section = soup.find('div', class_='productPublisherSummary')
        if summary_section:
            summary_elem = summary_section.find('span', class_='bc-text')
            if summary_elem:
                details['description'] = summary_elem.text.strip()
        
        # Publisher and copyright
        copyright_elem = soup.find('p', class_='bc-text', string=re.compile(r'©'))
        if copyright_elem:
            copyright_text = copyright_elem.text.strip()
            # Extract year
            year_match = re.search(r'©(\d{4})', copyright_text)
            if year_match:
                details['year'] = year_match.group(1)
            # Extract publisher
            pub_match = re.search(r'\(P\)(\d{4})\s+(.+)', copyright_text)
            if pub_match:
                details['release_year'] = pub_match.group(1)
                details['publisher'] = pub_match.group(2).strip()
        
        # Rating
        rating_elem = soup.find('li', class_='ratingsLabel')
        if rating_elem:
            stars_elem = rating_elem.find('span', class_='bc-text')
            if stars_elem:
                rating_text = stars_elem.text.strip()
                # Extract numeric rating
                match = re.search(r'([\d.]+)', rating_text)
                if match:
                    details['rating'] = match.group(1)
        
        if DEBUG:
            console.print("[dim]Debug: Metadata collected:[/dim]")
            for key, value in details.items():
                if value and key not in ['url', 'description', 'cover_url']:
                    console.print(f"[dim]  {key}: {value}[/dim]")
        
        return details


class AudiobookTagger:
    """Updates audio files with audiobook metadata."""
    
    # Supported formats
    SUPPORTED_FORMATS = {'.mp3', '.m4b', '.m4a', '.ogg', '.oga', '.opus', '.flac', '.wma', '.aac'}
    
    def __init__(self, files: List[Path]):
        self.files = sorted(files)
        # Group files by format
        self.formats = set(f.suffix.lower() for f in self.files)
    
    def get_initial_search_query(self) -> str:
        """Extract initial search query from existing tags or filename."""
        queries = []
        
        if DEBUG:
            console.print(f"[dim]Debug: Analyzing {self.files[0].name}[/dim]")
        
        # First try to get metadata from file tags
        for file in self.files:
            try:
                audio = File(file)
                if not audio:
                    continue
                
                # Collect all possible metadata
                album = None
                artist = None
                title = None
                albumartist = None
                
                if hasattr(audio, 'tags') and audio.tags:
                    # Try different tag formats based on file type
                    if file.suffix.lower() in ['.mp3']:
                        album = str(audio.tags.get('TALB', [''])[0]) if audio.tags.get('TALB') else None
                        artist = str(audio.tags.get('TPE1', [''])[0]) if audio.tags.get('TPE1') else None
                        albumartist = str(audio.tags.get('TPE2', [''])[0]) if audio.tags.get('TPE2') else None
                        title = str(audio.tags.get('TIT2', [''])[0]) if audio.tags.get('TIT2') else None
                    elif file.suffix.lower() in ['.m4b', '.m4a', '.aac']:
                        # M4B tags are stored differently
                        album = audio.tags.get('\xa9alb', [None])[0] if '\xa9alb' in audio.tags else None
                        artist = audio.tags.get('\xa9ART', [None])[0] if '\xa9ART' in audio.tags else None
                        albumartist = audio.tags.get('aART', [None])[0] if 'aART' in audio.tags else None
                        title = audio.tags.get('\xa9nam', [None])[0] if '\xa9nam' in audio.tags else None
                        
                        if DEBUG:
                            console.print(f"[dim]Debug M4B tags - Album: {album}, Artist: {artist}, AlbumArtist: {albumartist}, Title: {title}[/dim]")
                        
                    elif file.suffix.lower() in ['.ogg', '.oga', '.opus', '.flac']:
                        album = audio.tags.get('album', [None])[0] if 'album' in audio.tags else None
                        artist = audio.tags.get('artist', [None])[0] if 'artist' in audio.tags else None
                        albumartist = audio.tags.get('albumartist', [None])[0] if 'albumartist' in audio.tags else None
                        title = audio.tags.get('title', [None])[0] if 'title' in audio.tags else None
                
                # Build query from available metadata
                if album:
                    # Remove CD numbers if present
                    album = re.sub(r'[- ]+cd ?\d+$', '', str(album), flags=re.IGNORECASE)
                    # Remove common audiobook suffixes
                    album = re.sub(r'\s*\(unabridged\)\s*$', '', album, flags=re.IGNORECASE)
                    album = re.sub(r'\s*\(abridged\)\s*$', '', album, flags=re.IGNORECASE)
                    
                    # Prefer albumartist over artist for audiobooks
                    if albumartist and albumartist not in ['Unknown', 'Various Artists']:
                        queries.append(f"{albumartist} {album}")
                    elif artist and artist not in ['Unknown', 'Various Artists']:
                        queries.append(f"{artist} {album}")
                    else:
                        queries.append(album)
                    
                    # If we have a good query, clean and return it
                    if queries:
                        # Replace tabs with spaces and multiple spaces with single space
                        query = queries[0].replace('\t', ' ')
                        query = re.sub(r'\s+', ' ', query)
                        # Remove "Narrated By:" from the query (cleanup from previous mistaken tags)
                        query = re.sub(r'Narrated By:\s*', '', query, flags=re.IGNORECASE)
                        return query.strip()
                
                # Try title as fallback
                if title and title not in ['Unknown', 'Track']:
                    # Clean up title
                    title = re.sub(r'\s*\(unabridged\)\s*$', '', str(title), flags=re.IGNORECASE)
                    title = re.sub(r'\s*\(abridged\)\s*$', '', str(title), flags=re.IGNORECASE)
                    # Remove "Narrated By:" from title
                    title = re.sub(r'Narrated By:\s*', '', title, flags=re.IGNORECASE)
                    if artist and artist not in ['Unknown', 'Various Artists']:
                        query = f"{artist} {title}".replace('\t', ' ')
                        query = re.sub(r'\s+', ' ', query)
                        query = re.sub(r'Narrated By:\s*', '', query, flags=re.IGNORECASE)
                        return query.strip()
                    query = str(title).replace('\t', ' ')
                    query = re.sub(r'\s+', ' ', query)
                    query = re.sub(r'Narrated By:\s*', '', query, flags=re.IGNORECASE)
                    return query.strip()
                
                # Just artist as last resort from tags
                if artist and artist not in ['Unknown', 'Various Artists']:
                    query = str(artist).replace('\t', ' ')
                    query = re.sub(r'\s+', ' ', query)
                    query = re.sub(r'Narrated By:\s*', '', query, flags=re.IGNORECASE)
                    return query.strip()
                    
            except Exception as e:
                pass
        
        # Fallback to filename and directory parsing
        stem = self.files[0].stem
        parent_dir = self.files[0].parent.name
        
        if DEBUG:
            console.print(f"[dim]Debug: Parsing filename: {stem}[/dim]")
            console.print(f"[dim]Debug: Parent directory: {parent_dir}[/dim]")
        
        # If parent directory looks like it might be the book title, use it
        if parent_dir and parent_dir not in ['.', '..', '/', 'audiobooks', 'Audiobooks', 'Audio.Books', 'Audio.Books.incoming', 'incoming']:
            # Clean up the parent directory name
            parent_clean = re.sub(r'[_\.]', ' ', parent_dir)
            parent_clean = re.sub(r'\s+', ' ', parent_clean).strip()
            
            # If filename is generic but parent dir is descriptive, prefer parent
            if stem.lower() in ['audiobook', 'book', 'audio', parent_clean.lower(), 'track1', 'track01', '01', '1']:
                stem = parent_clean
                if DEBUG:
                    console.print(f"[dim]Debug: Using parent directory as base: {stem}[/dim]")
            elif len(parent_clean) > len(stem) and parent_clean.lower() != 'audio.books.incoming':
                # Combine parent and filename if parent seems more descriptive
                stem = f"{parent_clean} {stem}"
                if DEBUG:
                    console.print(f"[dim]Debug: Combining parent and filename: {stem}[/dim]")
        
        # Try to extract meaningful parts from filename
        # Common patterns: "Author - Title", "Title by Author", "Title"
        
        # Remove common file numbering patterns
        stem = re.sub(r'^\d+[-_\s\.]*', '', stem)  # Remove leading numbers
        stem = re.sub(r'[-_](\d+|CD\d+|Part\d+|Chapter\d+)$', '', stem, flags=re.IGNORECASE)  # Remove trailing numbers
        
        # Try to parse "Author - Title" pattern
        if ' - ' in stem:
            parts = stem.split(' - ', 1)
            if len(parts) == 2:
                # Could be "Author - Title" or "Title - Author"
                # Usually author comes first in audiobook filenames
                query = f"{parts[0].strip()} {parts[1].strip()}".replace('\t', ' ')
                query = re.sub(r'\s+', ' ', query)
                query = re.sub(r'Narrated By:\s*', '', query, flags=re.IGNORECASE)
                return query.strip()
        
        # Try to parse "Title by Author" pattern
        if ' by ' in stem.lower():
            parts = stem.lower().split(' by ', 1)
            if len(parts) == 2:
                title = stem[:stem.lower().find(' by ')].strip()
                author = stem[stem.lower().find(' by ') + 4:].strip()
                query = f"{author} {title}"
                query = re.sub(r'\s+', ' ', query)
                query = re.sub(r'Narrated By:\s*', '', query, flags=re.IGNORECASE)
                return query.strip()
        
        # Clean up underscores and dots used as spaces
        stem = re.sub(r'[_\.]', ' ', stem)
        stem = re.sub(r'\s+', ' ', stem)  # Normalize multiple spaces
        
        # Remove common audiobook indicators
        stem = re.sub(r'\s*\(unabridged\)\s*$', '', stem, flags=re.IGNORECASE)
        stem = re.sub(r'\s*\(abridged\)\s*$', '', stem, flags=re.IGNORECASE)
        stem = re.sub(r'\s*audiobook\s*$', '', stem, flags=re.IGNORECASE)
        
        # Replace tabs with spaces and multiple spaces with single space
        stem = stem.replace('\t', ' ')
        stem = re.sub(r'\s+', ' ', stem)
        
        # Remove "Narrated By:" from the query (cleanup from previous mistaken tags)
        stem = re.sub(r'Narrated By:\s*', '', stem, flags=re.IGNORECASE)
        
        return stem.strip()
    
    def update_tags(self, metadata: Dict, cover_data: Optional[bytes] = None, max_workers: Optional[int] = None):
        """Update all audio files with the metadata using parallel processing."""
        # Use optimal workers if not specified
        if max_workers is None:
            max_workers = get_optimal_workers()
        
        console.print(f"\n[cyan]Updating {len(self.files)} file(s) with metadata using {min(max_workers, len(self.files))} workers...[/cyan]")
        
        # Artist field should only be the author
        artist_combined = metadata.get('author', '')
        
        # Function to update a single file
        def update_single_file(args):
            file, track_num = args
            try:
                ext = file.suffix.lower()
                
                if ext == '.mp3':
                    self._update_mp3(file, metadata, artist_combined, cover_data, track_num)
                elif ext in ['.m4b', '.m4a', '.aac']:
                    self._update_mp4(file, metadata, artist_combined, cover_data, track_num)
                elif ext in ['.ogg', '.oga', '.opus']:
                    self._update_ogg(file, metadata, artist_combined, cover_data, track_num)
                elif ext == '.flac':
                    self._update_flac(file, metadata, artist_combined, cover_data, track_num)
                else:
                    # Generic mutagen handler for other formats
                    self._update_generic(file, metadata, artist_combined, cover_data, track_num)
                
                return (file, True, None)
            except Exception as e:
                return (file, False, str(e))
        
        # Prepare file list with track numbers
        file_args = [(file, i) for i, file in enumerate(self.files, 1)]
        
        # Use ThreadPoolExecutor for parallel processing
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Tagging files...", total=len(self.files))
            
            with ThreadPoolExecutor(max_workers=min(max_workers, len(self.files))) as executor:
                # Submit all tasks
                futures = {executor.submit(update_single_file, args): args[0] for args in file_args}
                
                # Process completed tasks
                for future in as_completed(futures):
                    file, success, error = future.result()
                    if success:
                        console.print(f"  [green]✓[/green] Updated: {file.name}")
                    else:
                        console.print(f"  [red]✗[/red] Failed to update {file.name}: {error}")
                    progress.update(task, advance=1)
    
    def _update_mp3(self, file: Path, metadata: Dict, artist_combined: str, cover_data: Optional[bytes], track_num: int):
        """Update MP3 file with ID3 tags."""
        audio = MP3(file, ID3=ID3)
        
        # Clear existing tags
        audio.delete()
        audio.save()
        
        # Reload with fresh tags
        audio = MP3(file, ID3=ID3)
        
        # Set standard tags
        title = metadata.get('title', '')
        if metadata.get('subtitle'):
            title = f"{title}: {metadata['subtitle']}"
        audio['TIT2'] = TIT2(encoding=3, text=title)
        
        # Album
        audio['TALB'] = TALB(encoding=3, text=metadata.get('title', ''))
        
        # Artists
        audio['TPE1'] = TPE1(encoding=3, text=artist_combined)  # Artist
        audio['TPE2'] = TPE2(encoding=3, text=metadata.get('author', ''))  # Album Artist
        audio['TCOM'] = TCOM(encoding=3, text=metadata.get('narrator', ''))  # Composer (narrator)
        
        # Publisher
        if metadata.get('publisher'):
            audio['TPUB'] = TPUB(text=metadata['publisher'])
        
        # Year
        if metadata.get('year'):
            audio['TDRC'] = TDRC(encoding=3, text=metadata['year'])
        if metadata.get('release_year'):
            audio['TDRL'] = TDRL(encoding=3, text=metadata['release_year'])
        
        # Genre
        if metadata.get('genre'):
            audio['TCON'] = TCON(text=metadata['genre'])
        
        # Description/Comment
        if metadata.get('description'):
            audio['COMM::eng'] = COMM(
                encoding=3,
                lang='eng',
                desc='',
                text=metadata['description'][:1000]  # Limit length
            )
            audio['TXXX:DESCRIPTION'] = TXXX(
                encoding=3,
                desc='DESCRIPTION',
                text=metadata['description']
            )
        
        # Series information
        if metadata.get('series'):
            audio['TXXX:SERIES'] = TXXX(encoding=3, desc='SERIES', text=metadata['series'])
            if metadata.get('series_part'):
                audio['TXXX:SERIES-PART'] = TXXX(encoding=3, desc='SERIES-PART', text=metadata['series_part'])
                album_sort = f"{metadata['series']} {metadata['series_part']} - {metadata['title']}"
                audio['TSOP'] = TSOP(text=album_sort)
                content_group = f"{metadata['series']}, Book #{metadata['series_part']}"
                audio['TIT1'] = TIT1(encoding=3, text=content_group)
                audio['TXXX:MOVEMENTNAME'] = TXXX(encoding=3, desc='MOVEMENTNAME', text=metadata['series'])
                audio['TXXX:MOVEMENT'] = TXXX(encoding=3, desc='MOVEMENT', text=metadata['series_part'])
                audio['TXXX:SHOWMOVEMENT'] = TXXX(encoding=3, desc='SHOWMOVEMENT', text='1')
        
        # iTunes specific tags
        audio['TXXX:ITUNESMEDIATYPE'] = TXXX(encoding=3, desc='ITUNESMEDIATYPE', text='Audiobook')
        audio['TXXX:ITUNESGAPLESS'] = TXXX(encoding=3, desc='ITUNESGAPLESS', text='1')
        
        # Additional metadata
        if metadata.get('url'):
            audio['TXXX:WWWAUDIOFILE'] = TXXX(encoding=3, desc='WWWAUDIOFILE', text=metadata['url'])
        if metadata.get('asin'):
            audio['TXXX:ASIN'] = TXXX(encoding=3, desc='ASIN', text=metadata['asin'])
        if metadata.get('rating'):
            audio['TXXX:RATING WMP'] = TXXX(encoding=3, desc='RATING WMP', text=metadata['rating'])
        
        # Track number
        if len(self.files) > 1:
            audio['TRCK'] = TRCK(encoding=3, text=f"{track_num}/{len(self.files)}")
            audio['TPOS'] = TPOS(encoding=3, text='1/1')
        
        # Cover art
        if cover_data:
            audio['APIC'] = APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,
                desc='Cover',
                data=cover_data
            )
        
        audio.save()
    
    def _update_mp4(self, file: Path, metadata: Dict, artist_combined: str, cover_data: Optional[bytes], track_num: int):
        """Update MP4/M4B/M4A files."""
        audio = MP4(file)
        
        # Clear existing tags
        audio.clear()
        
        # Set standard tags
        title = metadata.get('title', '')
        if metadata.get('subtitle'):
            title = f"{title}: {metadata['subtitle']}"
        
        audio['\xa9nam'] = title  # Title
        audio['\xa9alb'] = metadata.get('title', '')  # Album
        audio['\xa9ART'] = artist_combined  # Artist
        audio['aART'] = metadata.get('author', '')  # Album Artist
        audio['\xa9wrt'] = metadata.get('narrator', '')  # Composer (narrator)
        
        # Year and genre
        if metadata.get('year'):
            audio['\xa9day'] = metadata['year']
        if metadata.get('genre'):
            audio['\xa9gen'] = metadata['genre']
        
        # Description/Comment
        if metadata.get('description'):
            audio['\xa9cmt'] = metadata['description'][:1000]
            audio['desc'] = metadata['description']
        
        # Publisher
        if metadata.get('publisher'):
            audio['\xa9pub'] = metadata['publisher']
        
        # Track number
        if len(self.files) > 1:
            audio['trkn'] = [(track_num, len(self.files))]
        
        # Disc number
        audio['disk'] = [(1, 1)]
        
        # iTunes specific - mark as audiobook
        audio['stik'] = [2]  # Media type: 2 = audiobook
        audio['pgap'] = True  # Gapless playback
        
        # Custom tags for series
        if metadata.get('series'):
            audio['----:com.apple.iTunes:SERIES'] = metadata['series'].encode('utf-8')
            if metadata.get('series_part'):
                audio['----:com.apple.iTunes:SERIES-PART'] = metadata['series_part'].encode('utf-8')
                audio['soal'] = f"{metadata['series']} {metadata['series_part']} - {metadata['title']}"
        
        # Additional metadata
        if metadata.get('asin'):
            audio['----:com.apple.iTunes:ASIN'] = metadata['asin'].encode('utf-8')
        if metadata.get('url'):
            audio['----:com.apple.iTunes:WWWAUDIOFILE'] = metadata['url'].encode('utf-8')
        
        # Cover art
        if cover_data:
            audio['covr'] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
        
        audio.save()
    
    def _update_ogg(self, file: Path, metadata: Dict, artist_combined: str, cover_data: Optional[bytes], track_num: int):
        """Update OGG/Opus files."""
        audio = File(file)
        
        # Clear existing tags
        if hasattr(audio, 'clear'):
            audio.clear()
        
        # Set standard tags
        title = metadata.get('title', '')
        if metadata.get('subtitle'):
            title = f"{title}: {metadata['subtitle']}"
        
        audio['title'] = title
        audio['album'] = metadata.get('title', '')
        audio['artist'] = artist_combined
        audio['albumartist'] = metadata.get('author', '')
        audio['composer'] = metadata.get('narrator', '')
        
        # Additional metadata
        if metadata.get('year'):
            audio['date'] = metadata['year']
        if metadata.get('genre'):
            audio['genre'] = metadata['genre']
        if metadata.get('publisher'):
            audio['publisher'] = metadata['publisher']
        if metadata.get('description'):
            audio['comment'] = metadata['description'][:1000]
            audio['description'] = metadata['description']
        
        # Series information
        if metadata.get('series'):
            audio['series'] = metadata['series']
            if metadata.get('series_part'):
                audio['seriespart'] = metadata['series_part']
                audio['albumsort'] = f"{metadata['series']} {metadata['series_part']} - {metadata['title']}"
        
        # Track number
        if len(self.files) > 1:
            audio['tracknumber'] = str(track_num)
            audio['tracktotal'] = str(len(self.files))
        
        # Additional tags
        if metadata.get('asin'):
            audio['asin'] = metadata['asin']
        if metadata.get('url'):
            audio['wwwaudiofile'] = metadata['url']
        
        audio.save()
    
    def _update_flac(self, file: Path, metadata: Dict, artist_combined: str, cover_data: Optional[bytes], track_num: int):
        """Update FLAC files."""
        audio = FLAC(file)
        
        # Clear existing tags
        audio.clear()
        
        # Set standard tags
        title = metadata.get('title', '')
        if metadata.get('subtitle'):
            title = f"{title}: {metadata['subtitle']}"
        
        audio['title'] = title
        audio['album'] = metadata.get('title', '')
        audio['artist'] = artist_combined
        audio['albumartist'] = metadata.get('author', '')
        audio['composer'] = metadata.get('narrator', '')
        
        # Additional metadata
        if metadata.get('year'):
            audio['date'] = metadata['year']
        if metadata.get('genre'):
            audio['genre'] = metadata['genre']
        if metadata.get('publisher'):
            audio['publisher'] = metadata['publisher']
        if metadata.get('description'):
            audio['comment'] = metadata['description'][:1000]
            audio['description'] = metadata['description']
        
        # Series information
        if metadata.get('series'):
            audio['series'] = metadata['series']
            if metadata.get('series_part'):
                audio['seriespart'] = metadata['series_part']
                audio['albumsort'] = f"{metadata['series']} {metadata['series_part']} - {metadata['title']}"
        
        # Track number
        if len(self.files) > 1:
            audio['tracknumber'] = str(track_num)
            audio['tracktotal'] = str(len(self.files))
        
        # Additional tags
        if metadata.get('asin'):
            audio['asin'] = metadata['asin']
        if metadata.get('url'):
            audio['wwwaudiofile'] = metadata['url']
        
        # Cover art
        if cover_data:
            picture = Picture()
            picture.type = 3  # Cover (front)
            picture.mime = 'image/jpeg'
            picture.desc = 'Cover'
            picture.data = cover_data
            audio.add_picture(picture)
        
        audio.save()
    
    def _update_generic(self, file: Path, metadata: Dict, artist_combined: str, cover_data: Optional[bytes], track_num: int):
        """Update other audio files using generic mutagen interface."""
        audio = File(file)
        if not audio:
            raise Exception(f"Unsupported format: {file.suffix}")
        
        # Try to clear existing tags
        if hasattr(audio, 'clear'):
            audio.clear()
        
        # Use common tag names
        title = metadata.get('title', '')
        if metadata.get('subtitle'):
            title = f"{title}: {metadata['subtitle']}"
        
        if hasattr(audio, 'tags') and audio.tags is not None:
            audio.tags['title'] = title
            audio.tags['album'] = metadata.get('title', '')
            audio.tags['artist'] = artist_combined
            audio.tags['albumartist'] = metadata.get('author', '')
            
            if metadata.get('year'):
                audio.tags['date'] = metadata['year']
            if metadata.get('genre'):
                audio.tags['genre'] = metadata['genre']
            if metadata.get('description'):
                audio.tags['comment'] = metadata['description'][:1000]
        
        audio.save()


def download_cover(url: str) -> Optional[bytes]:
    """Download cover image from URL."""
    try:
        console.print("[cyan]Downloading cover art...[/cyan]")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.content
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to download cover: {e}[/yellow]")
        return None


def group_files_by_book(audio_files):
    """
    Group audio files into logical book groups.
    
    Returns a list of groups, where each group is a dict with:
    - 'files': List of Path objects
    - 'name': Display name for the group
    - 'query': Suggested search query for the group
    """
    groups = []
    
    # Strategy 1: Group by immediate parent directory
    files_by_dir = {}
    for file in audio_files:
        parent = file.parent
        if parent not in files_by_dir:
            files_by_dir[parent] = []
        files_by_dir[parent].append(file)
    
    # Strategy 2: For each directory group, check if files should be split further
    for directory, dir_files in files_by_dir.items():
        # Sort files for consistent ordering
        dir_files.sort()
        
        # Check if all files in this directory seem to be from the same book
        # by examining filename patterns and existing metadata
        subgroups = []
        
        # Try to detect different books by filename prefix patterns
        prefix_groups = {}
        for file in dir_files:
            # Get the base name without track numbers and extensions
            base = file.stem
            # Remove common track patterns
            base = re.sub(r'[-_\s]*(?:pt|part|chapter|ch|track|cd|disc)[-_\s]*\d+.*$', '', base, flags=re.IGNORECASE)
            base = re.sub(r'[-_\s]*\d{1,3}[-_\s]*$', '', base)  # Remove trailing numbers
            base = base.strip()
            
            if base:
                if base not in prefix_groups:
                    prefix_groups[base] = []
                prefix_groups[base].append(file)
        
        # If we have multiple distinct prefixes, treat them as separate books
        if len(prefix_groups) > 1:
            for prefix, prefix_files in prefix_groups.items():
                if len(prefix_files) >= 1:  # Even single files can be a book
                    subgroups.append({
                        'files': prefix_files,
                        'name': f"{directory.name}/{prefix}" if prefix else directory.name,
                        'base_name': prefix
                    })
        else:
            # All files seem to be from the same book
            subgroups.append({
                'files': dir_files,
                'name': directory.name,
                'base_name': list(prefix_groups.keys())[0] if prefix_groups else directory.name
            })
        
        groups.extend(subgroups)
    
    # For each group, generate a suggested search query
    for group in groups:
        # Use the first file to get a search query suggestion
        tagger = AudiobookTagger(group['files'][:1])
        group['query'] = tagger.get_initial_search_query()
    
    return groups


def tag_files(files, debug=False, workers=None):
    """Main tagging functionality."""
    global DEBUG
    DEBUG = debug
    
    # Collect audio files
    audio_files = []
    for path in files:
        path = Path(path)
        if path.is_dir():
            # Recursively search for all supported formats in directory
            for ext in AudiobookTagger.SUPPORTED_FORMATS:
                audio_files.extend(path.rglob(f'*{ext}'))
                audio_files.extend(path.rglob(f'*{ext.upper()}'))
        else:
            # Check if file has supported extension
            if path.suffix.lower() in AudiobookTagger.SUPPORTED_FORMATS:
                audio_files.append(path)
            else:
                console.print(f"[yellow]Warning: {path.name} is not a supported audio format[/yellow]")
    
    if not audio_files:
        console.print(f"[red]No supported audio files found![/red]")
        console.print(f"[yellow]Supported formats: {', '.join(sorted(AudiobookTagger.SUPPORTED_FORMATS))}[/yellow]")
        return
    
    # Group files by book
    book_groups = group_files_by_book(audio_files)
    
    # Show what we found
    if len(book_groups) > 1:
        total_files = sum(len(group['files']) for group in book_groups)
        console.print(f"\n[cyan]Found {len(book_groups)} books, {total_files} files total:[/cyan]")
        for i, group in enumerate(book_groups, 1):
            console.print(f"  {i}. [yellow]{group['name']}[/yellow] ({len(group['files'])} file{'s' if len(group['files']) > 1 else ''})")
        console.print()
    elif len(audio_files) == 1:
        console.print(f"\n[cyan]Found 1 file: {audio_files[0].name}[/cyan]")
    else:
        console.print(f"\n[cyan]Found {len(audio_files)} files in {book_groups[0]['name']}[/cyan]")
    
    # Collect metadata for all books first
    scraper = AudibleScraper()
    books_to_tag = []  # List of (group, tagger, metadata, cover_url) tuples
    
    console.print(f"\n[bold cyan]Step 1: Collecting metadata for all books[/bold cyan]\n")
    
    for group_idx, group in enumerate(book_groups):
        if len(book_groups) > 1:
            # Add visual separator between books
            if group_idx > 0:
                console.print()  # Extra space between books
            
            console.print(f"\n[bold cyan]{'━' * 70}[/bold cyan]")
            console.print(f"[bold cyan]Book {group_idx + 1} of {len(book_groups)}: {group['name']}[/bold cyan]")
            console.print(f"[bold cyan]{'━' * 70}[/bold cyan]\n")
        
        # Initialize tagger for this group
        tagger = AudiobookTagger(group['files'])
        
        # Get initial search query - use group's suggested query
        initial_query = group['query']
        
        # Ask user for search query with styled prompt
        try:
            # Try using inquirer for better interactive experience
            questions = [
                inquirer.Text('query', 
                             message='Search query',
                             default=initial_query)
            ]
            answers = inquirer.prompt(questions)
        
            if not answers:
                console.print("[yellow]Cancelled[/yellow]")
                return
        
            search_query = answers['query']
        except Exception:
            # Fallback to simple input if inquirer fails (non-interactive terminal)
            console.print(f"\n[bold cyan][?][/bold cyan] Search query [dim][{initial_query}][/dim]: ", end="")
            search_query = click.prompt('', default=initial_query, type=str, show_default=False, prompt_suffix='')
    
        if not search_query:
            console.print("[yellow]Cancelled[/yellow]")
            return
    
        # Search Audible
        results = scraper.search(search_query)
    
        if not results:
            console.print("[red]No results found![/red]")
            return
    
        # Display results
        table = Table(title="Search Results")
        table.add_column("#", style="cyan", width=3)
        table.add_column("Title", style="green")
        table.add_column("Author", style="yellow")
        table.add_column("Narrator", style="blue")
        table.add_column("Year", style="white", width=8)
        table.add_column("Duration", style="magenta", width=10)
    
        for i, result in enumerate(results, 1):
            table.add_row(
                str(i),
                result.get('title', 'Unknown'),
                result.get('author', 'Unknown'),
                result.get('narrator', 'Unknown'),
                result.get('year', ''),
                result.get('duration', 'Unknown')
            )
    
        console.print(table)
    
        # Let user select a result with formatted choices
        try:
            # Try using inquirer for better selection experience
            choices = []
            for i, r in enumerate(results, 1):
                choice_text = f"{i}. {r['title']}"
                if r.get('subtitle'):
                    choice_text += f" - {r['subtitle']}"
                if r.get('author'):
                    choice_text += f" by {r['author']}"
                choices.append(choice_text)
        
            # Print the prompt once to avoid repetition
            console.print("\n[bold cyan][?][/bold cyan] Select audiobook:")
        
            questions = [
                inquirer.List('selection',
                             message='',  # Empty message to avoid repetition
                             choices=choices + ['Cancel'])
            ]
            answers = inquirer.prompt(questions)
        
            if not answers or answers['selection'] == 'Cancel':
                console.print("[yellow]Cancelled[/yellow]")
                return
        
            # Extract selection number
            selection = int(answers['selection'].split('.')[0])
        except Exception:
            # Fallback to simple selection
            console.print("\n[bold cyan][?][/bold cyan] Select audiobook:")
            for i, r in enumerate(results, 1):
                choice_text = f"{r['title']}"
                if r.get('subtitle'):
                    choice_text += f" - {r['subtitle']}"
                if r.get('author'):
                    choice_text += f" by {r['author']}"
                console.print(f"  [cyan]{i})[/cyan] {choice_text}")
            console.print(f"  [cyan]{len(results)+1})[/cyan] Cancel")
        
            console.print("  Selection: ", end="")
            selection = click.prompt('', type=click.IntRange(1, len(results)+1), show_default=False, prompt_suffix='')
        
            if selection == len(results)+1:
                console.print("[yellow]Cancelled[/yellow]")
                return
    
        selected = results[selection - 1]
    
        # Get detailed metadata
        metadata = scraper.get_book_details(selected['url'])
    
        # Get current tags for comparison
        console.print("\n[cyan]Analyzing current tags...[/cyan]")
    
        # Prepare the new metadata that will be applied
        new_artist_combined = metadata.get('author', '')
    
        new_title = metadata.get('title', '')
        if metadata.get('subtitle'):
            new_title = f"{new_title}: {metadata['subtitle']}"
    
        # Show before/after comparison
        if len(tagger.files) > 1:
            # For multiple files, show a combined view
            console.print(f"\n[bold]Files to tag: {len(tagger.files)} files[/bold]")
            console.print("[dim]" + ", ".join(f.name for f in sorted(tagger.files)[:5]) + 
                         (" ..." if len(tagger.files) > 5 else "") + "[/dim]")
        
            # Get a representative file for current tags (use the first one)
            file = tagger.files[0]
            current_title = ""
            current_artist = ""
            current_album = ""
            current_composer = ""
        
            try:
                audio = File(file)
                if audio and hasattr(audio, 'tags') and audio.tags:
                    if file.suffix.lower() == '.mp3':
                        current_title = str(audio.tags.get('TIT2', [''])[0]) if audio.tags.get('TIT2') else ''
                        current_artist = str(audio.tags.get('TPE1', [''])[0]) if audio.tags.get('TPE1') else ''
                        current_album = str(audio.tags.get('TALB', [''])[0]) if audio.tags.get('TALB') else ''
                        current_composer = str(audio.tags.get('TCOM', [''])[0]) if audio.tags.get('TCOM') else ''
                    elif file.suffix.lower() in ['.m4b', '.m4a', '.aac']:
                        current_title = audio.tags.get('\xa9nam', [''])[0] or '' if '\xa9nam' in audio.tags else ''
                        current_artist = audio.tags.get('\xa9ART', [''])[0] or '' if '\xa9ART' in audio.tags else ''
                        current_album = audio.tags.get('\xa9alb', [''])[0] or '' if '\xa9alb' in audio.tags else ''
                        current_composer = audio.tags.get('\xa9wrt', [''])[0] or '' if '\xa9wrt' in audio.tags else ''
                    elif file.suffix.lower() in ['.ogg', '.oga', '.opus', '.flac']:
                        current_title = audio.tags.get('title', [''])[0] or '' if 'title' in audio.tags else ''
                        current_artist = audio.tags.get('artist', [''])[0] or '' if 'artist' in audio.tags else ''
                        current_album = audio.tags.get('album', [''])[0] or '' if 'album' in audio.tags else ''
                        current_composer = audio.tags.get('composer', [''])[0] or '' if 'composer' in audio.tags else ''
            except:
                pass
        
            # Create comparison table
            compare_table = Table(show_header=False, box=None, padding=(0, 2))
            compare_table.add_column("Field", style="cyan", width=20)
            compare_table.add_column("Current", style="red", width=40)
            compare_table.add_column("→", style="white", width=3)
            compare_table.add_column("New", style="green", width=40)
        
            # Show changes (these will apply to all files)
            compare_table.add_row("Title:", current_title or "(empty)", "→", new_title)
            compare_table.add_row("Artist:", current_artist or "(empty)", "→", new_artist_combined)
            compare_table.add_row("Album:", current_album or "(empty)", "→", metadata.get('title', ''))
            compare_table.add_row("Composer (Narrator):", current_composer or "(empty)", "→", metadata.get('narrator', ''))
        
            # Add additional fields that will be updated
            if metadata.get('genre'):
                compare_table.add_row("Genre:", "(not set)", "→", metadata.get('genre', ''))
            if metadata.get('publisher'):
                compare_table.add_row("Publisher:", "(not set)", "→", metadata.get('publisher', ''))
            if metadata.get('year'):
                compare_table.add_row("Year:", "(not set)", "→", metadata.get('year', ''))
            if metadata.get('series'):
                series_info = metadata['series']
                if metadata.get('series_part'):
                    series_info += f", Book #{metadata['series_part']}"
                compare_table.add_row("Series:", "(not set)", "→", series_info)
        
            console.print(compare_table)
        else:
            # Single file - show specific name
            file = tagger.files[0]
            console.print(f"\n[bold]File: {file.name}[/bold]")
        
            # Get current tags
            current_title = ""
            current_artist = ""
            current_album = ""
            current_composer = ""
        
            try:
                audio = File(file)
                if audio and hasattr(audio, 'tags') and audio.tags:
                    if file.suffix.lower() == '.mp3':
                        current_title = str(audio.tags.get('TIT2', [''])[0]) if audio.tags.get('TIT2') else ''
                        current_artist = str(audio.tags.get('TPE1', [''])[0]) if audio.tags.get('TPE1') else ''
                        current_album = str(audio.tags.get('TALB', [''])[0]) if audio.tags.get('TALB') else ''
                        current_composer = str(audio.tags.get('TCOM', [''])[0]) if audio.tags.get('TCOM') else ''
                    elif file.suffix.lower() in ['.m4b', '.m4a', '.aac']:
                        current_title = audio.tags.get('\xa9nam', [''])[0] or '' if '\xa9nam' in audio.tags else ''
                        current_artist = audio.tags.get('\xa9ART', [''])[0] or '' if '\xa9ART' in audio.tags else ''
                        current_album = audio.tags.get('\xa9alb', [''])[0] or '' if '\xa9alb' in audio.tags else ''
                        current_composer = audio.tags.get('\xa9wrt', [''])[0] or '' if '\xa9wrt' in audio.tags else ''
                    elif file.suffix.lower() in ['.ogg', '.oga', '.opus', '.flac']:
                        current_title = audio.tags.get('title', [''])[0] or '' if 'title' in audio.tags else ''
                        current_artist = audio.tags.get('artist', [''])[0] or '' if 'artist' in audio.tags else ''
                        current_album = audio.tags.get('album', [''])[0] or '' if 'album' in audio.tags else ''
                        current_composer = audio.tags.get('composer', [''])[0] or '' if 'composer' in audio.tags else ''
            except:
                pass
        
            # Create comparison table
            compare_table = Table(show_header=False, box=None, padding=(0, 2))
            compare_table.add_column("Field", style="cyan", width=20)
            compare_table.add_column("Current", style="red", width=40)
            compare_table.add_column("→", style="white", width=3)
            compare_table.add_column("New", style="green", width=40)
        
            # Show changes
            compare_table.add_row("Title:", current_title or "(empty)", "→", new_title)
            compare_table.add_row("Artist:", current_artist or "(empty)", "→", new_artist_combined)
            compare_table.add_row("Album:", current_album or "(empty)", "→", metadata.get('title', ''))
            compare_table.add_row("Composer (Narrator):", current_composer or "(empty)", "→", metadata.get('narrator', ''))
        
            # Add additional fields that will be updated
            if metadata.get('genre'):
                compare_table.add_row("Genre:", "(not set)", "→", metadata.get('genre', ''))
            if metadata.get('publisher'):
                compare_table.add_row("Publisher:", "(not set)", "→", metadata.get('publisher', ''))
            if metadata.get('year'):
                compare_table.add_row("Year:", "(not set)", "→", metadata.get('year', ''))
            if metadata.get('series'):
                series_info = metadata['series']
                if metadata.get('series_part'):
                    series_info += f", Book #{metadata['series_part']}"
                compare_table.add_row("Series:", "(not set)", "→", series_info)
        
            console.print(compare_table)
    
        # Ask for confirmation with styled prompt
        try:
            # Try using inquirer
            questions = [
                inquirer.Confirm('confirm',
                                message='Proceed with tagging?',
                                default=True)
            ]
            answers = inquirer.prompt(questions)
        
            if not answers or not answers['confirm']:
                console.print("[yellow]Cancelled[/yellow]")
                return
        except Exception:
            # Fallback to simple confirmation
            console.print("\n[bold cyan][?][/bold cyan] Proceed with tagging? [dim](Y/n)[/dim] ", end="")
            if not click.confirm('', default=True, show_default=False, prompt_suffix=''):
                console.print("[yellow]Cancelled[/yellow]")
                return
    
        # Save metadata for batch processing
        books_to_tag.append({
            'group': group,
            'tagger': tagger,
            'metadata': metadata,
            'cover_url': metadata.get('cover_url')
        })
        
        console.print("\n[green]✓[/green] Metadata collected")
    
    # Now process all books at once
    if len(books_to_tag) > 1:
        console.print(f"\n[bold cyan]{'━' * 70}[/bold cyan]")
        console.print(f"[bold cyan]Step 2: Updating all files ({len(books_to_tag)} books)[/bold cyan]")
        console.print(f"[bold cyan]{'━' * 70}[/bold cyan]\n")
    
    for book_idx, book_info in enumerate(books_to_tag):
        group = book_info['group']
        tagger = book_info['tagger']
        metadata = book_info['metadata']
        cover_url = book_info['cover_url']
        
        if len(books_to_tag) > 1:
            console.print(f"\n[cyan]Processing book {book_idx + 1}/{len(books_to_tag)}: {group['name']}[/cyan]")
        
        # Download cover if available
        cover_data = None
        if cover_url:
            cover_data = download_cover(cover_url)
        
        # Update tags
        tagger.update_tags(metadata, cover_data, max_workers=workers)
        
        console.print("[green]✅ Tagging complete![/green]")
    
    if len(books_to_tag) > 1:
        console.print(f"\n[bold green]✅ All {len(books_to_tag)} books have been tagged![/bold green]")
    
    # Tasks are now separate commands, not automatic post-processing


@click.group(invoke_without_command=True, context_settings={'help_option_names': ['-h', '--help']})
@click.pass_context
@click.option('--debug', is_flag=True, help='Show debug output')
def cli(ctx, debug):
    """
    Tag audio files with Audible audiobook metadata.
    
    Supported formats: MP3, M4B, M4A, OGG, OPUS, FLAC, AAC
    
    Examples:
        audtag tag audiobook.mp3          # Tag files (auto-detect workers)
        audtag tag --debug audiobook.mp3  # Tag with debug output
        audtag tag -w 8 audiobook.mp3     # Tag with 8 parallel workers
        audtag tag -w 1 audiobook.mp3     # Tag sequentially (1 worker)
        audtag info audiobook.mp3         # Show file info
    """
    # Store debug flag for subcommands
    ctx.obj = {'debug': debug}
    
    # If no subcommand and no args, show help
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@cli.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('files', nargs=-1, required=True, type=click.Path(exists=True))
@click.option('--workers', '-w', type=int, default=None, help=f'Number of parallel workers for tagging (default: auto-detect, currently {get_optimal_workers()})')
@click.pass_context
def tag(ctx, files, workers):
    """Tag audio files with Audible metadata."""
    debug = ctx.obj.get('debug', False) if ctx.obj else False
    tag_files(files, debug, workers)


@cli.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('files', nargs=-1, required=True, type=click.Path(exists=True))
@click.pass_context
def info(ctx, files):
    """Show metadata information for audio files."""
    audio_files = []
    for path in files:
        path = Path(path)
        if path.is_dir():
            for ext in AudiobookTagger.SUPPORTED_FORMATS:
                audio_files.extend(path.rglob(f'*{ext}'))
                audio_files.extend(path.rglob(f'*{ext.upper()}'))
        else:
            if path.suffix.lower() in AudiobookTagger.SUPPORTED_FORMATS:
                audio_files.append(path)
            else:
                console.print(f"[yellow]Warning: {path.name} is not a supported audio format[/yellow]")
    
    if not audio_files:
        console.print(f"[red]No supported audio files found![/red]")
        return
    
    # First, collect all file metadata
    file_metadata = {}
    
    for file_path in sorted(audio_files):
        try:
            audio = File(file_path)
            if not audio or not hasattr(audio, 'tags') or not audio.tags:
                file_metadata[file_path] = None
                continue
            
            # Extract metadata based on format
            metadata = {}
            if file_path.suffix.lower() == '.mp3':
                metadata['Title'] = str(audio.tags.get('TIT2', [''])[0]) if audio.tags.get('TIT2') else ''
                metadata['Artist'] = str(audio.tags.get('TPE1', [''])[0]) if audio.tags.get('TPE1') else ''
                metadata['Album'] = str(audio.tags.get('TALB', [''])[0]) if audio.tags.get('TALB') else ''
                metadata['Album Artist'] = str(audio.tags.get('TPE2', [''])[0]) if audio.tags.get('TPE2') else ''
                metadata['Composer (Narrator)'] = str(audio.tags.get('TCOM', [''])[0]) if audio.tags.get('TCOM') else ''
                metadata['Genre'] = str(audio.tags.get('TCON', [''])[0]) if audio.tags.get('TCON') else ''
                metadata['Year'] = str(audio.tags.get('TDRC', [''])[0]) if audio.tags.get('TDRC') else ''
                metadata['Publisher'] = str(audio.tags.get('TPUB', [''])[0]) if audio.tags.get('TPUB') else ''
                metadata['Track'] = str(audio.tags.get('TRCK', [''])[0]) if audio.tags.get('TRCK') else ''
                
                # Check for custom tags
                for tag_key, tag_value in audio.tags.items():
                    if tag_key.startswith('TXXX:'):
                        field_name = tag_key[5:]
                        if field_name in ['ASIN', 'SERIES', 'SERIES-PART', 'ITUNESMEDIATYPE']:
                            metadata[field_name] = str(tag_value)
                            
            elif file_path.suffix.lower() in ['.m4b', '.m4a', '.aac']:
                metadata['Title'] = audio.tags.get('\xa9nam', [''])[0] or '' if '\xa9nam' in audio.tags else ''
                metadata['Artist'] = audio.tags.get('\xa9ART', [''])[0] or '' if '\xa9ART' in audio.tags else ''
                metadata['Album'] = audio.tags.get('\xa9alb', [''])[0] or '' if '\xa9alb' in audio.tags else ''
                metadata['Album Artist'] = audio.tags.get('aART', [''])[0] or '' if 'aART' in audio.tags else ''
                metadata['Composer (Narrator)'] = audio.tags.get('\xa9wrt', [''])[0] or '' if '\xa9wrt' in audio.tags else ''
                metadata['Genre'] = audio.tags.get('\xa9gen', [''])[0] or '' if '\xa9gen' in audio.tags else ''
                metadata['Year'] = audio.tags.get('\xa9day', [''])[0] or '' if '\xa9day' in audio.tags else ''
                metadata['Publisher'] = audio.tags.get('\xa9pub', [''])[0] or '' if '\xa9pub' in audio.tags else ''
                metadata['Track'] = f"{audio.tags.get('trkn', [(0,0)])[0][0]}/{audio.tags.get('trkn', [(0,0)])[0][1]}" if 'trkn' in audio.tags else ''
                
                # Media type
                if 'stik' in audio.tags:
                    media_type = audio.tags['stik'][0]
                    media_type_str = "Audiobook" if media_type == 2 else f"Type {media_type}"
                    metadata['Media Type'] = media_type_str
                    
            elif file_path.suffix.lower() in ['.ogg', '.oga', '.opus', '.flac']:
                metadata['Title'] = audio.tags.get('title', [''])[0] or '' if 'title' in audio.tags else ''
                metadata['Artist'] = audio.tags.get('artist', [''])[0] or '' if 'artist' in audio.tags else ''
                metadata['Album'] = audio.tags.get('album', [''])[0] or '' if 'album' in audio.tags else ''
                metadata['Album Artist'] = audio.tags.get('albumartist', [''])[0] or '' if 'albumartist' in audio.tags else ''
                metadata['Composer (Narrator)'] = audio.tags.get('composer', [''])[0] or '' if 'composer' in audio.tags else ''
                metadata['Genre'] = audio.tags.get('genre', [''])[0] or '' if 'genre' in audio.tags else ''
                metadata['Date'] = audio.tags.get('date', [''])[0] or '' if 'date' in audio.tags else ''
                metadata['Publisher'] = audio.tags.get('publisher', [''])[0] or '' if 'publisher' in audio.tags else ''
            
            # Add audio properties
            if hasattr(audio.info, 'length'):
                duration = int(audio.info.length)
                hours, remainder = divmod(duration, 3600)
                minutes, seconds = divmod(remainder, 60)
                metadata['Duration'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            if hasattr(audio.info, 'bitrate'):
                metadata['Bitrate'] = f"{audio.info.bitrate} bps"
            if hasattr(audio.info, 'sample_rate'):
                metadata['Sample Rate'] = f"{audio.info.sample_rate} Hz"
                
            file_metadata[file_path] = metadata
            
        except Exception as e:
            file_metadata[file_path] = {'error': str(e)}
    
    # Now group files by their tag signatures (excluding Track and Duration which vary per file)
    tag_groups = {}
    
    for file_path, metadata in file_metadata.items():
        if metadata is None:
            # No tags found
            if 'no_tags' not in tag_groups:
                tag_groups['no_tags'] = []
            tag_groups['no_tags'].append(file_path)
        elif 'error' in metadata:
            # Error reading
            if 'error' not in tag_groups:
                tag_groups['error'] = []
            tag_groups['error'].append((file_path, metadata['error']))
        else:
            # Create a signature from the metadata (excluding file-specific fields)
            signature_fields = ['Title', 'Artist', 'Album', 'Album Artist', 'Composer (Narrator)', 
                              'Genre', 'Year', 'Publisher', 'SERIES', 'ITUNESMEDIATYPE']
            signature = tuple(metadata.get(field, '') for field in signature_fields)
            
            if signature not in tag_groups:
                tag_groups[signature] = []
            tag_groups[signature].append(file_path)
    
    # Display the grouped information
    for signature, file_paths in tag_groups.items():
        if signature == 'no_tags':
            console.print(f"\n[bold yellow]Files with no tags:[/bold yellow]")
            for fp in file_paths:
                console.print(f"  • {fp.name}")
        elif signature == 'error':
            console.print(f"\n[bold red]Files with errors:[/bold red]")
            for fp, error in file_paths:
                console.print(f"  • {fp.name}: {error}")
        else:
            # Regular files with tags
            if len(file_paths) > 1:
                # Multiple files with same tags - show grouped
                console.print(f"\n[bold cyan]Files: {len(file_paths)} files with identical tags[/bold cyan]")
                console.print("[dim]" + ", ".join(f.name for f in file_paths[:5]) + 
                             (" ..." if len(file_paths) > 5 else "") + "[/dim]")
            else:
                # Single file
                console.print(f"\n[bold cyan]File: {file_paths[0].name}[/bold cyan]")
                console.print(f"[dim]Path: {file_paths[0]}[/dim]")
            
            # Show the metadata table
            metadata = file_metadata[file_paths[0]]
            tag_table = Table(show_header=False, box=None, padding=(0, 2))
            tag_table.add_column("Field", style="cyan", width=25)
            tag_table.add_column("Value", style="white")
            
            # Show common tags
            for field in ['Title', 'Artist', 'Album', 'Album Artist', 'Composer (Narrator)', 
                         'Genre', 'Year', 'Publisher', 'SERIES', 'SERIES-PART', 'ITUNESMEDIATYPE', 
                         'Media Type', 'ASIN']:
                if field in metadata and metadata[field]:
                    tag_table.add_row(f"{field}:", metadata[field])
            
            # For grouped files, show track numbers as a range
            if len(file_paths) > 1:
                tracks = []
                for fp in file_paths:
                    if fp in file_metadata and 'Track' in file_metadata[fp]:
                        tracks.append(file_metadata[fp]['Track'])
                if tracks:
                    tag_table.add_row("Tracks:", f"{tracks[0]} to {tracks[-1]}")
            else:
                # Single file - show its track
                if 'Track' in metadata and metadata['Track']:
                    tag_table.add_row("Track:", metadata['Track'])
            
            # Show audio properties (these might vary slightly)
            if 'Duration' in metadata:
                tag_table.add_row("Duration:", metadata['Duration'])
            if 'Bitrate' in metadata:
                tag_table.add_row("Bitrate:", metadata['Bitrate'])
            if 'Sample Rate' in metadata:
                tag_table.add_row("Sample Rate:", metadata['Sample Rate'])
                
            console.print(tag_table)


# Dynamically register task commands from configuration
def register_task_commands():
    """Register task commands from audtag.yaml configuration."""
    if not TASK_SYSTEM_AVAILABLE:
        return
        
    try:
        # Load task configuration
        task_system = TaskSystem()
        tasks = task_system.get_available_tasks()
        
        for task in tasks:
            task_name = task.get('name')
            task_description = task.get('description', f"Execute {task_name} task")
            
            # Create a command function for this task
            def make_task_command(name, desc, task_config):
                # Build short help text for the command listing
                short_help = desc
                
                # Build epilog text with task configuration details
                epilog = "\n\b\nTask Configuration:\n\b\n"
                epilog += f"Name: {task_config.get('name', 'N/A')}\n"
                
                if task_config.get('destination'):
                    epilog += f"Destination: {task_config.get('destination')}\n"
                if task_config.get('naming_pattern'):
                    epilog += f"Naming Pattern: {task_config.get('naming_pattern')}\n"
                
                # Add example showing how patterns work
                epilog += "\n\b\nExample:\n\b\n"
                epilog += "Given a file with these tags:\n"
                epilog += "  Artist: Brandon Sanderson\n"
                epilog += "  Album: The Way of Kings\n" 
                epilog += "  Title: Chapter 1 - Stormblessed\n"
                epilog += "  Track: 1\n"
                epilog += "\n"
                
                if name == 'move' and task_config.get('destination'):
                    example_dest = task_config.get('destination')
                    example_dest = example_dest.replace('{artist}', 'Brandon Sanderson')
                    example_dest = example_dest.replace('{album}', 'The Way of Kings')
                    example_dest = example_dest.replace('{date:%Y-%m-%d}', '2024-01-15')
                    
                    example_name = task_config.get('naming_pattern', '{filename}.{ext}')
                    example_name = example_name.replace('{artist}', 'Brandon Sanderson')
                    example_name = example_name.replace('{album}', 'The Way of Kings')
                    example_name = example_name.replace('{title}', 'Chapter 1 - Stormblessed')
                    example_name = example_name.replace('{track}', '1')
                    example_name = example_name.replace('{track:02d}', '01')
                    example_name = example_name.replace('{track:03d}', '001')
                    example_name = example_name.replace('{year}', '2010')
                    example_name = example_name.replace('{filename}', 'audiobook')
                    example_name = example_name.replace('{ext}', 'm4b')
                    
                    epilog += f"Would move to: {example_dest}{example_name}\n"
                    
                elif name == 'copy' and task_config.get('destination'):
                    example_dest = task_config.get('destination')
                    example_dest = example_dest.replace('{artist}', 'Brandon Sanderson')
                    example_dest = example_dest.replace('{album}', 'The Way of Kings')
                    from datetime import datetime
                    example_dest = example_dest.replace('{date:%Y-%m-%d}', datetime.now().strftime('%Y-%m-%d'))
                    
                    example_name = task_config.get('naming_pattern', '{filename}.{ext}')
                    example_name = example_name.replace('{artist}', 'Brandon Sanderson')
                    example_name = example_name.replace('{album}', 'The Way of Kings')
                    example_name = example_name.replace('{title}', 'Chapter 1 - Stormblessed')
                    example_name = example_name.replace('{track}', '1')
                    example_name = example_name.replace('{track:02d}', '01')
                    example_name = example_name.replace('{track:03d}', '001')
                    example_name = example_name.replace('{year}', '2010')
                    example_name = example_name.replace('{filename}', 'audiobook')
                    example_name = example_name.replace('{ext}', 'm4b')
                    
                    epilog += f"Would copy to: {example_dest}{example_name}\n"
                    
                elif name == 'rename' and task_config.get('naming_pattern'):
                    example_name = task_config.get('naming_pattern')
                    example_name = example_name.replace('{artist}', 'Brandon Sanderson')
                    example_name = example_name.replace('{album}', 'The Way of Kings')
                    example_name = example_name.replace('{title}', 'Chapter 1 - Stormblessed')
                    example_name = example_name.replace('{track}', '1')
                    example_name = example_name.replace('{track:02d}', '01')
                    example_name = example_name.replace('{track:03d}', '001')
                    example_name = example_name.replace('{year}', '2010')
                    example_name = example_name.replace('{filename}', 'audiobook')
                    example_name = example_name.replace('{ext}', 'm4b')
                    
                    epilog += f"Would rename to: {example_name}\n"
                
                epilog += "\n\b\nPattern Variables:\n\b\n"
                epilog += "{artist}       - Artist/Author name\n"
                epilog += "{album}        - Album/Book title\n"
                epilog += "{title}        - Track/Chapter title\n"
                epilog += "{track}        - Track number\n"
                epilog += "{track:02d}    - Track with zero padding\n"
                epilog += "{year}         - Year\n"
                epilog += "{genre}        - Genre\n"
                epilog += "{composer}     - Composer/Narrator\n"
                epilog += "{filename}     - Original filename\n"
                epilog += "{ext}          - File extension\n"
                epilog += "{date:%Y-%m-%d} - Current date"
                
                @cli.command(name=name, short_help=short_help, epilog=epilog,
                           context_settings={'help_option_names': ['-h', '--help'], 
                                           'max_content_width': 120})
                @click.argument('files', nargs=-1, required=True, type=click.Path(exists=True))
                @click.option('--dry-run', '-n', is_flag=True, help='Show what would be done without doing it')
                @click.option('--config', '-c', type=click.Path(exists=True), default=None, 
                            help='Path to task configuration file (default: ~/audtag.yaml or ./audtag.yaml)')
                @click.pass_context
                def task_command(ctx, files, dry_run, config):
                    debug = ctx.obj.get('debug', False) if ctx.obj else False
                    
                    # Collect audio files silently
                    audio_files = []
                    for path in files:
                        path = Path(path)
                        if path.is_dir():
                            for ext in AudiobookTagger.SUPPORTED_FORMATS:
                                matches = list(path.rglob(f'*{ext}'))
                                audio_files.extend(matches)
                                matches = list(path.rglob(f'*{ext.upper()}'))
                                audio_files.extend(matches)
                        else:
                            if path.suffix.lower() in AudiobookTagger.SUPPORTED_FORMATS:
                                audio_files.append(path)
                            else:
                                console.print(f"[yellow]Warning: {path.name} is not a supported audio format[/yellow]")
                    
                    if not audio_files:
                        console.print(f"[red]No audio files found in: {', '.join(files)}[/red]")
                        console.print(f"[dim]Supported formats: {', '.join(sorted(AudiobookTagger.SUPPORTED_FORMATS))}[/dim]")
                        return
                    
                    # Execute the task
                    task_system = TaskSystem(config_path=config, debug=debug)
                    task_system.execute_task(name, audio_files, dry_run=dry_run)
                
                return task_command
            
            # Register the command
            make_task_command(task_name, task_description, task)
            
    except Exception as e:
        # Silently fail - tasks just won't be available
        pass

# Register task commands on module load
register_task_commands()

if __name__ == '__main__':
    cli()