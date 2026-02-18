"""src/data/graph_db.py 단위 테스트.

검증 항목:
- get_driver(): 싱글턴 패턴, Memgraph 미실행/미설치 시 None 반환
- is_available(): Memgraph 접속 가능 여부 확인
- execute(): Cypher 실행, 연결 불가 시 빈 리스트 반환
- execute_df(): Cypher 실행 후 DataFrame 반환, 연결 불가 시 빈 DataFrame
- close(): 드라이버 종료 및 _driver 초기화

테스트 전략:
- 실제 Memgraph 서버 없이 테스트
- neo4j GraphDatabase.driver, verify_connectivity, session을 모킹
- _NEO4J_AVAILABLE 플래그와 _driver 전역 변수를 monkeypatch로 제어
"""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class TestGetDriver:
    """get_driver() 함수 테스트."""

    def test_returns_none_when_neo4j_unavailable(self):
        """neo4j 드라이버 미설치 시 None을 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        with patch.object(graph_db_module, "_NEO4J_AVAILABLE", False):
            with patch.object(graph_db_module, "_driver", None):
                result = graph_db_module.get_driver()
        assert result is None

    def test_returns_none_when_memgraph_unreachable(self):
        """Memgraph 서버에 접속 불가 시 None을 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_driver = MagicMock()
        from neo4j.exceptions import ServiceUnavailable
        mock_driver.verify_connectivity.side_effect = ServiceUnavailable("연결 실패")

        with patch.object(graph_db_module, "_NEO4J_AVAILABLE", True):
            with patch.object(graph_db_module, "_driver", None):
                with patch("src.data.graph_db.GraphDatabase") as mock_gdb:
                    mock_gdb.driver.return_value = mock_driver
                    result = graph_db_module.get_driver()

        assert result is None

    def test_returns_none_when_auth_error(self):
        """인증 오류 시 None을 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_driver = MagicMock()
        from neo4j.exceptions import AuthError
        mock_driver.verify_connectivity.side_effect = AuthError("인증 실패")

        with patch.object(graph_db_module, "_NEO4J_AVAILABLE", True):
            with patch.object(graph_db_module, "_driver", None):
                with patch("src.data.graph_db.GraphDatabase") as mock_gdb:
                    mock_gdb.driver.return_value = mock_driver
                    result = graph_db_module.get_driver()

        assert result is None

    def test_returns_none_when_os_error(self):
        """OSError 발생 시 None을 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_driver = MagicMock()
        mock_driver.verify_connectivity.side_effect = OSError("소켓 오류")

        with patch.object(graph_db_module, "_NEO4J_AVAILABLE", True):
            with patch.object(graph_db_module, "_driver", None):
                with patch("src.data.graph_db.GraphDatabase") as mock_gdb:
                    mock_gdb.driver.return_value = mock_driver
                    result = graph_db_module.get_driver()

        assert result is None

    def test_returns_none_when_unexpected_exception(self):
        """예기치 않은 예외 발생 시 None을 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_driver = MagicMock()
        mock_driver.verify_connectivity.side_effect = RuntimeError("알 수 없는 오류")

        with patch.object(graph_db_module, "_NEO4J_AVAILABLE", True):
            with patch.object(graph_db_module, "_driver", None):
                with patch("src.data.graph_db.GraphDatabase") as mock_gdb:
                    mock_gdb.driver.return_value = mock_driver
                    result = graph_db_module.get_driver()

        assert result is None

    def test_returns_existing_driver_singleton(self):
        """이미 드라이버가 존재하면 새로 생성하지 않고 기존 드라이버를 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        existing_driver = MagicMock()

        with patch.object(graph_db_module, "_driver", existing_driver):
            result = graph_db_module.get_driver()

        assert result is existing_driver

    def test_creates_driver_on_success(self):
        """접속 성공 시 드라이버를 생성하고 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_driver = MagicMock()
        mock_driver.verify_connectivity.return_value = None  # 성공

        with patch.object(graph_db_module, "_NEO4J_AVAILABLE", True):
            with patch.object(graph_db_module, "_driver", None):
                with patch("src.data.graph_db.GraphDatabase") as mock_gdb:
                    mock_gdb.driver.return_value = mock_driver
                    result = graph_db_module.get_driver()

        assert result is mock_driver

    def test_driver_set_to_none_after_connection_failure(self):
        """접속 실패 후 _driver가 None으로 설정되는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_driver = MagicMock()
        from neo4j.exceptions import ServiceUnavailable
        mock_driver.verify_connectivity.side_effect = ServiceUnavailable("실패")

        with patch.object(graph_db_module, "_NEO4J_AVAILABLE", True):
            with patch.object(graph_db_module, "_driver", None):
                with patch("src.data.graph_db.GraphDatabase") as mock_gdb:
                    mock_gdb.driver.return_value = mock_driver
                    graph_db_module.get_driver()

        # _driver 전역 변수가 None으로 복원되어야 함
        assert graph_db_module._driver is None


class TestIsAvailable:
    """is_available() 함수 테스트."""

    def test_returns_false_when_driver_is_none(self):
        """드라이버가 None일 때 False를 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        with patch.object(graph_db_module, "get_driver", return_value=None):
            result = graph_db_module.is_available()

        assert result is False

    def test_returns_true_when_ping_succeeds(self):
        """RETURN 1 쿼리 성공 시 True를 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: 1  # record["ping"] == 1
        mock_record.__contains__ = lambda self, key: True

        mock_result = MagicMock()
        mock_result.single.return_value = mock_record

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(graph_db_module, "get_driver", return_value=mock_driver):
            result = graph_db_module.is_available()

        assert result is True

    def test_returns_false_when_ping_returns_none(self):
        """RETURN 1 쿼리 결과가 None일 때 False를 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_result = MagicMock()
        mock_result.single.return_value = None

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(graph_db_module, "get_driver", return_value=mock_driver):
            result = graph_db_module.is_available()

        assert result is False

    def test_returns_false_when_session_raises_exception(self):
        """세션 실행 중 예외 발생 시 False를 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.side_effect = Exception("세션 오류")

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(graph_db_module, "get_driver", return_value=mock_driver):
            result = graph_db_module.is_available()

        assert result is False


class TestExecute:
    """execute() 함수 테스트."""

    def test_returns_empty_list_when_driver_none(self):
        """드라이버가 None일 때 빈 리스트를 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        with patch.object(graph_db_module, "get_driver", return_value=None):
            result = graph_db_module.execute("MATCH (n) RETURN n")

        assert result == []

    def test_returns_list_of_dicts_on_success(self):
        """쿼리 성공 시 레코드 목록을 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_record1 = MagicMock()
        mock_record1.data.return_value = {"id": 1, "name": "회사A"}
        mock_record2 = MagicMock()
        mock_record2.data.return_value = {"id": 2, "name": "회사B"}

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([mock_record1, mock_record2]))

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(graph_db_module, "get_driver", return_value=mock_driver):
            result = graph_db_module.execute("MATCH (c:Company) RETURN c.id AS id, c.name AS name")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "회사A"}
        assert result[1] == {"id": 2, "name": "회사B"}

    def test_passes_params_to_session_run(self):
        """파라미터가 session.run()에 전달되는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        cypher = "MATCH (a:Account {id: $id}) RETURN a"
        params = {"id": 1001}

        with patch.object(graph_db_module, "get_driver", return_value=mock_driver):
            graph_db_module.execute(cypher, params)

        mock_session.run.assert_called_once_with(cypher, parameters=params)

    def test_uses_empty_dict_when_params_none(self):
        """params=None 시 빈 딕셔너리로 호출하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        cypher = "MATCH (n) RETURN n"

        with patch.object(graph_db_module, "get_driver", return_value=mock_driver):
            graph_db_module.execute(cypher, None)

        mock_session.run.assert_called_once_with(cypher, parameters={})

    def test_returns_empty_list_on_exception(self):
        """쿼리 실행 중 예외 발생 시 빈 리스트를 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.side_effect = Exception("쿼리 실패")

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(graph_db_module, "get_driver", return_value=mock_driver):
            result = graph_db_module.execute("MATCH (n) RETURN n")

        assert result == []

    def test_returns_empty_list_when_no_records(self):
        """결과 레코드가 없을 때 빈 리스트를 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch.object(graph_db_module, "get_driver", return_value=mock_driver):
            result = graph_db_module.execute("MATCH (n:NonExistent) RETURN n")

        assert result == []


class TestExecuteDf:
    """execute_df() 함수 테스트."""

    def test_returns_empty_dataframe_when_driver_none(self):
        """드라이버 없을 때 빈 DataFrame을 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        with patch.object(graph_db_module, "get_driver", return_value=None):
            result = graph_db_module.execute_df("MATCH (n) RETURN n")

        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_returns_empty_dataframe_when_no_records(self):
        """레코드가 없을 때 빈 DataFrame을 반환하는지 확인."""
        import src.data.graph_db as graph_db_module

        with patch.object(graph_db_module, "execute", return_value=[]):
            result = graph_db_module.execute_df("MATCH (n:NonExistent) RETURN n")

        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_returns_dataframe_from_records(self):
        """레코드가 있을 때 DataFrame으로 변환하는지 확인."""
        import src.data.graph_db as graph_db_module

        records = [
            {"id": 1001, "company_id": 10},
            {"id": 1002, "company_id": 20},
            {"id": 1003, "company_id": 10},
        ]

        with patch.object(graph_db_module, "execute", return_value=records):
            result = graph_db_module.execute_df("MATCH (a:Account) RETURN a.id AS id, a.company_id AS company_id")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert list(result.columns) == ["id", "company_id"]
        assert result["id"].tolist() == [1001, 1002, 1003]

    def test_dataframe_column_types_preserved(self):
        """DataFrame의 컬럼 타입이 올바르게 보존되는지 확인."""
        import src.data.graph_db as graph_db_module

        records = [
            {"account_id": 1001, "amount": 500000, "is_fraud": True},
        ]

        with patch.object(graph_db_module, "execute", return_value=records):
            result = graph_db_module.execute_df("MATCH (a) RETURN a")

        assert result["account_id"].iloc[0] == 1001
        assert result["amount"].iloc[0] == 500000
        assert result["is_fraud"].iloc[0] == True  # noqa: E712 (numpy bool comparison)

    def test_passes_cypher_and_params_to_execute(self):
        """cypher와 params가 execute()에 올바르게 전달되는지 확인."""
        import src.data.graph_db as graph_db_module

        with patch.object(graph_db_module, "execute", return_value=[]) as mock_execute:
            cypher = "MATCH (a:Account {id: $id}) RETURN a"
            params = {"id": 999}
            graph_db_module.execute_df(cypher, params)

        mock_execute.assert_called_once_with(cypher, params)


class TestClose:
    """close() 함수 테스트."""

    def test_close_calls_driver_close(self):
        """드라이버가 존재할 때 driver.close()를 호출하는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_driver = MagicMock()

        with patch.object(graph_db_module, "_driver", mock_driver):
            graph_db_module.close()

        mock_driver.close.assert_called_once()

    def test_close_sets_driver_to_none(self):
        """close() 후 _driver가 None으로 설정되는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_driver = MagicMock()

        with patch.object(graph_db_module, "_driver", mock_driver):
            graph_db_module.close()

        assert graph_db_module._driver is None

    def test_close_does_nothing_when_driver_none(self):
        """드라이버가 None일 때 오류 없이 종료하는지 확인."""
        import src.data.graph_db as graph_db_module

        with patch.object(graph_db_module, "_driver", None):
            # 예외가 발생하지 않아야 함
            graph_db_module.close()

        assert graph_db_module._driver is None

    def test_close_handles_exception_gracefully(self):
        """driver.close() 중 예외 발생 시에도 _driver가 None으로 설정되는지 확인."""
        import src.data.graph_db as graph_db_module

        mock_driver = MagicMock()
        mock_driver.close.side_effect = Exception("종료 중 오류")

        with patch.object(graph_db_module, "_driver", mock_driver):
            # 예외가 외부로 전파되지 않아야 함
            graph_db_module.close()

        # finally 블록으로 인해 _driver는 None으로 설정되어야 함
        assert graph_db_module._driver is None
