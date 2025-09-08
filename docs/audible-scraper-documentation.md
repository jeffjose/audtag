# Mp3tag Audible.com Web Source Script Documentation

## Overview
This is an Mp3tag web source script that scrapes Audible.com to fetch audiobook metadata for automatic tagging of audio files.

**File**: `Audible.com#Search by Album.src`  
**Base URL**: www.audible.com  
**Search Method**: Combines artist name and album title (removes CD numbers from album)  
**Installation Path**: `%appdata%\roaming\mp3tag\data\sources`

## Configuration Parameters
- **Name**: Audible.com
- **IndexUrl**: `https://www.audible.com/search?ipRedirectOverride=true&overrideBaseCountry=true&keywords=`
- **AlbumUrl**: `https://www.audible.com`
- **WordSeparator**: `+`
- **SearchBy**: `%artist% $regexp(%album%,'[- ]+cd ?\d+$',,1)`
- **Encoding**: url-utf-8

## Two-Stage Processing

### Stage 1: Index Script (Search Results)
**Lines**: 27-102

Parses the Audible search results page to extract basic information for each audiobook:

#### Extracted Fields:
- **URL** (lines 48-52): Book detail page URL with redirect override parameters
- **Album** (lines 54-72): Main title, including subtitle if present
- **Author** (lines 74-79): Primary author from authorLabel
- **Duration** (lines 82-86): Runtime from runtimeLabel
- **Year** (lines 88-91): Release date
- **Language** (lines 93-96): Book language

#### Technical Details:
- Focuses on the "center-3" to "center-4" content area
- Cleans HTML with regex replacements for whitespace
- Iterates through search results using `<h3 class="bc-heading"` markers
- Continues while "bc-color-link" exists (max 99 results)

### Stage 2: Album Script (Book Details)
**Lines**: 103-399

Fetches and parses individual book detail pages for comprehensive metadata:

#### Primary Metadata Extracted:

##### Cover Art (lines 108-115)
- Extracts image URL from JSON-LD data
- Upgrades thumbnail URLs to 500px versions (_SL175_ → _SS500_)

##### Core Book Information:
- **ASIN** (lines 117-122): Amazon Standard Identification Number
- **Album Title** (lines 124-148): Main title, handles titles with colons
- **Subtitle** (lines 150-160): Secondary title if present
- **Album Artist** (lines 162-172): Author(s) from authorLabel
- **Composer** (lines 173-183): Narrator(s) from narratorLabel

##### Series Information (lines 184-223):
- **Series Name**: Extracted from seriesLabel
- **Series Part**: Book number in series
- **Album Sort**: Formatted as "Series # - Title"
- **Content Group**: "Series, Book #X" format
- Sets SHOWMOVEMENT=1 for series books

##### Additional Metadata:
- **Genres** (lines 225-252): Up to 2 categories, separated by "/"
- **Rating** (lines 254-275): User rating (defaults to 0.1 or 0.2 if missing)
- **Comment/Description** (lines 277-319): Publisher's summary
- **Publisher** (lines 305-309): Publishing company
- **Copyright** (lines 356-398): Copyright year and holder

#### iTunes-Specific Tags:
- **ITUNESMEDIATYPE**: Set to "Audiobook" (lines 339-341)
- **ITUNESGAPLESS**: Set to "1" for gapless playback (lines 343-345)

#### Special Field Mappings:
- **Artist**: Combines Author and Narrator as "Author, Narrator"
- **WWWAUDIOFILE**: Stores the Audible URL
- **DESCRIPTION**: Duplicate of Comment for MP4 compatibility
- **MOVEMENTNAME/MOVEMENT**: Alternative storage for series information

## Data Processing Techniques

### HTML Parsing Methods:
- `findline`: Locates specific HTML patterns
- `findinline`: Finds patterns within current line
- `joinuntil`: Combines multiple lines until pattern
- `sayuntil`: Outputs text until pattern found
- `regexpreplace`: Cleans HTML tags and formatting

### String Manipulation:
- Removes excessive whitespace with regex
- Handles special characters and HTML entities
- Formats compound fields (e.g., "Series, Book #1")

## Example Search Query
For searching "breakneck":
1. **Search URL**: `https://www.audible.com/search?keywords=breakneck`
2. **Process**: 
   - Fetches search results
   - Parses each result's basic info
   - User selects desired book
   - Fetches detailed page for selected book
   - Extracts all metadata fields

## Version History
- 2013-03-11: Initial creation by dano for Audible.de
- 2013-09-20: Updated
- 2020-03-24: Updated
- 2020-04-06: Updated to Audible.com
- 2020-06-28: Updated to region independent (u/Carlyone)
- 2020-08-05: Latest update

## Debug Options
The script includes commented debug options:
- Write HTML input to file: `C:\Users\%user%\Desktop\mp3tag.html`
- Debug output: `C:\Users\%user%\Desktop\mp3tagdebug.txt`

## Notes
- Handles various Audible page layouts and format changes
- Robust error handling for missing fields (uses conditional checks)
- Supports both standalone books and series entries
- Automatically formats data for optimal Mp3tag and iTunes compatibility