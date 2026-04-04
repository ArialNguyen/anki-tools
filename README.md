# Gemini Vocab Builder (Turbo Mode)

A powerful tool for automatically enriching English vocabulary data with definitions, parts of speech, and example sentences using Google Gemini API, optimized for Anki import.

## Features

- **Multi-threading & Multi-API Key Support**: Circumvents Google API rate limits (429 errors) using round-robin key rotation.
- **Strict Validation**: Ensures 100% completeness by enforcing non-empty responses from AI, with automatic retries.
- **Auto-save & Resume**: Real-time checkpointing after each batch. Supports resuming interrupted processes without wasting API calls.
- **Optimized for Anki**: Generates front/back card formats suitable for flashcard learning.

## Prerequisites

- Python 3.8 or higher
- Google Gemini API keys (stored in `.env` file)
- Microsoft Excel file (`Vocab_mountain_Writting.xlsm`) in the parent directory

## Installation

### 1. Clone or Download the Repository

Ensure you have the project files in your local directory.

### 2. Create a Virtual Environment

It is recommended to use a virtual environment to manage dependencies.

```bash
# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
# venv\Scripts\activate
```

### 3. Install Dependencies

With the virtual environment activated, install the required packages:

```bash
pip install -r requirements.txt
```

### 4. Configure API Keys

Create a `.env` file in the project root with your Google Gemini API keys:

```
GEMINI_API_KEY_1=your_first_api_key_here
GEMINI_API_KEY_2=your_second_api_key_here
# Add more keys as needed
```

## Usage

1. Ensure the Excel file `Vocab_mountain_Writting.xlsm` is located in the parent directory (`../`).

2. Run the script:

```bash
python convert_anki.py
```

The script will:
- Validate API keys
- Process vocabulary from the specified Excel sheet
- Generate enriched data with AI-generated content
- Save output to CSV files

## Configuration

- **Excel File**: Update the `run_import` call in `convert_anki.py` to specify the desired sheet (e.g., 'Day 2').
- **Output**: Modify the output CSV filename as needed.
- **Chunk Size**: Adjust `CHUNK_SIZE` in `process_sheet` for batch processing.

## Troubleshooting

- **API Key Issues**: Ensure keys are valid and have sufficient quota.
- **File Not Found**: Verify the Excel file path is correct relative to the script location.
- **Dependencies**: Confirm all packages are installed in the active virtual environment.

## License

This project is for personal use. Ensure compliance with Google Gemini API terms of service.