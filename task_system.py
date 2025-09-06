#!/usr/bin/env python3
"""
Task system for post-tagging operations.
Supports move, copy, and rename operations with configurable patterns.
"""

import os
import re
import shutil
import yaml
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from rich.console import Console
from rich.table import Table
from mutagen import File

console = Console()


class TaskSystem:
    """Handles post-tagging tasks like move, copy, and rename."""
    
    def __init__(self, config_path: Optional[Path] = None, debug: bool = False):
        """
        Initialize the task system.
        
        Args:
            config_path: Path to config file. If None, looks for audtag.yaml
            debug: Enable debug output
        """
        self.debug = debug
        self.config = self._load_config(config_path)
        self.dry_run = False  # Set by execute_task method
        self.overwrite_all = False  # Track if user chose "all" for overwrites
    
    def get_available_tasks(self) -> List[Dict[str, Any]]:
        """Get list of available tasks from configuration."""
        return self.config.get('tasks', [])
    
    def _format_path_display(self, source: Path, dest: Path) -> str:
        """
        Format source and destination paths for display.
        Shows relative paths when possible, abbreviates common prefixes.
        """
        # Format source path
        try:
            # Try relative to current directory
            src_display = str(source.relative_to(Path.cwd()))
            if src_display.startswith('../'):
                # If it goes up directories, show abbreviated form
                src_display = f".../{source.parent.name}/{source.name}"
        except ValueError:
            # Not relative to cwd
            src_str = str(source)
            home = str(Path.home())
            if src_str.startswith(home):
                src_display = "~" + src_str[len(home):]
            else:
                # Show parent/filename for readability
                if source.parent.name:
                    src_display = f".../{source.parent.name}/{source.name}"
                else:
                    src_display = source.name
        
        # Format destination path - show the meaningful parts
        dest_str = str(dest)
        
        # Check for Audio.Books in path
        if "Audio.Books" in dest_str:
            # Extract everything after Audio.Books
            parts = dest_str.split("Audio.Books/")
            if len(parts) > 1:
                dest_display = f".../Audio.Books/{parts[1]}"
            else:
                dest_display = dest_str
        else:
            # For other paths, show parent/filename
            if dest.parent.name:
                dest_display = f".../{dest.parent.name}/{dest.name}"
            else:
                dest_display = dest.name
        
        return f"{src_display} → {dest_display}"
    
    def _files_are_identical(self, file1: Path, file2: Path) -> bool:
        """
        Check if two files are identical by comparing size and content hash.
        
        Returns:
            True if files are identical, False otherwise
        """
        try:
            # First check if they're the same file (same inode)
            if file1.samefile(file2):
                return True
        except (OSError, FileNotFoundError):
            pass
        
        # Check if both exist
        if not file1.exists() or not file2.exists():
            return False
        
        # Quick check: file sizes
        if file1.stat().st_size != file2.stat().st_size:
            return False
        
        # For small files, compare content directly
        file_size = file1.stat().st_size
        if file_size < 1024 * 1024:  # Less than 1MB
            try:
                return file1.read_bytes() == file2.read_bytes()
            except Exception:
                return False
        
        # For larger files, compare by hash
        try:
            hash1 = hashlib.md5()
            hash2 = hashlib.md5()
            
            with open(file1, 'rb') as f1, open(file2, 'rb') as f2:
                # Read in chunks
                while True:
                    chunk1 = f1.read(8192)
                    chunk2 = f2.read(8192)
                    if not chunk1 and not chunk2:
                        break
                    hash1.update(chunk1)
                    hash2.update(chunk2)
            
            return hash1.hexdigest() == hash2.hexdigest()
        except Exception:
            return False
    
    def _prompt_overwrite(self, source_path: Path, dest_path: Path) -> str:
        """
        Prompt user for overwrite decision.
        
        Returns:
            'yes' - overwrite this file
            'no' - skip this file
            'all' - overwrite all files
            'quit' - stop the operation
            'identical' - files are the same
        """
        if self.overwrite_all:
            return 'yes'
        
        # Check if files are identical
        if self._files_are_identical(source_path, dest_path):
            return 'identical'
        
        # Show file comparison info
        console.print(f"\n[yellow]File already exists:[/yellow] {dest_path}")
        
        # Get file sizes for comparison
        source_size = source_path.stat().st_size
        dest_size = dest_path.stat().st_size
        
        def format_size(size):
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    return f"{size:.1f}{unit}"
                size /= 1024.0
            return f"{size:.1f}TB"
        
        console.print(f"  Source: {format_size(source_size)} | Destination: {format_size(dest_size)}")
        
        if source_size == dest_size:
            console.print("  [dim]Files have same size but different content[/dim]")
        else:
            size_diff = source_size - dest_size
            if size_diff > 0:
                console.print(f"  [dim]Source is {format_size(abs(size_diff))} larger[/dim]")
            else:
                console.print(f"  [dim]Destination is {format_size(abs(size_diff))} larger[/dim]")
        
        console.print("Overwrite? [[green]y[/green]]es / [[red]n[/red]]o / [[cyan]a[/cyan]]ll / [[magenta]q[/magenta]]uit: ", end="")
        
        while True:
            choice = input().lower().strip()
            if choice in ['y', 'yes']:
                return 'yes'
            elif choice in ['n', 'no']:
                return 'no'
            elif choice in ['a', 'all']:
                self.overwrite_all = True
                return 'yes'
            elif choice in ['q', 'quit']:
                return 'quit'
            else:
                console.print("Please enter y/n/a/q: ", end="")
        
    def _load_config(self, config_path: Optional[Path] = None) -> Dict:
        """Load configuration from YAML file."""
        if config_path is None:
            # Check for config in order of preference:
            # 1. $HOME/audtag.yaml (user config, or AUDTAG_CONFIG_HOME if set)
            # 2. ./audtag.yaml (current directory)
            # 3. ./tasks.yaml (legacy name for backwards compatibility)
            
            # Use AUDTAG_CONFIG_HOME if set (for sudo usage)
            import os
            config_home = os.environ.get('AUDTAG_CONFIG_HOME', str(Path.home()))
            home_config = Path(config_home) / "audtag.yaml"
            local_config = Path.cwd() / "audtag.yaml"
            legacy_config = Path.cwd() / "tasks.yaml"
            
            if home_config.exists():
                config_path = home_config
            elif local_config.exists():
                config_path = local_config
            elif legacy_config.exists():
                config_path = legacy_config
                if self.debug:
                    console.print(f"[dim]Using legacy tasks.yaml - consider renaming to audtag.yaml[/dim]")
            else:
                # Default to home config location even if it doesn't exist
                config_path = home_config
        else:
            config_path = Path(config_path)
            
        if not config_path.exists():
            if self.debug:
                console.print(f"[dim]No config file found at {config_path}[/dim]")
                console.print(f"[dim]Create ~/audtag.yaml or ./audtag.yaml to define tasks[/dim]")
            return {'tasks': []}
            
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f) or {}
                if self.debug:
                    console.print(f"[dim]Loaded config from {config_path}[/dim]")
                return config
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to load config from {config_path}: {e}[/yellow]")
            return {'settings': {'enabled': False}, 'tasks': []}
    
    def _get_file_metadata(self, file_path: Path) -> Dict[str, str]:
        """Extract metadata from audio file for use in patterns."""
        metadata = {
            'filename': file_path.stem,
            'ext': file_path.suffix.lstrip('.'),
            'date': datetime.now(),
        }
        
        # Try to extract year from filename if it's in format (YYYY)
        import re
        year_match = re.search(r'\((\d{4})\)', file_path.stem)
        if year_match:
            metadata['year'] = year_match.group(1)
        
        # For cover images, try to extract metadata from directory structure
        if file_path.suffix.lower() in ['.jpg', '.jpeg', '.png'] and 'cover' in file_path.stem.lower():
            # Try to get artist from parent's parent directory (e.g., .../Author Name/Book Title/)
            if file_path.parent.parent.name and file_path.parent.parent.name != 'Audio.Books.incoming':
                metadata['artist'] = file_path.parent.parent.name
            
            # Try to get album from parent directory
            if file_path.parent.name:
                metadata['album'] = file_path.parent.name
            
            # Also try to extract from the cover filename if it follows a pattern
            # e.g., "Book Title (2020) - cover.jpg"
            cover_match = re.match(r'^(.+?)\s*\(\d{4}\)\s*-\s*cover', file_path.stem)
            if cover_match and not metadata.get('album'):
                metadata['album'] = cover_match.group(1).strip()
        
        try:
            audio = File(file_path)
            if audio and audio.tags:
                # Extract common tags based on file format
                if file_path.suffix.lower() == '.mp3':
                    from mutagen.id3 import ID3
                    tags = audio.tags
                    metadata['title'] = str(tags.get('TIT2', [''])[0]) if tags.get('TIT2') else ''
                    metadata['artist'] = str(tags.get('TPE1', [''])[0]) if tags.get('TPE1') else ''
                    metadata['album'] = str(tags.get('TALB', [''])[0]) if tags.get('TALB') else ''
                    metadata['composer'] = str(tags.get('TCOM', [''])[0]) if tags.get('TCOM') else ''
                    metadata['genre'] = str(tags.get('TCON', [''])[0]) if tags.get('TCON') else ''
                    year_from_tag = str(tags.get('TDRC', [''])[0]) if tags.get('TDRC') else ''
                    if year_from_tag:  # Only override if tag has year
                        metadata['year'] = year_from_tag
                    # Extract track number
                    track = tags.get('TRCK')
                    if track:
                        track_str = str(track[0])
                        metadata['track'] = int(track_str.split('/')[0]) if '/' in track_str else int(track_str) if track_str.isdigit() else 0
                    else:
                        metadata['track'] = 0
                        
                elif file_path.suffix.lower() in ['.m4b', '.m4a', '.aac']:
                    metadata['title'] = audio.tags.get('\xa9nam', [''])[0] or ''
                    metadata['artist'] = audio.tags.get('\xa9ART', [''])[0] or ''
                    metadata['album'] = audio.tags.get('\xa9alb', [''])[0] or ''
                    metadata['composer'] = audio.tags.get('\xa9wrt', [''])[0] or ''
                    metadata['genre'] = audio.tags.get('\xa9gen', [''])[0] or ''
                    year_from_tag = audio.tags.get('\xa9day', [''])[0] or ''
                    if year_from_tag:  # Only override if tag has year
                        metadata['year'] = year_from_tag
                    track = audio.tags.get('trkn', [(0, 0)])[0]
                    metadata['track'] = track[0] if isinstance(track, tuple) else track
                    
                elif file_path.suffix.lower() in ['.ogg', '.oga', '.opus', '.flac']:
                    metadata['title'] = audio.tags.get('title', [''])[0] or ''
                    metadata['artist'] = audio.tags.get('artist', [''])[0] or ''
                    metadata['album'] = audio.tags.get('album', [''])[0] or ''
                    metadata['composer'] = audio.tags.get('composer', [''])[0] or ''
                    metadata['genre'] = audio.tags.get('genre', [''])[0] or ''
                    year_from_tag = audio.tags.get('date', [''])[0] or ''
                    if year_from_tag:  # Only override if tag has year
                        metadata['year'] = year_from_tag
                    track = audio.tags.get('tracknumber', ['0'])[0]
                    metadata['track'] = int(track.split('/')[0]) if '/' in str(track) else int(track) if str(track).isdigit() else 0
                    
        except Exception as e:
            if self.debug:
                console.print(f"[yellow]Warning: Could not read metadata from {file_path}: {e}[/yellow]")
        
        # Clean up metadata - remove any path separators that could cause issues
        for key, value in metadata.items():
            if isinstance(value, str):
                # Replace path separators and other problematic characters
                value = re.sub(r'[<>:"/\\|?*]', '_', value)
                # Remove leading/trailing spaces and dots
                value = value.strip('. ')
                metadata[key] = value
                
        return metadata
    
    def _format_pattern(self, pattern: str, metadata: Dict[str, Any]) -> str:
        """
        Format a naming pattern with metadata.
        
        Supports:
        - {variable} - Simple substitution
        - {track:02d} - Formatted track number with zero padding
        - {date:%Y-%m-%d} - Date formatting
        """
        import re
        result = pattern
        
        # Handle date formatting
        if '{date:' in result and 'date' in metadata:
            date_pattern = re.compile(r'\{date:([^}]+)\}')
            for match in date_pattern.finditer(pattern):
                date_format = match.group(1)
                formatted_date = metadata['date'].strftime(date_format)
                result = result.replace(match.group(0), formatted_date)
        
        # Handle track formatting
        if '{track:' in result and 'track' in metadata:
            track_pattern = re.compile(r'\{track:(\d+)d\}')
            for match in track_pattern.finditer(pattern):
                padding = int(match.group(1))
                formatted_track = str(metadata['track']).zfill(padding)
                result = result.replace(match.group(0), formatted_track)
        
        # Handle simple substitutions
        for key, value in metadata.items():
            if isinstance(value, (str, int)):
                result = result.replace(f'{{{key}}}', str(value))
        
        # Clean up any remaining unreplaced variables
        # This handles cases where metadata doesn't have a value for a variable
        # Replace {year} with empty string if year is not in metadata
        result = re.sub(r'\{[^}]+\}', '', result)
        
        # Clean up multiple spaces and parentheses with nothing inside
        result = re.sub(r'\(\s*\)', '', result)  # Remove empty parentheses
        result = re.sub(r'\s+', ' ', result)  # Collapse multiple spaces
        result = result.strip()
        
        return result
    
    def _execute_move(self, file_path: Path, task_config: Dict) -> bool:
        """Execute a move task."""
        metadata = self._get_file_metadata(file_path)
        
        # Format destination path
        dest_dir = self._format_pattern(task_config['destination'], metadata)
        dest_dir = Path(dest_dir).expanduser()
        
        # Format filename
        # For cover images, preserve the original filename
        if file_path.suffix.lower() in ['.jpg', '.jpeg', '.png'] and 'cover' in file_path.stem.lower():
            new_filename = file_path.name
        else:
            naming_pattern = task_config.get('naming_pattern', '{filename}.{ext}')
            new_filename = self._format_pattern(naming_pattern, metadata)
        
        dest_path = dest_dir / new_filename
        
        if self.dry_run:
            if dest_path.exists():
                if self._files_are_identical(file_path, dest_path):
                    console.print(f"[green]✓[/green] {file_path.name} → {new_filename} [dim](identical)[/dim]")
                else:
                    console.print(f"  {file_path.name} → {new_filename} [yellow](exists)[/yellow]")
            else:
                console.print(f"  {file_path.name} → {new_filename}")
            return True
        
        # Check if destination exists
        if dest_path.exists():
            choice = self._prompt_overwrite(file_path, dest_path)
            if choice == 'identical':
                # For move operation, delete the source file even if identical exists at destination
                try:
                    file_path.unlink()
                    console.print(f"[green]✓[/green] {file_path.name} → {new_filename} [dim](identical, source removed)[/dim]")
                    return True
                except Exception as e:
                    console.print(f"[red]Failed to remove source file {file_path.name}: {e}[/red]")
                    return False
            elif choice == 'no':
                console.print(f"[yellow]⊘[/yellow] {file_path.name} [dim](skipped)[/dim]")
                return False
            elif choice == 'quit':
                console.print(f"[red]Operation cancelled[/red]")
                raise KeyboardInterrupt("User cancelled operation")
        
        # Create directories if needed
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            shutil.move(str(file_path), str(dest_path))
            console.print(f"[green]✓[/green] {file_path.name} → {new_filename}")
            return True
        except PermissionError as e:
            console.print(f"[red]Permission denied:[/red] Cannot move {file_path.name}")
            console.print(f"[dim]Try running with sudo or check file permissions[/dim]")
            return False
        except Exception as e:
            console.print(f"[red]Failed to move {file_path.name}: {e}[/red]")
            return False
    
    def _execute_copy(self, file_path: Path, task_config: Dict) -> bool:
        """Execute a copy task."""
        metadata = self._get_file_metadata(file_path)
        
        # Format destination path
        dest_dir = self._format_pattern(task_config['destination'], metadata)
        dest_dir = Path(dest_dir).expanduser()
        
        # Format filename
        # For cover images, preserve the original filename
        if file_path.suffix.lower() in ['.jpg', '.jpeg', '.png'] and 'cover' in file_path.stem.lower():
            new_filename = file_path.name
        else:
            naming_pattern = task_config.get('naming_pattern', '{filename}.{ext}')
            new_filename = self._format_pattern(naming_pattern, metadata)
        
        dest_path = dest_dir / new_filename
        
        if self.dry_run:
            if dest_path.exists():
                if self._files_are_identical(file_path, dest_path):
                    console.print(f"[green]✓[/green] {file_path.name} → {new_filename} [dim](identical)[/dim]")
                else:
                    console.print(f"  {file_path.name} → {new_filename} [yellow](exists)[/yellow]")
            else:
                console.print(f"  {file_path.name} → {new_filename}")
            return True
        
        # Check if destination exists
        if dest_path.exists():
            choice = self._prompt_overwrite(file_path, dest_path)
            if choice == 'identical':
                console.print(f"[green]✓[/green] {file_path.name} → {new_filename} [dim](identical)[/dim]")
                return True  # Count as success since file is already there
            elif choice == 'no':
                console.print(f"[yellow]⊘[/yellow] {file_path.name} [dim](skipped)[/dim]")
                return False
            elif choice == 'quit':
                console.print(f"[red]Operation cancelled[/red]")
                raise KeyboardInterrupt("User cancelled operation")
        
        # Create directories if needed
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            shutil.copy2(str(file_path), str(dest_path))
            console.print(f"[green]✓[/green] {file_path.name} → {new_filename}")
            return True
        except PermissionError as e:
            console.print(f"[red]Permission denied:[/red] Cannot copy {file_path.name}")
            console.print(f"[dim]Try running with sudo or check file permissions[/dim]")
            return False
        except Exception as e:
            console.print(f"[red]Failed to copy {file_path.name}: {e}[/red]")
            return False
    
    def _execute_rename(self, file_path: Path, task_config: Dict) -> bool:
        """Execute a rename task."""
        metadata = self._get_file_metadata(file_path)
        
        # Format new filename
        # For cover images, preserve the original filename structure
        if file_path.suffix.lower() in ['.jpg', '.jpeg', '.png'] and 'cover' in file_path.stem.lower():
            new_filename = file_path.name
        else:
            naming_pattern = task_config.get('naming_pattern', '{filename}.{ext}')
            new_filename = self._format_pattern(naming_pattern, metadata)
        
        dest_path = file_path.parent / new_filename
        
        # Skip if renaming to same name
        if dest_path == file_path:
            console.print(f"[green]✓[/green] {file_path.name} [dim](already correct)[/dim]")
            return True
        
        # For rename, just show filenames since they're in the same directory
        if self.dry_run:
            if dest_path.exists():
                if self._files_are_identical(file_path, dest_path):
                    console.print(f"[green]✓[/green] {file_path.name} → {new_filename} [dim](identical)[/dim]")
                else:
                    console.print(f"  {file_path.name} → {new_filename} [yellow](exists)[/yellow]")
            else:
                console.print(f"  {file_path.name} → {new_filename}")
            return True
        
        # Check if destination exists
        if dest_path.exists():
            choice = self._prompt_overwrite(file_path, dest_path)
            if choice == 'identical':
                console.print(f"[green]✓[/green] {file_path.name} → {new_filename} [dim](identical)[/dim]")
                return True  # Count as success since file is already there
            elif choice == 'no':
                console.print(f"[yellow]⊘[/yellow] {file_path.name} [dim](skipped)[/dim]")
                return False
            elif choice == 'quit':
                console.print(f"[red]Operation cancelled[/red]")
                raise KeyboardInterrupt("User cancelled operation")
        
        try:
            file_path.rename(dest_path)
            console.print(f"[green]✓[/green] {file_path.name} → {new_filename}")
            return True
        except PermissionError as e:
            console.print(f"[red]Permission denied:[/red] Cannot rename {file_path.name}")
            console.print(f"[dim]Try running with sudo or check file permissions[/dim]")
            return False
        except Exception as e:
            console.print(f"[red]Failed to rename {file_path.name}: {e}[/red]")
            return False
    
    def execute_task(self, task_name: str, files: List[Path], dry_run: Optional[bool] = None) -> None:
        """
        Execute a specific task on the given files.
        
        Args:
            task_name: Name of the task to execute
            files: List of file paths to process
            dry_run: Override dry_run setting (None uses config setting)
        """
        # Override dry_run if specified
        if dry_run is not None:
            self.dry_run = dry_run
            
        # Find the task in config
        tasks = self.config.get('tasks', [])
        task_config = None
        for task in tasks:
            if task.get('name') == task_name:
                task_config = task
                break
        
        if not task_config:
            console.print(f"[red]Task '{task_name}' not found in configuration[/red]")
            return
            
        task_description = task_config.get('description', task_name)
        console.print(f"[bold cyan]{task_description}{' (DRY RUN)' if self.dry_run else ''}[/bold cyan]\n")
        
        # Check if we have files to process
        if not files:
            console.print("[yellow]No audio files to process![/yellow]")
            return
        
        # Group files by directory for better display
        files_by_dir = {}
        for f in files:
            dir_path = f.parent
            if dir_path not in files_by_dir:
                files_by_dir[dir_path] = []
            files_by_dir[dir_path].append(f)
        
        success_count = 0
        fail_count = 0
        
        # Process each directory group
        for dir_path, dir_files in files_by_dir.items():
            # First, check for destination conflicts
            dest_paths = {}
            for file_path in dir_files:
                metadata = self._get_file_metadata(file_path)
                
                if task_name in ['move', 'copy']:
                    dest_dir = self._format_pattern(task_config['destination'], metadata)
                    dest_dir = Path(dest_dir).expanduser()
                    naming_pattern = task_config.get('naming_pattern', '{filename}.{ext}')
                    new_filename = self._format_pattern(naming_pattern, metadata)
                    dest_path = dest_dir / new_filename
                elif task_name == 'rename':
                    naming_pattern = task_config.get('naming_pattern', '{filename}.{ext}')
                    new_filename = self._format_pattern(naming_pattern, metadata)
                    dest_path = file_path.parent / new_filename
                else:
                    continue
                
                # Track destination paths
                if dest_path in dest_paths:
                    dest_paths[dest_path].append(file_path)
                else:
                    dest_paths[dest_path] = [file_path]
            
            # Check for conflicts (multiple source files going to same destination)
            conflicts = {dest: sources for dest, sources in dest_paths.items() if len(sources) > 1}
            if conflicts:
                console.print(f"[red]⚠ ERROR: Multiple files would have the same destination![/red]")
                console.print(f"[red]This usually happens when track numbers are missing from metadata.[/red]\n")
                
                for dest_path, source_files in conflicts.items():
                    console.print(f"[yellow]Destination:[/yellow] {dest_path.name}")
                    console.print(f"[yellow]Source files:[/yellow]")
                    for src in source_files:
                        console.print(f"  • {src.name}")
                    console.print()
                
                console.print(f"[red]Operation cancelled to prevent data loss.[/red]")
                console.print(f"[dim]Fix: Tag the files first with proper track numbers, or use a naming pattern that includes {{filename}}[/dim]")
                fail_count += len(dir_files)
                continue  # Skip this directory group
            
            # Show the directory context
            if task_name == 'move':
                # For move, show source -> destination directory
                # Get sample metadata to show destination
                sample_metadata = self._get_file_metadata(dir_files[0])
                dest_dir = self._format_pattern(task_config['destination'], sample_metadata)
                console.print(f"[dim]{dir_path}/[/dim]")
                console.print(f"[dim]→ {dest_dir}[/dim]\n")
            elif task_name == 'copy':
                # Similar to move
                sample_metadata = self._get_file_metadata(dir_files[0])
                dest_dir = self._format_pattern(task_config['destination'], sample_metadata)
                console.print(f"[dim]{dir_path}/[/dim]")
                console.print(f"[dim]→ {dest_dir}[/dim]\n")
            else:
                # For rename, just show the directory
                console.print(f"[dim]{dir_path}/[/dim]\n")
            
            # Process files in this directory
            for file_path in dir_files:
                try:
                    if task_name == 'move':
                        success = self._execute_move(file_path, task_config)
                    elif task_name == 'copy':
                        success = self._execute_copy(file_path, task_config)
                    elif task_name == 'rename':
                        success = self._execute_rename(file_path, task_config)
                    else:
                        console.print(f"[yellow]Unknown task type: {task_name}[/yellow]")
                        return
                    
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1
                except KeyboardInterrupt:
                    console.print(f"\n[yellow]Operation cancelled by user[/yellow]")
                    console.print(f"[dim]Processed {success_count} files before cancellation[/dim]")
                    return
                except Exception as e:
                    console.print(f"[red]Error processing {file_path.name}: {e}[/red]")
                    fail_count += 1
        
        # Print summary
        console.print(f"\n[bold]Summary:[/bold] {success_count} succeeded, {fail_count} failed")
    
    def execute_tasks(self, files: List[Path]) -> None:
        """
        Execute all tasks on the given files.
        Note: This method is deprecated. Use execute_task() for individual tasks.
        
        Args:
            files: List of file paths to process
        """
        tasks = self.config.get('tasks', [])
        
        if not tasks:
            if self.debug:
                console.print("[dim]No tasks defined[/dim]")
            return
        
        console.print(f"\n[bold cyan]Executing tasks{' (DRY RUN)' if self.dry_run else ''}...[/bold cyan]")
        
        for task in tasks:
            task_name = task.get('name', 'unknown')
            task_description = task.get('description', task_name)
            
            console.print(f"\n[bold]Task: {task_description}[/bold]")
            
            success_count = 0
            fail_count = 0
            
            for file_path in files:
                if task_name == 'move':
                    success = self._execute_move(file_path, task)
                elif task_name == 'copy':
                    success = self._execute_copy(file_path, task)
                elif task_name == 'rename':
                    success = self._execute_rename(file_path, task)
                else:
                    console.print(f"[yellow]Unknown task type: {task_name}[/yellow]")
                    continue
                
                if success:
                    success_count += 1
                else:
                    fail_count += 1
            
            # Summary for this task
            console.print(f"[dim]Task complete: {success_count} succeeded, {fail_count} failed[/dim]")
        
        if self.dry_run:
            console.print("\n[yellow]This was a dry run. No files were actually modified.[/yellow]")