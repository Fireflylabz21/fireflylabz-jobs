# Local Development Guide: Building with VS Code

This guide provides a step-by-step walkthrough for setting up, writing, testing, and debugging your $0/month AI Job Newsletter system locally using **Visual Studio Code (VS Code)** or AI-native editors like **Cursor** or **Windsurf**.

---

## 1. Prerequisites & Recommended Tools

### Essential Software
* **[VS Code](https://code.visualstudio.com/)** or **[Cursor](https://www.cursor.com/)** (an AI-first fork of VS Code with built-in LLM capabilities).
* **[Python 3.11+](https://www.python.org/downloads/)** installed on your system.
* **[Git](https://git-scm.com/)** installed for version control.

### Recommended VS Code Extensions
Open VS Code, press `Ctrl+P` (or `Cmd+P` on macOS), and install these extensions:
1. **Python** (`ms-python.python`): Full Python support (autocompletion, debugging, linting).
2. **Pylance** (`ms-python.vscode-pylance`): Fast language support and type checking.
3. **Dotenv Official** (`mikestead.dotenv`): Syntax highlighting for `.env` files containing local API keys.
4. **GitHub Actions** (`github.vscode-github-actions`): Manage and monitor GitHub workflows directly inside VS Code.
5. **REST Client** (`humao.rest-client`): Optional tool to test external API endpoints directly in editor tabs.

---

## 2. Directory Structure Setup

Create a clean folder on your machine and open it in VS Code:

```text
ai-job-newsletter/
├── .github/
│   └── workflows/
│       └── newsletter.yml      # GitHub Actions automation schedule
├── .vscode/
│   └── launch.json             # VS Code debugger configuration
├── .env                        # Local secret environment variables (GIT-IGNORED)
├── .gitignore                  # Prevents committing secrets to GitHub
├── gcp_key.json                # Google Cloud Service Account JSON key (GIT-IGNORED)
├── main.py                     # Main processing script
└── requirements.txt            # Python dependencies
```

---

## 3. Step-by-Step Local Setup

### Step 3.1: Open Project in VS Code
1. Open VS Code.
2. Go to **File $\rightarrow$ Open Folder...** and select your `ai-job-newsletter` folder.
3. Open a terminal inside VS Code by pressing ``Ctrl + ` `` (or `Terminal -> New Terminal`).

### Step 3.2: Create and Activate a Python Virtual Environment
Isolate your project packages using Python's virtual environment module (`venv`):

* **macOS / Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```
* **Windows (PowerShell):**
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```

*Tip: VS Code will prompt you in the bottom right corner: "We noticed a new virtual environment has been created. Do you want to select it for the workspace?" Click **Yes**.*

### Step 3.3: Install Dependencies
Create `requirements.txt` with the required libraries:

```text
psycopg2-binary>=2.9.9
gspread>=6.1.0
google-auth>=2.29.0
google-generativeai>=0.5.0
resend>=2.0.0
python-dotenv>=1.0.0
```

Install them in your active virtual environment:
```bash
pip install -r requirements.txt
```

---

## 4. Local Environment Variables & Secrets Management

To run and test the script on your computer without exposing sensitive API keys to GitHub:

### Step 4.1: Create a `.gitignore` File
Create a `.gitignore` file in your root folder:
```text
# Environments
venv/
.env

# Google GCP Keys & Credentials
*.json
!package.json

# Python Cache
__pycache__/
*.pyc
.vscode/
```

### Step 4.2: Add GCP Service Account Key
Download your Service Account JSON key file from Google Cloud Console, place it in the project root, and name it `gcp_key.json`.

### Step 4.3: Create a `.env` File
Create a `.env` file in your project root:
```env
GEMINI_API_KEY=your_google_ai_studio_api_key_here
SUPABASE_DB_URL=postgresql://postgres.xxxx:your_password@aws-0-region.pooler.supabase.com:6543/postgres
RESEND_API_KEY=re_123456789_your_resend_key
GOOGLE_SHEET_NAME=Job Newsletter Subscribers
GCP_SERVICE_ACCOUNT_FILE=gcp_key.json
```

---

## 5. Adapting `main.py` for Local Environment Loading

Update the configuration section of `main.py` so it seamlessly loads `.env` variables locally while falling back to environment variables when executed in GitHub Actions:

```python
import os
import json
import time
import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import resend

# Load local .env file if running on local machine
load_dotenv()

# Config parameters
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Job Newsletter Subscribers")

# Google Credentials handling (local file vs GitHub Actions string)
GCP_SERVICE_ACCOUNT_KEY = os.getenv("GCP_SERVICE_ACCOUNT_KEY")
GCP_SERVICE_ACCOUNT_FILE = os.getenv("GCP_SERVICE_ACCOUNT_FILE", "gcp_key.json")

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

if GCP_SERVICE_ACCOUNT_KEY:
    # Running in GitHub Actions
    service_account_info = json.loads(GCP_SERVICE_ACCOUNT_KEY)
    creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
elif os.path.exists(GCP_SERVICE_ACCOUNT_FILE):
    # Running locally
    creds = Credentials.from_service_account_file(GCP_SERVICE_ACCOUNT_FILE, scopes=scopes)
else:
    raise ValueError("No GCP Service Account credentials found!")

# Initialize Clients
genai.configure(api_key=GEMINI_API_KEY)
resend.api_key = RESEND_API_KEY
gs_client = gspread.authorize(creds)
```

---

## 6. Debugging in VS Code

VS Code allows you to pause execution, inspect variable states, and step through functions line-by-line.

### Step 6.1: Create Debug Configuration
Create `.vscode/launch.json`:
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Debug Newsletter Pipeline",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/main.py",
            "console": "integratedTerminal",
            "justMyCode": true
        }
    ]
}
```

### Step 6.2: Running the Debugger
1. Click on **Run and Debug** icon on the left sidebar (or press `Ctrl+Shift+D` / `Cmd+Shift+D`).
2. Set a **Breakpoint** by clicking in the left margin next to any line number in `main.py` (e.g., inside `evaluate_and_rank_jobs`).
3. Press **F5** to start debugging.
4. Use the controls at the top to **Step Over (F10)**, **Step Into (F11)**, or **Continue (F5)** to inspect variables in the **Variables Window**.

---

## 7. Committing & Deploying to GitHub from VS Code

1. Open Source Control panel in VS Code (`Ctrl+Shift+G` or `Cmd+Shift+G`).
2. Stage changes by clicking `+` next to files (ensure `.env` and `gcp_key.json` are **NOT** listed under staged changes).
3. Type a commit message: `feat: add initial job newsletter pipeline code`.
4. Click **Commit**, then **Publish Branch** to send the code to your GitHub repository.
5. In GitHub, add your production secrets under **Settings $\rightarrow$ Secrets and variables $\rightarrow$ Actions** as detailed in the deployment guide.