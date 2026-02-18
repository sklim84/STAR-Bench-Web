"""src/data/graph_etl.py 단위 테스트.

검증 항목:
- run_etl(): 전체 ETL 흐름, Memgraph 미실행 시 {"error": ...} 반환, 기존 데이터 스킵
- _create_indexes(): 인덱스 생성 Cypher 호출 확인
- _load_companies(): 금융회사 노드 적재, 빈 DataFrame 처리
- _load_accounts(): 계좌 노드 배치 적재, BELONGS_TO 관계 생성
- _load_transfers(): 거래 엣지 배치 적재
- _df_to_transfer_batch(): DataFrame → dict 변환, NaN 처리
- clear_graph(): Memgraph 미실행 시 스킵, 실행 시 DETACH DELETE 호출
- get_graph_stats(): Memgraph 미실행 시 기본값, 실행 시 카운트 반환

테스트 전략:
- 실제 Memgraph 서버 없이 테스트
- graph_db.is_available(), graph_db.execute(), src.data.db.query()를 모킹
"""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# 공통 샘플 데이터
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_company_df():
    """금융회사 조회 결과 샘플."""
    return pd.DataFrame({"company_id": [1, 2, 3, 4]})


@pytest.fixture
def sample_account_df():
    """계좌-금융회사 매핑 조회 결과 샘플."""
    return pd.DataFrame({
        "account_id": [1001, 1002, 2001, 2002],
        "company_id": [1, 1, 2, 2],
    })


@pytest.fixture
def sample_transfer_df():
    """거래 데이터 샘플 (hofinet 스키마 기반)."""
    return pd.DataFrame({
        "source": [1001, 1002, 2001],
        "target": [2001, 2002, 1001],
        "거래일자": [20240101, 20240102, 20240103],
        "거래시간대": [9, 14, 21],
        "자금구분": [1, 3, 0],
        "매체구분": [1, 2, 3],
        "거래금액": [100000, 5000000, 250000],
        "이상거래여부": [0, 1, 0],
        "이상거래유형": [0, 3, 0],
    })


# ---------------------------------------------------------------------------
# run_etl()
# ---------------------------------------------------------------------------

class TestRunEtl:
    """run_etl() 함수 테스트."""

    def test_returns_error_when_memgraph_unavailable(self):
        """Memgraph 미실행 시 {'error': 'Memgraph 미실행'}을 반환하는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.is_available", return_value=False):
            result = graph_etl.run_etl()

        assert "error" in result
        assert result["error"] == "Memgraph 미실행"

    def test_skips_etl_when_data_already_exists(self):
        """기존 데이터(accounts > 0) 존재 시 ETL을 스킵하고 기존 카운트를 반환하는지 확인."""
        from src.data import graph_etl

        existing_stats = {
            "accounts": 5000,
            "companies": 20,
            "transfers": 100000,
            "belongs_to": 5000,
        }

        with patch("src.data.graph_etl.graph_db.is_available", return_value=True):
            with patch("src.data.graph_etl.get_graph_stats", return_value=existing_stats):
                result = graph_etl.run_etl()

        assert result["accounts"] == 5000
        assert result["companies"] == 20
        assert result["transfers"] == 100000
        assert result["elapsed_sec"] == 0.0

    def test_runs_full_etl_when_no_existing_data(self):
        """기존 데이터가 없을 때 전체 ETL을 실행하는지 확인."""
        from src.data import graph_etl

        empty_stats = {"accounts": 0, "companies": 0, "transfers": 0, "belongs_to": 0}

        with patch("src.data.graph_etl.graph_db.is_available", return_value=True):
            with patch("src.data.graph_etl.get_graph_stats", return_value=empty_stats):
                with patch("src.data.graph_etl._create_indexes") as mock_indexes:
                    with patch("src.data.graph_etl._load_companies", return_value=4) as mock_companies:
                        with patch("src.data.graph_etl._load_accounts", return_value=100) as mock_accounts:
                            with patch("src.data.graph_etl._load_transfers", return_value=1000) as mock_transfers:
                                result = graph_etl.run_etl(batch_size=500)

        mock_indexes.assert_called_once()
        mock_companies.assert_called_once()
        mock_accounts.assert_called_once_with(500)
        mock_transfers.assert_called_once_with(500)

        assert result["accounts"] == 100
        assert result["companies"] == 4
        assert result["transfers"] == 1000
        assert "elapsed_sec" in result
        assert result["elapsed_sec"] >= 0.0

    def test_returns_dict_with_required_keys_on_success(self):
        """ETL 성공 시 반환 딕셔너리에 필수 키가 모두 포함되는지 확인."""
        from src.data import graph_etl

        empty_stats = {"accounts": 0, "companies": 0, "transfers": 0, "belongs_to": 0}

        with patch("src.data.graph_etl.graph_db.is_available", return_value=True):
            with patch("src.data.graph_etl.get_graph_stats", return_value=empty_stats):
                with patch("src.data.graph_etl._create_indexes"):
                    with patch("src.data.graph_etl._load_companies", return_value=2):
                        with patch("src.data.graph_etl._load_accounts", return_value=50):
                            with patch("src.data.graph_etl._load_transfers", return_value=200):
                                result = graph_etl.run_etl()

        assert set(result.keys()) == {"accounts", "companies", "transfers", "elapsed_sec"}

    def test_default_batch_size_is_10000(self):
        """기본 batch_size가 10000인지 확인 (함수 시그니처)."""
        import inspect
        from src.data import graph_etl

        sig = inspect.signature(graph_etl.run_etl)
        assert sig.parameters["batch_size"].default == 10000


# ---------------------------------------------------------------------------
# _create_indexes()
# ---------------------------------------------------------------------------

class TestCreateIndexes:
    """_create_indexes() 함수 테스트."""

    def test_creates_account_and_company_indexes(self):
        """Account와 Company 인덱스 생성 Cypher가 호출되는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
            graph_etl._create_indexes()

        assert mock_execute.call_count == 2
        calls = [str(c) for c in mock_execute.call_args_list]
        assert any(":Account(id)" in c for c in calls)
        assert any(":Company(id)" in c for c in calls)

    def test_ignores_exception_from_existing_index(self):
        """이미 존재하는 인덱스로 인한 예외를 무시하는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.execute", side_effect=Exception("이미 존재")):
            # 예외가 전파되지 않아야 함
            graph_etl._create_indexes()


# ---------------------------------------------------------------------------
# _load_companies()
# ---------------------------------------------------------------------------

class TestLoadCompanies:
    """_load_companies() 함수 테스트."""

    def test_returns_company_count(self, sample_company_df):
        """금융회사 노드 수를 올바르게 반환하는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.db.query", return_value=sample_company_df):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                result = graph_etl._load_companies()

        assert result == 4
        mock_execute.assert_called_once()

    def test_returns_zero_when_df_empty(self):
        """빈 DataFrame 반환 시 0을 반환하는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.db.query", return_value=pd.DataFrame()):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                result = graph_etl._load_companies()

        assert result == 0
        mock_execute.assert_not_called()

    def test_creates_company_nodes_with_correct_cypher(self, sample_company_df):
        """MERGE(:Company) Cypher가 정확히 호출되는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.db.query", return_value=sample_company_df):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                graph_etl._load_companies()

        cypher_call = mock_execute.call_args[0][0]
        assert "MERGE" in cypher_call
        assert ":Company" in cypher_call
        assert "UNWIND" in cypher_call

    def test_passes_correct_batch_to_execute(self, sample_company_df):
        """execute()에 올바른 배치 파라미터가 전달되는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.db.query", return_value=sample_company_df):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                graph_etl._load_companies()

        params = mock_execute.call_args[0][1]
        assert "batch" in params
        batch = params["batch"]
        assert len(batch) == 4
        assert all(isinstance(item["id"], int) for item in batch)
        assert {item["id"] for item in batch} == {1, 2, 3, 4}


# ---------------------------------------------------------------------------
# _load_accounts()
# ---------------------------------------------------------------------------

class TestLoadAccounts:
    """_load_accounts() 함수 테스트."""

    def test_returns_account_count(self, sample_account_df):
        """계좌 노드 수를 올바르게 반환하는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.db.query", return_value=sample_account_df):
            with patch("src.data.graph_etl.graph_db.execute"):
                result = graph_etl._load_accounts(batch_size=100)

        assert result == 4

    def test_returns_zero_when_df_empty(self):
        """빈 DataFrame 반환 시 0을 반환하는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.db.query", return_value=pd.DataFrame()):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                result = graph_etl._load_accounts(batch_size=100)

        assert result == 0
        mock_execute.assert_not_called()

    def test_creates_belongs_to_relationship(self, sample_account_df):
        """BELONGS_TO 관계 생성 Cypher가 호출되는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.db.query", return_value=sample_account_df):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                graph_etl._load_accounts(batch_size=100)

        cypher_call = mock_execute.call_args[0][0]
        assert "BELONGS_TO" in cypher_call
        assert "MERGE" in cypher_call

    def test_batches_correctly_with_small_batch_size(self, sample_account_df):
        """batch_size보다 데이터가 많으면 여러 배치로 나누는지 확인."""
        from src.data import graph_etl

        # 4개 레코드를 2개씩 배치
        with patch("src.data.graph_etl.db.query", return_value=sample_account_df):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                result = graph_etl._load_accounts(batch_size=2)

        assert result == 4
        assert mock_execute.call_count == 2  # 2번 배치 호출

    def test_passes_account_and_company_id_in_batch(self, sample_account_df):
        """배치 딕셔너리에 id와 company_id가 포함되는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.db.query", return_value=sample_account_df):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                graph_etl._load_accounts(batch_size=100)

        params = mock_execute.call_args[0][1]
        batch = params["batch"]
        assert all("id" in item and "company_id" in item for item in batch)
        assert all(isinstance(item["id"], int) for item in batch)
        assert all(isinstance(item["company_id"], int) for item in batch)


# ---------------------------------------------------------------------------
# _load_transfers()
# ---------------------------------------------------------------------------

class TestLoadTransfers:
    """_load_transfers() 함수 테스트."""

    def test_returns_zero_when_no_data(self):
        """데이터가 없을 때 0을 반환하는지 확인."""
        from src.data import graph_etl

        count_df = pd.DataFrame({"cnt": [0]})

        with patch("src.data.graph_etl.db.query", return_value=count_df):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                result = graph_etl._load_transfers(batch_size=1000)

        assert result == 0
        mock_execute.assert_not_called()

    def test_returns_total_transfer_count(self, sample_transfer_df):
        """전체 거래 엣지 수를 올바르게 반환하는지 확인."""
        from src.data import graph_etl

        count_df = pd.DataFrame({"cnt": [3]})

        def mock_query(sql, *args, **kwargs):
            if "count(*)" in sql.lower():
                return count_df
            return sample_transfer_df

        with patch("src.data.graph_etl.db.query", side_effect=mock_query):
            with patch("src.data.graph_etl.graph_db.execute"):
                result = graph_etl._load_transfers(batch_size=1000)

        assert result == 3

    def test_creates_transfer_relationship_cypher(self, sample_transfer_df):
        """TRANSFER 관계 생성 Cypher가 호출되는지 확인."""
        from src.data import graph_etl

        count_df = pd.DataFrame({"cnt": [3]})

        def mock_query(sql, *args, **kwargs):
            if "count(*)" in sql.lower():
                return count_df
            return sample_transfer_df

        with patch("src.data.graph_etl.db.query", side_effect=mock_query):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                graph_etl._load_transfers(batch_size=1000)

        cypher_call = mock_execute.call_args[0][0]
        assert "TRANSFER" in cypher_call
        assert "CREATE" in cypher_call

    def test_uses_limit_and_offset_for_batching(self, sample_transfer_df):
        """배치 조회 시 LIMIT/OFFSET이 사용되는지 확인."""
        from src.data import graph_etl

        count_df = pd.DataFrame({"cnt": [6]})
        call_tracker = []

        def mock_query(sql, *args, **kwargs):
            call_tracker.append(sql)
            if "count(*)" in sql.lower():
                return count_df
            # 각 배치에 3개씩 반환
            return sample_transfer_df

        with patch("src.data.graph_etl.db.query", side_effect=mock_query):
            with patch("src.data.graph_etl.graph_db.execute"):
                graph_etl._load_transfers(batch_size=3)

        # LIMIT / OFFSET이 포함된 쿼리가 2번 호출되어야 함
        batch_queries = [q for q in call_tracker if "LIMIT" in q.upper()]
        assert len(batch_queries) == 2
        assert "OFFSET 0" in batch_queries[0]
        assert "OFFSET 3" in batch_queries[1]

    def test_breaks_when_batch_is_empty(self):
        """배치가 빈 DataFrame이면 반복을 중단하는지 확인."""
        from src.data import graph_etl

        count_df = pd.DataFrame({"cnt": [5]})
        empty_df = pd.DataFrame()
        call_count = 0

        def mock_query(sql, *args, **kwargs):
            nonlocal call_count
            if "count(*)" in sql.lower():
                return count_df
            call_count += 1
            return empty_df  # 항상 빈 DataFrame 반환

        with patch("src.data.graph_etl.db.query", side_effect=mock_query):
            with patch("src.data.graph_etl.graph_db.execute"):
                result = graph_etl._load_transfers(batch_size=5)

        # 첫 배치에서 빈 DataFrame이면 루프가 중단됨
        assert call_count == 1
        assert result == 0


# ---------------------------------------------------------------------------
# _df_to_transfer_batch()
# ---------------------------------------------------------------------------

class TestDfToTransferBatch:
    """_df_to_transfer_batch() 함수 테스트."""

    def test_returns_list_of_dicts(self, sample_transfer_df):
        """DataFrame을 딕셔너리 리스트로 변환하는지 확인."""
        from src.data import graph_etl

        result = graph_etl._df_to_transfer_batch(sample_transfer_df)

        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(item, dict) for item in result)

    def test_contains_required_keys(self, sample_transfer_df):
        """각 딕셔너리에 필수 키가 포함되는지 확인."""
        from src.data import graph_etl

        result = graph_etl._df_to_transfer_batch(sample_transfer_df)
        required_keys = {
            "source", "target", "거래일자", "거래시간대",
            "자금구분", "매체구분", "거래금액", "이상거래여부", "이상거래유형"
        }

        for item in result:
            assert required_keys.issubset(set(item.keys()))

    def test_converts_values_to_python_int(self, sample_transfer_df):
        """모든 값이 Python int 타입으로 변환되는지 확인."""
        from src.data import graph_etl

        result = graph_etl._df_to_transfer_batch(sample_transfer_df)

        for item in result:
            for key, value in item.items():
                assert isinstance(value, int), f"{key}의 값이 int가 아님: {type(value)}"

    def test_handles_nan_in_fraud_type(self):
        """이상거래유형이 NaN일 때 0으로 대체하는지 확인."""
        import numpy as np
        from src.data import graph_etl

        df_with_nan = pd.DataFrame({
            "source": [1001],
            "target": [2001],
            "거래일자": [20240101],
            "거래시간대": [9],
            "자금구분": [1],
            "매체구분": [1],
            "거래금액": [100000],
            "이상거래여부": [0],
            "이상거래유형": [float("nan")],
        })

        result = graph_etl._df_to_transfer_batch(df_with_nan)

        assert result[0]["이상거래유형"] == 0

    def test_correct_values_mapping(self, sample_transfer_df):
        """DataFrame 값이 올바르게 딕셔너리에 매핑되는지 확인."""
        from src.data import graph_etl

        result = graph_etl._df_to_transfer_batch(sample_transfer_df)

        assert result[0]["source"] == 1001
        assert result[0]["target"] == 2001
        assert result[0]["거래일자"] == 20240101
        assert result[0]["거래금액"] == 100000
        assert result[0]["이상거래여부"] == 0

        assert result[1]["source"] == 1002
        assert result[1]["이상거래여부"] == 1
        assert result[1]["이상거래유형"] == 3

    def test_empty_dataframe_returns_empty_list(self):
        """빈 DataFrame에 대해 빈 리스트를 반환하는지 확인."""
        from src.data import graph_etl

        result = graph_etl._df_to_transfer_batch(pd.DataFrame())

        assert result == []


# ---------------------------------------------------------------------------
# clear_graph()
# ---------------------------------------------------------------------------

class TestClearGraph:
    """clear_graph() 함수 테스트."""

    def test_does_nothing_when_memgraph_unavailable(self):
        """Memgraph 미실행 시 아무 작업도 하지 않는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.is_available", return_value=False):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                graph_etl.clear_graph()

        mock_execute.assert_not_called()

    def test_executes_detach_delete_when_available(self):
        """Memgraph 실행 중일 때 DETACH DELETE Cypher를 호출하는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.is_available", return_value=True):
            with patch("src.data.graph_etl.graph_db.execute") as mock_execute:
                graph_etl.clear_graph()

        mock_execute.assert_called_once()
        cypher_arg = mock_execute.call_args[0][0]
        assert "DETACH DELETE" in cypher_arg

    def test_returns_none(self):
        """clear_graph()가 None을 반환하는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.is_available", return_value=False):
            result = graph_etl.clear_graph()

        assert result is None


# ---------------------------------------------------------------------------
# get_graph_stats()
# ---------------------------------------------------------------------------

class TestGetGraphStats:
    """get_graph_stats() 함수 테스트."""

    def test_returns_zeros_when_memgraph_unavailable(self):
        """Memgraph 미실행 시 모든 값이 0인 딕셔너리를 반환하는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.is_available", return_value=False):
            result = graph_etl.get_graph_stats()

        assert result == {
            "accounts": 0,
            "companies": 0,
            "transfers": 0,
            "belongs_to": 0,
        }

    def test_returns_zeros_when_execute_returns_empty(self):
        """execute()가 빈 리스트를 반환할 때 모든 값이 0인지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.is_available", return_value=True):
            with patch("src.data.graph_etl.graph_db.execute", return_value=[]):
                result = graph_etl.get_graph_stats()

        assert result == {
            "accounts": 0,
            "companies": 0,
            "transfers": 0,
            "belongs_to": 0,
        }

    def test_returns_correct_counts_from_records(self):
        """execute() 결과로부터 올바른 카운트를 반환하는지 확인."""
        from src.data import graph_etl

        mock_records = [{
            "accounts": 5000,
            "companies": 20,
            "transfers": 100000,
            "belongs_to": 5000,
        }]

        with patch("src.data.graph_etl.graph_db.is_available", return_value=True):
            with patch("src.data.graph_etl.graph_db.execute", return_value=mock_records):
                result = graph_etl.get_graph_stats()

        assert result["accounts"] == 5000
        assert result["companies"] == 20
        assert result["transfers"] == 100000
        assert result["belongs_to"] == 5000

    def test_returns_dict_with_required_keys(self):
        """반환 딕셔너리에 필수 키가 모두 포함되는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.is_available", return_value=False):
            result = graph_etl.get_graph_stats()

        assert set(result.keys()) == {"accounts", "companies", "transfers", "belongs_to"}

    def test_uses_fallback_zero_for_missing_keys(self):
        """레코드에 일부 키가 없을 때 기본값 0을 사용하는지 확인."""
        from src.data import graph_etl

        # 일부 키만 포함된 레코드
        mock_records = [{"accounts": 100}]

        with patch("src.data.graph_etl.graph_db.is_available", return_value=True):
            with patch("src.data.graph_etl.graph_db.execute", return_value=mock_records):
                result = graph_etl.get_graph_stats()

        assert result["accounts"] == 100
        assert result["companies"] == 0
        assert result["transfers"] == 0
        assert result["belongs_to"] == 0

    def test_calls_graph_db_execute_with_count_query(self):
        """카운트 조회용 Cypher가 execute()에 전달되는지 확인."""
        from src.data import graph_etl

        with patch("src.data.graph_etl.graph_db.is_available", return_value=True):
            with patch("src.data.graph_etl.graph_db.execute", return_value=[]) as mock_execute:
                graph_etl.get_graph_stats()

        mock_execute.assert_called_once()
        cypher = mock_execute.call_args[0][0]
        # Account, Company, TRANSFER, BELONGS_TO 카운트 쿼리인지 확인
        assert "Account" in cypher
        assert "Company" in cypher
        assert "TRANSFER" in cypher
        assert "BELONGS_TO" in cypher
