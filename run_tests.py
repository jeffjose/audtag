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
Test runner for audtag test suite.
Run all tests or specific test modules.
"""

import sys
import unittest
from pathlib import Path

def run_tests(pattern='test*.py', verbosity=2):
    """
    Run tests matching the pattern.
    
    Args:
        pattern: File pattern to match test files (default: 'test*.py')
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)
    
    Returns:
        0 if all tests pass, 1 otherwise
    """
    # Get the tests directory
    tests_dir = Path(__file__).parent / 'tests'
    
    # Discover and load tests
    loader = unittest.TestLoader()
    suite = loader.discover(str(tests_dir), pattern=pattern)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    if result.wasSuccessful():
        print("\n✓ All tests passed!")
        return 0
    else:
        print("\n✗ Some tests failed")
        if result.failures:
            print(f"\nFailed tests:")
            for test, _ in result.failures:
                print(f"  - {test}")
        if result.errors:
            print(f"\nTests with errors:")
            for test, _ in result.errors:
                print(f"  - {test}")
        return 1

def main():
    """Main entry point for test runner."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run audtag tests')
    parser.add_argument(
        '--pattern', '-p',
        default='test*.py',
        help='Pattern to match test files (default: test*.py)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Quiet output (only summary)'
    )
    
    args = parser.parse_args()
    
    # Determine verbosity
    verbosity = 2 if args.verbose else 0 if args.quiet else 1
    
    # Run tests
    sys.exit(run_tests(pattern=args.pattern, verbosity=verbosity))

if __name__ == '__main__':
    main()