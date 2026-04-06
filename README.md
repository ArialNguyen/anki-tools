# � Anki Vocabulary Tools: Gemini Vocab Builder

## 🎯 Overview

**Anki Vocabulary Tools** is a high-performance, enterprise-grade Python application designed to intelligently enrich English vocabulary data for language learners. Leveraging Google's Gemini API ecosystem, this tool automates the generation of precise definitions, phonetic transcriptions, parts of speech, and contextual example sentences—all formatted perfectly for seamless Anki flashcard imports.

Built with IELTS reading preparation in mind, this tool transforms raw vocabulary lists into production-ready flashcard decks, saving countless hours of manual research and formatting.

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| **🧠 Intelligent API Management** | Automatic API key rotation and model fallback. If one key hits rate limits, the system instantly switches to another without interrupting the workflow. Includes sophisticated quota tracking (RPM, TPM, RPD). |
| **⚡ Concurrent Processing** | Multi-threaded architecture processes multiple vocabulary items simultaneously, maximizing throughput while respecting API rate limits. |
| **🛡️ Data Validation** | Strict AI prompting and validation logic ensures 100% data completeness. Invalid responses trigger automatic retries with exponential backoff. |
| **💾 Smart Checkpointing** | Real-time progress saving after every batch. Interrupted jobs resume exactly where they left off with zero wasted API quota. |
| **📊 Live Dashboard** | Beautiful, real-time terminal UI powered by Rich library displays progress, thread status, API key health, and quota consumption. |
| **⚙️ Flexible Configuration** | All system parameters (models, chunk sizes, quotas) configurable via `config.json`—no code changes needed. |
| **📤 Anki-Ready Export** | CSV output formatted specifically for Anki import with cloze deletion support and bilingual example sentences. |

---

## 📂 Folder Structure

```
anki-tools/
├── README.md                      # Project documentation (this file)
├── requirements.txt               # Python package dependencies
├── config.json                    # Application configuration & model settings
├── .env                           # API keys (secured, not in version control)
├── rpd_tracker.json               # Daily request tracking & quota monitoring
├── run_app.py                     # Main application entry point
├── check_models.py                # Utility to verify available Gemini models
├── convert_anki.py                # Utility to convert and validate CSV exports
│
├── modules/                       # Core application package
│   ├── __init__.py                # Package initializer
│   ├── vocab_engine.py            # Main orchestrator: threading, API calls, data processing
│   ├── api_manager.py             # API quota tracking, key rotation, rate limiting
│   └── terminal_ui.py             # Live dashboard UI using Rich library
│
└── exports/                       # Generated CSV exports (Anki-format ready)
    ├── day2_anki.csv
    ├── day3_anki.csv
    └── ...

```

---

## 🚀 Installation

### Prerequisites
- Python 3.8 or higher
- Google Gemini API access (free tier available)
- An Excel file with vocabulary data (`.xlsx` or `.xlsm`)

### Step 1: Clone or Download the Repository

```bash
cd ~/your/preferred/directory
git clone <repository-url>
cd anki-tools
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

**Dependencies include:**
- `pandas` - Data manipulation and CSV handling
- `requests` - HTTP requests to Gemini API
- `python-dotenv` - Secure environment variable management
- `rich` - Beautiful terminal UI and formatting
- `openpyxl` - Excel file processing

### Step 3: Configure API Keys

Create a `.env` file in the project root and add your Gemini API keys:

```bash
# .env file
API_KEY_1=your_first_gemini_api_key_here
API_KEY_2=your_second_gemini_api_key_here
API_KEY_3=your_third_gemini_api_key_here
```

**How to get API keys:**
1. Visit [Google AI Studio](https://aistudio.google.com)
2. Click "Get API Key"
3. Create a new API key
4. Copy and paste into `.env`

> ⚠️ **Security Note:** Never commit `.env` to version control. It's already in `.gitignore`.

### Step 4: Update Project Path (Optional)

Edit `run_app.py` to point to your vocabulary Excel file:

```python
engine.run(
    relative_source_path="path/to/your/Vocab_file.xlsm",  # Update this path
    sheet_name="Day 8",                                     # Update sheet name
    output_csv_name="day8_anki.csv"                        # Output file name
)
```

---

## ▶️ Running the Project

### Basic Usage

```bash
python run_app.py
```

The application will:
1. Load your API keys from `.env`
2. Prompt you to confirm the number of active API keys
3. Read vocabulary from your Excel file
4. Process each word with Gemini API
5. Display real-time progress on an interactive dashboard
6. Save results to CSV in `exports/` directory

### Example Output

```
✅ Loaded 3 API keys.

❓ Continue with 3 active keys? (yes/no): yes

📂 Processing: Day 8 Vocabulary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Progress: [████████████░░░░░░░] 65% | 13/20 words
Active Workers: 3/3
Next Batch: "abandon, ability, able..."

API Status:
├─ Key #1: ✅ Ready (45 RPD remaining)
├─ Key #2: ⏳ Cooldown (2.3s)
└─ Key #3: ✅ Ready (48 RPD remaining)

💾 Last saved: 45 seconds ago
```

---

## ⚙️ Environment Configuration

### `.env` File (API Keys)

Create this file with your API credentials:

```bash
# Recommended: Use multiple keys for higher throughput
API_KEY_1=sk-...your-first-key...
API_KEY_2=sk-...your-second-key...
API_KEY_3=sk-...your-third-key...
```

### `config.json` (System Parameters)

Main configuration file controlling behavior:

```json
{
  "CHUNK_SIZE": 3,
  "MAX_RETRIES_AI": 5,
  "API_KEY_COOLDOWN": 5,
  "OUTPUT_DIR": "exports",
  "MODELS_CONFIG": {
    "gemini-3.1-flash-lite-preview": {
      "RPM": 15,
      "TPM": 250000,
      "RPD": 500
    },
    "gemini-2.5-flash-lite": {
      "RPM": 10,
      "TPM": 250000,
      "RPD": 20
    }
  }
}
```

**Parameter Explanation:**

| Parameter | Description | Example |
|-----------|-------------|---------|
| `CHUNK_SIZE` | Words processed per API call | `3` (processes 3 words at once) |
| `MAX_RETRIES_AI` | Retry attempts if API fails | `5` (up to 5 retries per batch) |
| `API_KEY_COOLDOWN` | Seconds before reusing a rate-limited key | `5` |
| `OUTPUT_DIR` | Directory to save CSV exports | `"exports"` |
| `RPM` | Requests per minute limit for a model | `15` |
| `TPM` | Tokens per minute limit | `250000` |
| `RPD` | Requests per day limit | `500` |

**Tips for Configuration:**
- Start with `CHUNK_SIZE: 3` for reliability
- Increase `CHUNK_SIZE` to 5-10 for faster processing if API allows
- Use multiple API keys to distribute quota across different limits
- Adjust `RPM` and `TPM` based on your API tier

---

## 📖 Usage Examples

### Example 1: Process Daily Vocabulary Set

```bash
# Update run_app.py
engine.run(
    relative_source_path="../vocab_lists/day_5.xlsm",
    sheet_name="Vocabulary",
    output_csv_name="day5_anki.csv"
)

# Run the application
python run_app.py
```

Output: `exports/day5_anki.csv` with enriched vocabulary ready for Anki.

### Example 2: Using the Utility Scripts

Check available Gemini models:
```bash
python check_models.py
```

Validate and convert exports:
```bash
python convert_anki.py
```

---

## 🛠️ Architecture & Design

### Core Components

**1. VocabEnricher** (`vocab_engine.py`)
- Main orchestrator managing the entire workflow
- Handles multi-threading with concurrent.futures
- Manages data persistence and checkpointing
- Coordinates with API manager and UI

**2. KeyManager** (`api_manager.py`)
- Tracks quota consumption (RPM, TPM, RPD) per API key
- Implements intelligent key rotation
- Monitors rate limits and triggers cooldowns
- Saves daily quota usage to `rpd_tracker.json`

**3. DashboardUI** (`terminal_ui.py`)
- Real-time progress visualization
- Thread status monitoring
- API health metrics
- Built with Rich library for beautiful formatting

**4. Configuration Management** (`config.json`)
- Centralized model and quota definitions
- Decoupled from application code
- Easy updates without redeployment

### Request Flow

```
Excel File
    ↓
VocabEnricher reads & chunks words
    ↓
KeyManager selects available API key
    ↓
Worker threads call Gemini API concurrently
    ↓
Response validation (retry if incomplete)
    ↓
DashboardUI updates progress in real-time
    ↓
Auto-save to CSV after each batch
    ↓
Anki-formatted CSV in exports/
```

---

## 🤝 Contribution Guidelines

We welcome contributions! Here's how to participate:

### Reporting Bugs

1. Check existing [GitHub Issues](https://github.com/yourusername/anki-tools/issues)
2. Create a new issue with:
   - Clear description of the problem
   - Steps to reproduce
   - Expected vs. actual behavior
   - Python version and OS
   - Relevant config snippets

### Proposing Features

1. Open a discussion issue first
2. Describe the feature and its benefits
3. Provide use cases and examples
4. Wait for maintainer feedback before implementing

### Submitting Code Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make changes following the existing code style
4. Add tests for new functionality
5. Commit with clear messages: `git commit -m "Add feature X"`
6. Push to your fork: `git push origin feature/your-feature-name`
7. Submit a Pull Request with a detailed description

### Code Style Guidelines

- Follow PEP 8 standards
- Use meaningful variable names
- Add docstrings to functions and classes
- Keep functions focused and under 50 lines when possible
- Use type hints where applicable
- Comment complex logic

### Development Workflow

```bash
# Set up development environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Make your changes
# Test locally
python run_app.py

# Run quality checks
pylint modules/
```

### Pull Request Checklist

- [ ] Tested with multiple API keys
- [ ] Verified CSV output format
- [ ] Updated documentation if needed
- [ ] Added relevant comments
- [ ] No hardcoded credentials or paths
- [ ] Follows existing code style

---

## 📝 License & Attribution

This project is shared for educational and personal use. Please respect any attribution requirements and licensing terms.

---

## 💬 Support & Questions

- **Documentation:** See this README and inline code comments
- **Common Issues:** Refer to the Troubleshooting section below
- **Feature Requests:** Open an issue on GitHub

### Troubleshooting

| Issue | Solution |
|-------|----------|
| **"No API Keys found in .env"** | Ensure `.env` exists in project root with valid API keys |
| **"429 Too Many Requests"** | Increase `API_KEY_COOLDOWN` in config.json or add more API keys |
| **CSV import fails in Anki** | Verify CSV format matches Anki expectations; check for special characters |
| **Excel file not found** | Verify the `relative_source_path` in `run_app.py` is correct |
| **Incomplete enrichment data** | Increase `MAX_RETRIES_AI` in config.json and check API responses |

---

## 🎓 Learning Resources

- [Anki Documentation](https://docs.ankiweb.net/)
- [Google Gemini API Guide](https://ai.google.dev/tutorials/rest_quickstart)
- [Python Concurrent Programming](https://docs.python.org/3/library/concurrent.futures.html)
- [Pandas Documentation](https://pandas.pydata.org/docs/)

---

**Last Updated:** April 2026  
**Version:** 1.0.0  
**Python:** 3.8+