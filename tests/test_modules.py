"""모듈 임포트 및 프로젝트 구조 테스트.

검증 항목:
- 모든 핵심 모듈이 정상적으로 임포트되는지
- 프로젝트 디렉토리 구조가 올바른지
- 필수 의존성 패키지가 설치되어 있는지
"""

import importlib
from pathlib import Path

import pytest

import config


class TestModuleImports:
    """핵심 모듈 임포트 테스트."""

    def test_import_config(self):
        """config 모듈 임포트가 정상 동작하는지 확인."""
        import config
        assert hasattr(config, "BASE_DIR")

    def test_import_src_data_db(self):
        """src.data.db 모듈 임포트가 정상 동작하는지 확인."""
        from src.data import db
        assert hasattr(db, "get_connection")
        assert hasattr(db, "query")
        assert hasattr(db, "query_arrow")
        assert hasattr(db, "close")

    def test_import_src_data_loader(self):
        """src.data.loader 모듈 임포트가 정상 동작하는지 확인."""
        from src.data import loader
        assert hasattr(loader, "csv_to_parquet")
        assert hasattr(loader, "load_parquet")
        assert hasattr(loader, "SCHEMA")
        assert hasattr(loader, "CONVERT_OPTIONS")

    def test_import_src_package(self):
        """src 패키지 임포트가 정상 동작하는지 확인."""
        import src
        import src.data
        import src.features


class TestDependencies:
    """필수 의존성 패키지 설치 확인."""

    @pytest.mark.parametrize("package_name", [
        "streamlit",
        "streamlit_option_menu",
        "duckdb",
        "pyarrow",
        "pandas",
        "plotly",
        "networkx",
        "dotenv",
        "openai",
        "anthropic",
        "sklearn",
        "xgboost",
    ])
    def test_dependency_installed(self, package_name):
        """필수 패키지가 설치되어 있는지 확인."""
        try:
            importlib.import_module(package_name)
        except ImportError:
            pytest.fail(f"패키지 '{package_name}'이 설치되어 있지 않습니다")


class TestProjectStructure:
    """프로젝트 디렉토리 구조 테스트."""

    def test_required_directories(self):
        """필수 디렉토리가 존재하는지 확인."""
        required_dirs = ["_datasets", "_models", "_docs", "src", "_pages"]
        for dir_name in required_dirs:
            dir_path = config.BASE_DIR / dir_name
            assert dir_path.exists(), f"디렉토리 '{dir_name}'이 없습니다"
            assert dir_path.is_dir()

    def test_required_files(self):
        """필수 파일이 존재하는지 확인."""
        required_files = [
            "app.py",
            "config.py",
            "requirements.txt",
            "src/__init__.py",
            "src/data/__init__.py",
            "src/data/db.py",
            "src/data/loader.py",
        ]
        for file_name in required_files:
            file_path = config.BASE_DIR / file_name
            assert file_path.exists(), f"파일 '{file_name}'이 없습니다"

    def test_page_files_exist(self):
        """Streamlit 페이지 파일들이 존재하는지 확인."""
        page_files = [
            "_pages/dashboard_page.py",
            "_pages/network_page.py",
            "_pages/detection_page.py",
            "_pages/agent_page.py",
        ]
        for file_name in page_files:
            file_path = config.BASE_DIR / file_name
            assert file_path.exists(), f"페이지 파일 '{file_name}'이 없습니다"

    def test_gitignore_exists(self):
        """.gitignore 파일이 존재하는지 확인."""
        assert (config.BASE_DIR / ".gitignore").exists()

    def test_env_file_exists(self):
        """.env 파일이 존재하는지 확인."""
        assert (config.BASE_DIR / ".env").exists(), ".env 파일이 없습니다 (API 키 설정 필요)"
