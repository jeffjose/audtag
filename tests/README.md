# Audtag Test Suite

This directory contains the test suite for the audtag audiobook tagger.

## Running Tests

### Run All Tests
```bash
# From project root using uv
uv run --script run_tests.py

# Or using the shell script
./test.sh

# With verbose output
./test.sh --verbose

# Quiet mode (only summary)
./test.sh --quiet

# Or directly execute the test runner
./run_tests.py
```

### Run Specific Test Module
```bash
# Run only core tests
uv run -m unittest tests.test_core

# Run only integration tests  
uv run -m unittest tests.test_integration

# Or directly execute the test file
./tests/test_core.py
```

### Run Specific Test Class
```bash
# Run only AudibleScraper tests
uv run -m unittest tests.test_core.TestAudibleScraper

# Run only CLI tests
uv run -m unittest tests.test_integration.TestCLICommands
```

### Run Specific Test Method
```bash
# Run a single test
uv run -m unittest tests.test_core.TestAudibleScraper.test_initialization
```

## Test Structure

### test_core.py
Core functionality tests:
- **TestAudibleScraper** - Tests for Audible.com scraping
- **TestAudiobookTagger** - Tests for metadata tagging
- **TestFileGrouping** - Tests for smart file grouping
- **TestCoverDownload** - Tests for cover art downloading
- **TestUtilityFunctions** - Tests for helper functions

### test_integration.py
Integration and workflow tests:
- **TestCLICommands** - Tests for CLI command structure
- **TestTaggingWorkflow** - Tests for complete tagging workflows
- **TestErrorHandling** - Tests for error handling and recovery

## Test Coverage

The tests cover:
- Audible search and metadata extraction
- File tagging with different formats (MP3, M4B, etc.)
- Smart file grouping algorithms
- Cover art downloading with fallback
- CLI commands and user interactions
- Error handling and recovery
- Parallel processing

## Writing New Tests

When adding new features:
1. Add unit tests to `test_core.py` for new functions/classes
2. Add integration tests to `test_integration.py` for workflows
3. Run tests with `./test.sh` to ensure everything passes
4. Use mocking to avoid network calls and file system dependencies

## Dependencies

Tests use Python's built-in `unittest` framework with mocking.
No additional test dependencies are required beyond the main project dependencies.