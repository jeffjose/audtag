# audtag

A command-line tool for automatically tagging audiobook files with metadata from Audible.com. Designed for simplicity and efficiency, audtag handles multiple files in parallel, preserves smart titles, and supports post-tagging operations like organizing your audiobook library.

## Installation

audtag requires Python 3.10+ and uses `uv` for dependency management.

### Install from GitHub (Recommended)

Install audtag globally using `uv tool`:

```bash
# Install from GitHub
uv tool install --from git+https://github.com/jeffjose/audtag.git audtag

# Verify installation
audtag --help

# Update to latest version
uv tool upgrade audtag
```

### Development Installation

For development, install in editable mode using `uv tool`:

```bash
# Clone the repository
git clone https://github.com/jeffjose/audtag.git
cd audtag

# Install in editable mode for development
uv tool install -e .

# Now you can use audtag globally and changes are reflected immediately
audtag --help
```

### Install from Source

Alternatively, clone and run directly:

```bash
# Clone the repository
git clone https://github.com/jeffjose/audtag.git
cd audtag

# Make the wrapper executable
chmod +x audtag

# Run directly (dependencies auto-installed via uv)
./audtag --help
```

## Basic Usage

### Tag Single File

```bash
./audtag tag audiobook.m4b
```

The tool searches Audible.com for metadata, presents matching results, and applies your selection to the file.

### Tag Multiple Files

```bash
./audtag tag *.m4b
```

Process multiple audiobooks at once. Files are automatically grouped by book title for efficient batch processing.

### View File Information

```bash
./audtag info audiobook.m4b
```

Display current metadata tags for any audio file without modifying it.

## Advanced Features

### Parallel Processing

audtag automatically detects optimal worker count based on CPU cores for maximum performance:

```bash
# Use auto-detected workers (default)
./audtag tag *.m4b

# Specify custom worker count
./audtag tag --workers 8 *.m4b
```

### Smart Title Preservation

When files already contain series or subtitle information in brackets, audtag intelligently preserves and merges this data:

```bash
# Original filename: "The Hobbit [Lord of the Rings 0.5].m4b"
# After tagging: Title includes series information
```

### Interactive Search Retry

When Audible search returns no results, audtag provides interactive options to retry with different queries, skip the current book, or cancel processing. This ensures you can always find the right metadata even for books with complex or ambiguous titles:

```bash
# Search yields no results
# Options presented:
#   1) Try a different search query
#   2) Skip this book
#   3) Cancel all
```

### Post-Tagging Tasks

Configure automated tasks to organize your library after tagging. Create an `audtag.yaml` configuration file:

```yaml
tasks:
  - name: "Organize Audiobooks"
    description: "Move tagged files to library"
    type: move
    destination: "~/Audio.Books/{author}/{album} ({year})"
    naming_pattern: "{album} - {track:02d} - {title}.{ext}"
```

Run tasks after tagging:

```bash
./audtag task "Organize Audiobooks" *.m4b
```

### Dry Run Mode

Preview task operations without making changes:

```bash
./audtag task "Organize Audiobooks" --dry-run *.m4b
```

## Pattern Variables

Task configurations support flexible pattern variables for organizing files:

### Directory Patterns

- `{author}` - Book author
- `{album}` - Book title/album
- `{year}` - Publication year
- `{genre}` - Book genre
- `{narrator}` - Narrator name
- `{series}` - Series name
- `{series_position}` - Position in series

### Filename Patterns

- `{title}` - Chapter/track title
- `{track}` - Track number (use `:02d` for zero-padding)
- `{filename}` - Original filename without extension
- `{ext}` - File extension

### Example Patterns

```yaml
# Organize by author/series
destination: "~/Audiobooks/{author}/{series}/{album} ({year})"

# Organize by genre
destination: "~/Audiobooks/{genre}/{author} - {album}"

# Simple flat structure
destination: "~/Audiobooks/{author} - {album} ({year})"
```

## Supported Formats

audtag works with all major audiobook formats:

- M4B/M4A (Apple audiobooks)
- MP3
- FLAC
- OGG Vorbis
- Opus

## Metadata Fields

The tool fetches and applies comprehensive metadata:

- Title and subtitle
- Author and narrator
- Album artist (for proper library grouping)
- Publication year
- Genre
- Series information
- Track numbers and total tracks
- Cover artwork (saved as separate file, not embedded)
- Duration information

## File Grouping

When processing multiple files, audtag intelligently groups them:

- Multi-part audiobooks are recognized and tagged together
- Series are detected from filenames
- Consistent metadata across all parts
- Preserves track numbering for proper playback order
- Cover images are automatically included in move/copy operations
- Metadata extracted from directory structure for cover images

## Configuration

audtag looks for configuration in the following order:

1. Specified via `--config` option
2. `audtag.yaml` in current directory
3. `~/.config/audtag/config.yaml`

### Example Configuration

```yaml
# Default task to run
default_task: "Organize Library"

# Task definitions
tasks:
  - name: "Organize Library"
    type: move
    destination: "~/Audio.Books/{author}/{album} ({year})"
    naming_pattern: "{track:02d} - {title}.{ext}"
    
  - name: "Backup Originals"
    type: copy
    destination: "~/Audiobook.Backups/{year}/{album}"
    
  - name: "Rename Only"
    type: rename
    naming_pattern: "{author} - {album} - {track:02d}.{ext}"
```

## Performance

audtag is optimized for speed and efficiency:

- Parallel file processing with configurable workers
- Intelligent CPU core detection
- Concurrent background tagging for improved responsiveness
- Batch operations for related files
- Minimal memory footprint
- Progress indicators for long operations

## Error Handling

The tool provides clear feedback and graceful error handling:

- Network failures trigger automatic retries
- Permission issues include helpful suggestions
- Duplicate detection prevents accidental overwrites
- Detailed debug output available with `--debug` flag

## Tips

1. **Bulk Processing**: Process entire directories efficiently:

   ```bash
   find ~/Audiobooks -name "*.m4b" -exec ./audtag tag {} +
   ```

2. **Preview Changes**: Always use `--dry-run` first for task operations:

   ```bash
   ./audtag task "Organize" --dry-run *.m4b
   ```

3. **Debug Issues**: Enable debug output for troubleshooting:

   ```bash
   ./audtag --debug tag problematic.m4b
   ```

4. **Sudo Support**: The wrapper correctly handles sudo for system-wide operations:

   ```bash
   sudo ./audtag task "Move to System Library" *.m4b
   ```

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome. Please submit pull requests with tests for new features.

## Requirements

- Python 3.10+
- uv (automatically installed if not present)
- Internet connection for Audible.com metadata fetching
