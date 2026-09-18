# Command Line Interface (CLI) & Migrations

```

The `fapix` command-line utility automates project management, user administration, database migrations, and development server execution.

---

## 🛠️ Installation & Setup

### Prerequisites

* **Python:** `3.10+`
* **Database:** SQLite *(Default)* or PostgreSQL

### Install from PyPI

```bash
pip install fapix

```

### Local / Editable Installation

```bash
# Clone repository
git clone [https://github.com/devHashim111/fapix](https://github.com/devHashim111/fapix)
cd fapix

# Setup virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install editable package & verify
pip install -e .
fapix --help

```

---

## 📁 Project & App Creation

### Create a Project

```bash
fapix startproject myproject
cd myproject

```

#### Generated Directory Structure

```text
myproject/
├── main.py            # Application entrypoint & router initialization
├── db_config.py       # Tortoise-ORM configuration & model registry
├── pyproject.toml     # Project metadata & Aerich configuration
└── apps/              # Business logic modules
    └── auth/          # Optional auth application

```

### Create a Custom App

```bash
fapix startapp product

```

---

## 🔄 Smart Database Migrations

Database migrations are powered by `aerich` with automated fallback handling.

### Global Migrations

```bash
fapix makemigrations
fapix migrate

```

### App-Specific Migrations

```bash
fapix makemigrations product

```

> 📌 **Self-Healing Engine:** If database tables or migration directories are uninitialized, `fapix migrate` automatically initializes database configurations and syncs missing files before applying schema upgrades.

---

## 🚀 Running the Server

```bash
# Default execution (Port 8000)
fapix runserver

# Custom port and log level
fapix runserver 9000 --log-level info

```
