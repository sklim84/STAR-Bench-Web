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


# requirements-tools.txt installs the tool layer alone; the UI packages are
# checked only when the full app environment (requirements.txt) is installed.
_TOOL_PACKAGES = ["duckdb", "pyarrow", "pandas", "networkx", "dotenv", "openai",
                  "sklearn", "xgboost"]
_APP_PACKAGES = ["streamlit", "streamlit_option_menu", "plotly", "anthropic"]


class TestDependencies:
    """필수 의존성 패키지 설치 확인."""

    @pytest.mark.parametrize("package_name", _TOOL_PACKAGES)
    def test_tool_dependency_installed(self, package_name):
        """도구 계층 패키지가 설치되어 있는지 확인."""
        importlib.import_module(package_name)

    @pytest.mark.parametrize("package_name", _APP_PACKAGES)
    def test_app_dependency_installed(self, package_name):
        """앱 전용 패키지는 설치된 환경에서만 확인한다."""
        pytest.importorskip(
            package_name,
            reason=f"'{package_name}' is an app-only dependency (requirements.txt)",
        )


class TestProjectStructure:
    """프로젝트 디렉토리 구조 테스트."""

    def test_required_directories(self):
        """필수 디렉토리가 존재하는지 확인."""
        required_dirs = ["_datasets", "src", "_pages", "scripts", "tests"]
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

    def test_env_example_exists(self):
        """.env.example이 존재하는지 확인 (.env는 로컬 전용)."""
        assert (config.BASE_DIR / ".env.example").exists()
