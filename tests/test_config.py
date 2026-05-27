"""config.py 기능 테스트.

검증 항목:
- 경로 상수가 올바른 디렉토리/파일을 가리키는지
- 필수 디렉토리가 실제로 존재하는지
- DuckDB 스레드 설정이 유효한 값인지
"""

from pathlib import Path

import pytest

import config

# raw HOFINET 데이터/학습 모델은 비공개(거버넌스)이며 로컬에서 재생성된다.
# 공개 repo의 fresh clone에는 없으므로, 존재할 때만 관련 테스트를 실행한다.
_HAS_CSV = config.CSV_PATH.exists()
_HAS_PARQUET = config.PARQUET_PATH.exists()


class TestPathConstants:
    """경로 상수 검증."""

    def test_base_dir_is_project_root(self):
        """BASE_DIR이 프로젝트 루트(config.py가 위치한 디렉토리)인지 확인."""
        assert config.BASE_DIR.exists()
        assert (config.BASE_DIR / "config.py").exists()

    def test_datasets_dir_exists(self):
        """_datasets 디렉토리가 존재하는지 확인."""
        assert config.DATASETS_DIR.exists()
        assert config.DATASETS_DIR.is_dir()

    @pytest.mark.skipif(not config.MODELS_DIR.exists(),
                        reason="_models는 모델 학습 시 런타임 생성됨 (repo 미포함)")
    def test_models_dir_exists(self):
        """_models 디렉토리가 존재하는지 확인."""
        assert config.MODELS_DIR.exists()
        assert config.MODELS_DIR.is_dir()

    def test_docs_dir_exists(self):
        """_docs 디렉토리가 존재하는지 확인."""
        assert config.DOCS_DIR.exists()
        assert config.DOCS_DIR.is_dir()

    def test_csv_path_points_to_correct_file(self):
        """CSV_PATH가 HOFINET.csv를 가리키는지 확인."""
        assert config.CSV_PATH.name == "HOFINET.csv"
        assert config.CSV_PATH.parent == config.DATASETS_DIR

    def test_parquet_path_points_to_correct_file(self):
        """PARQUET_PATH가 HOFINET.parquet를 가리키는지 확인."""
        assert config.PARQUET_PATH.name == "HOFINET.parquet"
        assert config.PARQUET_PATH.parent == config.DATASETS_DIR

    def test_duckdb_path_points_to_correct_file(self):
        """DUCKDB_PATH가 HOFINET.duckdb를 가리키는지 확인."""
        assert config.DUCKDB_PATH.name == "HOFINET.duckdb"
        assert config.DUCKDB_PATH.parent == config.DATASETS_DIR

    def test_all_paths_are_pathlib_objects(self):
        """모든 경로 상수가 Path 객체인지 확인."""
        for attr_name in ["BASE_DIR", "DATASETS_DIR", "MODELS_DIR", "DOCS_DIR",
                          "CSV_PATH", "PARQUET_PATH", "DUCKDB_PATH"]:
            attr = getattr(config, attr_name)
            assert isinstance(attr, Path), f"{attr_name}은 Path 객체여야 합니다"


class TestDataFiles:
    """데이터 파일 존재 확인."""

    @pytest.mark.skipif(not _HAS_CSV, reason="HOFINET.csv 비공개 (로컬 재생성)")
    def test_csv_file_exists(self):
        """HOFINET.csv 파일이 존재하는지 확인."""
        assert config.CSV_PATH.exists(), "HOFINET.csv 파일이 없습니다"

    @pytest.mark.skipif(not _HAS_PARQUET, reason="HOFINET.parquet 비공개 (로컬 재생성)")
    def test_parquet_file_exists(self):
        """HOFINET.parquet 파일이 존재하는지 확인."""
        assert config.PARQUET_PATH.exists(), "HOFINET.parquet 파일이 없습니다"

    @pytest.mark.skipif(not _HAS_CSV, reason="HOFINET.csv 비공개 (로컬 재생성)")
    def test_csv_file_not_empty(self):
        """CSV 파일이 비어있지 않은지 확인."""
        assert config.CSV_PATH.stat().st_size > 0

    @pytest.mark.skipif(not _HAS_PARQUET, reason="HOFINET.parquet 비공개 (로컬 재생성)")
    def test_parquet_file_not_empty(self):
        """Parquet 파일이 비어있지 않은지 확인."""
        assert config.PARQUET_PATH.stat().st_size > 0

    @pytest.mark.skipif(not (_HAS_CSV and _HAS_PARQUET),
                        reason="HOFINET 원천 데이터 비공개 (로컬 재생성)")
    def test_parquet_smaller_than_csv(self):
        """Parquet 파일이 CSV보다 작은지 확인 (압축 효과)."""
        csv_size = config.CSV_PATH.stat().st_size
        parquet_size = config.PARQUET_PATH.stat().st_size
        assert parquet_size < csv_size, "Parquet이 CSV보다 커서는 안 됩니다"


class TestDuckDBSettings:
    """DuckDB 설정 검증."""

    def test_threads_is_positive_integer(self):
        """DUCKDB_THREADS가 양의 정수인지 확인."""
        assert isinstance(config.DUCKDB_THREADS, int)
        assert config.DUCKDB_THREADS > 0


class TestAPIKeys:
    """API 키 설정 검증."""

    def test_api_key_attributes_exist(self):
        """API 키 속성이 존재하는지 확인 (값은 빈 문자열일 수 있음)."""
        assert hasattr(config, "OPENAI_API_KEY")
        assert hasattr(config, "ANTHROPIC_API_KEY")

    def test_api_keys_are_strings(self):
        """API 키가 문자열 타입인지 확인."""
        assert isinstance(config.OPENAI_API_KEY, str)
        assert isinstance(config.ANTHROPIC_API_KEY, str)
