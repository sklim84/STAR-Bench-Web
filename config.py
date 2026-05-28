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

# OpenRouter (primary provider for the analysis agent — OpenAI-compatible API).
# If OPENROUTER_API_KEY is set, agent.chat() routes through OpenRouter; otherwise
# it falls back to direct OpenAI with OPENAI_API_KEY.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
# Optional OpenRouter rankings/analytics headers (recommended by OpenRouter docs).
OPENROUTER_HTTP_REFERER = os.getenv("OPENROUTER_HTTP_REFERER", "")
OPENROUTER_X_TITLE = os.getenv("OPENROUTER_X_TITLE", "STAR-Bench AML Assistant")

# DuckDB settings
DUCKDB_THREADS = os.cpu_count()

# Memgraph settings
MEMGRAPH_HOST = os.getenv("MEMGRAPH_HOST", "localhost")
MEMGRAPH_PORT = int(os.getenv("MEMGRAPH_PORT", "7687"))
MEMGRAPH_USER = os.getenv("MEMGRAPH_USER", "")
MEMGRAPH_PASSWORD = os.getenv("MEMGRAPH_PASSWORD", "")
MEMGRAPH_URI = f"bolt://{MEMGRAPH_HOST}:{MEMGRAPH_PORT}"
