from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATASETS_DIR = BASE_DIR / "_datasets"
MODELS_DIR = BASE_DIR / "_models"
DOCS_DIR = BASE_DIR / "_docs"

# Data files
CSV_PATH = DATASETS_DIR / "HOFINET.csv"
PARQUET_PATH = DATASETS_DIR / "HOFINET.parquet"
DUCKDB_PATH = DATASETS_DIR / "HOFINET.duckdb"

# API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# DuckDB settings
DUCKDB_THREADS = os.cpu_count()
