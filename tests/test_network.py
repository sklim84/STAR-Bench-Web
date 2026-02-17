"""기능2: 네트워크 분석 (src/features/network.py) 단위 테스트.

검증 항목:
- 쿼리 함수가 올바른 DataFrame을 반환하는지
- 반환 컬럼 이름과 수가 기대값과 일치하는지
- 데이터 값의 범위와 정합성이 올바른지
- NetworkX 그래프 빌더가 올바른 그래프를 생성하는지
- 파라미터(limit, account_id, hops)가 올바르게 적용되는지
- 중심성 지표, 커뮤니티 탐지, 이상거래 흐름 매트릭스, 확장 통계 함수
"""

import pandas as pd
import networkx as nx
import pytest
from unittest.mock import patch

from src.features.network import (
    get_bank_network,
    get_fraud_account_network,
    get_account_ego_network,
    get_fraud_accounts,
    get_bank_network_stats,
    build_bank_graph,
    build_account_graph,
    compute_centrality_metrics,
    detect_communities,
    get_fraud_flow_matrix,
    get_extended_network_stats,
)


# ──────────────────────────────────────────────
# get_bank_network
# ──────────────────────────────────────────────
class TestGetBankNetwork:
    """get_bank_network() 단위 테스트."""

    @pytest.fixture(scope="class")
    def bank_df(self):
        return get_bank_network()

    def test_returns_dataframe(self, bank_df):
        assert isinstance(bank_df, pd.DataFrame)

    def test_expected_columns(self, bank_df):
        expected = {"source", "target", "총거래", "이상거래", "총금액"}
        assert expected.issubset(set(bank_df.columns))

    def test_not_empty(self, bank_df):
        """금융회사 간 연결이 1건 이상 존재해야 한다."""
        assert len(bank_df) > 0

    def test_total_transactions_positive(self, bank_df):
        """모든 연결의 총거래 건수가 1 이상이어야 한다."""
        assert (bank_df["총거래"] >= 1).all()

    def test_fraud_count_non_negative(self, bank_df):
        """이상거래 건수가 0 이상이어야 한다."""
        assert (bank_df["이상거래"] >= 0).all()

    def test_amount_positive(self, bank_df):
        """총금액이 양수이어야 한다."""
        assert (bank_df["총금액"] > 0).all()

    def test_sorted_by_total_desc(self, bank_df):
        """총거래 기준 내림차순 정렬이어야 한다."""
        totals = bank_df["총거래"].tolist()
        assert totals == sorted(totals, reverse=True)

    def test_source_target_are_integers(self, bank_df):
        """source, target이 정수형(금융회사 번호)이어야 한다."""
        assert bank_df["source"].dtype.kind in ("i", "u")
        assert bank_df["target"].dtype.kind in ("i", "u")

    def test_fraud_not_exceeds_total(self, bank_df):
        """이상거래 건수가 총거래 건수를 초과하지 않아야 한다."""
        assert (bank_df["이상거래"] <= bank_df["총거래"]).all()


# ──────────────────────────────────────────────
# get_fraud_account_network
# ──────────────────────────────────────────────
class TestGetFraudAccountNetwork:
    """get_fraud_account_network() 단위 테스트."""

    @pytest.fixture(scope="class")
    def fraud_df(self):
        return get_fraud_account_network(limit=100)

    def test_returns_dataframe(self, fraud_df):
        assert isinstance(fraud_df, pd.DataFrame)

    def test_expected_columns(self, fraud_df):
        expected = {"source", "target", "거래횟수", "총금액", "이상거래유형", "이상거래설명"}
        assert expected.issubset(set(fraud_df.columns))

    def test_limit_applied(self, fraud_df):
        """limit=100이므로 100건 이하여야 한다."""
        assert len(fraud_df) <= 100

    def test_not_empty(self, fraud_df):
        """이상거래 계좌 네트워크가 1건 이상 존재해야 한다."""
        assert len(fraud_df) > 0

    def test_transaction_count_positive(self, fraud_df):
        """거래횟수가 1 이상이어야 한다."""
        assert (fraud_df["거래횟수"] >= 1).all()

    def test_amount_positive(self, fraud_df):
        """총금액이 양수이어야 한다."""
        assert (fraud_df["총금액"] > 0).all()

    def test_sorted_by_count_desc(self, fraud_df):
        """거래횟수 기준 내림차순 정렬이어야 한다."""
        counts = fraud_df["거래횟수"].tolist()
        assert counts == sorted(counts, reverse=True)

    def test_default_limit_500(self):
        """기본 limit=500이 올바르게 적용되는지 확인."""
        df = get_fraud_account_network()
        assert len(df) <= 500

    def test_small_limit_reduces_rows(self):
        """작은 limit 값이 행 수를 줄이는지 확인."""
        df_10 = get_fraud_account_network(limit=10)
        df_50 = get_fraud_account_network(limit=50)
        assert len(df_10) <= 10
        assert len(df_50) <= 50
        assert len(df_10) <= len(df_50)


# ──────────────────────────────────────────────
# get_account_ego_network
# ──────────────────────────────────────────────
class TestGetAccountEgoNetwork:
    """get_account_ego_network() 단위 테스트."""

    @pytest.fixture(scope="class")
    def sample_account(self):
        """이상거래에 관련된 첫 번째 출금 계좌 ID를 반환한다."""
        from src.features.network import get_fraud_accounts
        accounts = get_fraud_accounts()
        return int(accounts["계좌"].iloc[0])

    def test_1hop_returns_dataframe(self, sample_account):
        df = get_account_ego_network(sample_account, hops=1)
        assert isinstance(df, pd.DataFrame)

    def test_1hop_expected_columns(self, sample_account):
        df = get_account_ego_network(sample_account, hops=1)
        expected = {"source", "target", "거래횟수", "총금액", "이상거래여부"}
        assert expected.issubset(set(df.columns))

    def test_1hop_contains_account(self, sample_account):
        """1-hop 네트워크에 조회 계좌가 source 또는 target으로 포함되어야 한다."""
        df = get_account_ego_network(sample_account, hops=1)
        if len(df) > 0:
            in_source = (df["source"] == sample_account).any()
            in_target = (df["target"] == sample_account).any()
            assert in_source or in_target

    def test_2hop_returns_dataframe(self, sample_account):
        df = get_account_ego_network(sample_account, hops=2)
        assert isinstance(df, pd.DataFrame)

    def test_2hop_not_smaller_than_1hop(self, sample_account):
        """2-hop은 1-hop보다 같거나 많은 연결을 포함해야 한다."""
        df_1 = get_account_ego_network(sample_account, hops=1)
        df_2 = get_account_ego_network(sample_account, hops=2)
        assert len(df_2) >= len(df_1)

    def test_fraud_flag_binary(self, sample_account):
        """이상거래여부가 0 또는 1만 포함해야 한다."""
        df = get_account_ego_network(sample_account, hops=1)
        if len(df) > 0:
            unique_vals = set(df["이상거래여부"].unique())
            assert unique_vals.issubset({0, 1})


# ──────────────────────────────────────────────
# get_fraud_accounts
# ──────────────────────────────────────────────
class TestGetFraudAccounts:
    """get_fraud_accounts() 단위 테스트."""

    @pytest.fixture(scope="class")
    def fraud_accounts(self):
        return get_fraud_accounts()

    def test_returns_dataframe(self, fraud_accounts):
        assert isinstance(fraud_accounts, pd.DataFrame)

    def test_expected_columns(self, fraud_accounts):
        assert "계좌" in fraud_accounts.columns

    def test_not_empty(self, fraud_accounts):
        """이상거래 계좌가 1건 이상 존재해야 한다."""
        assert len(fraud_accounts) > 0

    def test_sorted_ascending(self, fraud_accounts):
        """계좌 기준 오름차순 정렬이어야 한다."""
        accounts = fraud_accounts["계좌"].tolist()
        assert accounts == sorted(accounts)

    def test_no_duplicates(self, fraud_accounts):
        """중복 계좌가 없어야 한다 (DISTINCT 쿼리)."""
        assert fraud_accounts["계좌"].nunique() == len(fraud_accounts)

    def test_account_values_positive(self, fraud_accounts):
        """계좌 번호가 양수이어야 한다."""
        assert (fraud_accounts["계좌"] > 0).all()


# ──────────────────────────────────────────────
# get_bank_network_stats
# ──────────────────────────────────────────────
class TestGetBankNetworkStats:
    """get_bank_network_stats() 단위 테스트."""

    @pytest.fixture(scope="class")
    def stats(self):
        return get_bank_network_stats()

    def test_returns_dataframe(self, stats):
        assert isinstance(stats, pd.DataFrame)

    def test_single_row(self, stats):
        """집계 결과는 정확히 1행이어야 한다."""
        assert len(stats) == 1

    def test_expected_columns(self, stats):
        expected = {"출금금융회사수", "입금금융회사수", "연결수"}
        assert expected.issubset(set(stats.columns))

    def test_counts_positive(self, stats):
        """모든 수치가 양수이어야 한다."""
        row = stats.iloc[0]
        assert int(row["출금금융회사수"]) > 0
        assert int(row["입금금융회사수"]) > 0
        assert int(row["연결수"]) > 0

    def test_connection_count_reasonable(self, stats):
        """연결 수가 금융회사 수보다 많아야 한다 (다대다 관계)."""
        row = stats.iloc[0]
        max_companies = max(int(row["출금금융회사수"]), int(row["입금금융회사수"]))
        assert int(row["연결수"]) >= max_companies


# ──────────────────────────────────────────────
# build_bank_graph
# ──────────────────────────────────────────────
class TestBuildBankGraph:
    """build_bank_graph() 단위 테스트."""

    @pytest.fixture(scope="class")
    def bank_graph(self):
        df = get_bank_network()
        return build_bank_graph(df), df

    def test_returns_digraph(self, bank_graph):
        G, _ = bank_graph
        assert isinstance(G, nx.DiGraph)

    def test_nodes_match_unique_accounts(self, bank_graph):
        """노드 수가 unique source + target 합집합과 일치해야 한다."""
        G, df = bank_graph
        unique_nodes = set(str(int(v)) for v in df["source"]) | set(str(int(v)) for v in df["target"])
        assert len(G.nodes()) == len(unique_nodes)

    def test_edges_match_df_rows(self, bank_graph):
        """엣지 수가 DataFrame 행 수와 일치해야 한다."""
        G, df = bank_graph
        assert len(G.edges()) == len(df)

    def test_edge_attributes_exist(self, bank_graph):
        """엣지에 weight, fraud, amount 속성이 있어야 한다."""
        G, _ = bank_graph
        for u, v, data in list(G.edges(data=True))[:5]:  # 처음 5개만 검사
            assert "weight" in data
            assert "fraud" in data
            assert "amount" in data

    def test_weight_is_int(self, bank_graph):
        """weight(총거래) 속성이 정수형이어야 한다."""
        G, _ = bank_graph
        for _, _, data in list(G.edges(data=True))[:5]:
            assert isinstance(data["weight"], int)

    def test_fraud_non_negative(self, bank_graph):
        """fraud 속성이 0 이상이어야 한다."""
        G, _ = bank_graph
        for _, _, data in list(G.edges(data=True))[:10]:
            assert data["fraud"] >= 0

    def test_empty_df_returns_empty_graph(self):
        """빈 DataFrame 입력 시 노드와 엣지가 없는 그래프를 반환해야 한다."""
        empty_df = pd.DataFrame(columns=["source", "target", "총거래", "이상거래", "총금액"])
        G = build_bank_graph(empty_df)
        assert isinstance(G, nx.DiGraph)
        assert len(G.nodes()) == 0
        assert len(G.edges()) == 0


# ──────────────────────────────────────────────
# build_account_graph
# ──────────────────────────────────────────────
class TestBuildAccountGraph:
    """build_account_graph() 단위 테스트."""

    @pytest.fixture(scope="class")
    def account_graph(self):
        df = get_fraud_account_network(limit=100)
        return build_account_graph(df), df

    def test_returns_digraph(self, account_graph):
        G, _ = account_graph
        assert isinstance(G, nx.DiGraph)

    def test_nodes_match_unique_accounts(self, account_graph):
        """노드가 source + target 합집합과 일치해야 한다."""
        G, df = account_graph
        unique_nodes = set(str(int(v)) for v in df["source"]) | set(str(int(v)) for v in df["target"])
        assert len(G.nodes()) == len(unique_nodes)

    def test_edges_match_df_rows(self, account_graph):
        """엣지 수가 DataFrame 행 수와 일치해야 한다."""
        G, df = account_graph
        assert len(G.edges()) == len(df)

    def test_edge_attributes_exist(self, account_graph):
        """엣지에 weight, amount 속성이 있어야 한다."""
        G, _ = account_graph
        for u, v, data in list(G.edges(data=True))[:5]:
            assert "weight" in data
            assert "amount" in data

    def test_weight_positive(self, account_graph):
        """weight(거래횟수) 속성이 양수이어야 한다."""
        G, _ = account_graph
        for _, _, data in list(G.edges(data=True))[:10]:
            assert data["weight"] >= 1

    def test_empty_df_returns_empty_graph(self):
        """빈 DataFrame 입력 시 노드와 엣지가 없는 그래프를 반환해야 한다."""
        empty_df = pd.DataFrame(columns=["source", "target", "거래횟수", "총금액"])
        G = build_account_graph(empty_df)
        assert isinstance(G, nx.DiGraph)
        assert len(G.nodes()) == 0
        assert len(G.edges()) == 0


# ──────────────────────────────────────────────
# compute_centrality_metrics
# ──────────────────────────────────────────────
class TestComputeCentralityMetrics:
    """compute_centrality_metrics() 단위 테스트."""

    @pytest.fixture(scope="class")
    def centrality_result(self):
        df = get_bank_network()
        G = build_bank_graph(df)
        return compute_centrality_metrics(G), G

    def test_returns_dataframe(self, centrality_result):
        metrics_df, _ = centrality_result
        assert isinstance(metrics_df, pd.DataFrame)

    def test_expected_columns(self, centrality_result):
        metrics_df, _ = centrality_result
        expected = {"노드", "degree", "betweenness", "closeness", "eigenvector"}
        assert expected.issubset(set(metrics_df.columns))

    def test_row_count_matches_nodes(self, centrality_result):
        """행 수가 그래프 노드 수와 일치해야 한다."""
        metrics_df, G = centrality_result
        assert len(metrics_df) == len(G.nodes())

    def test_degree_non_negative(self, centrality_result):
        """degree가 0 이상이어야 한다."""
        metrics_df, _ = centrality_result
        assert (metrics_df["degree"] >= 0).all()

    def test_betweenness_range(self, centrality_result):
        """betweenness 값이 0~1 범위이어야 한다."""
        metrics_df, _ = centrality_result
        assert (metrics_df["betweenness"] >= 0).all()
        assert (metrics_df["betweenness"] <= 1).all()

    def test_closeness_range(self, centrality_result):
        """closeness 값이 0~1 범위이어야 한다."""
        metrics_df, _ = centrality_result
        assert (metrics_df["closeness"] >= 0).all()
        assert (metrics_df["closeness"] <= 1).all()

    def test_eigenvector_non_negative(self, centrality_result):
        """eigenvector 값이 0 이상이어야 한다."""
        metrics_df, _ = centrality_result
        assert (metrics_df["eigenvector"] >= 0).all()

    def test_sorted_by_degree_desc(self, centrality_result):
        """degree 기준 내림차순 정렬이어야 한다."""
        metrics_df, _ = centrality_result
        degrees = metrics_df["degree"].tolist()
        assert degrees == sorted(degrees, reverse=True)

    def test_empty_graph(self):
        """빈 그래프 입력 시 빈 DataFrame을 반환해야 한다."""
        G = nx.DiGraph()
        result = compute_centrality_metrics(G)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
        expected_cols = {"노드", "degree", "betweenness", "closeness", "eigenvector"}
        assert expected_cols.issubset(set(result.columns))


# ──────────────────────────────────────────────
# detect_communities
# ──────────────────────────────────────────────
class TestDetectCommunities:
    """detect_communities() 단위 테스트."""

    @pytest.fixture(scope="class")
    def community_result(self):
        df = get_fraud_account_network(limit=100)
        G = build_account_graph(df)
        return detect_communities(G), G

    def test_returns_dataframe(self, community_result):
        comm_df, _ = community_result
        assert isinstance(comm_df, pd.DataFrame)

    def test_expected_columns(self, community_result):
        comm_df, _ = community_result
        expected = {"노드", "커뮤니티"}
        assert expected.issubset(set(comm_df.columns))

    def test_row_count_matches_nodes(self, community_result):
        """행 수가 그래프 노드 수와 일치해야 한다."""
        comm_df, G = community_result
        assert len(comm_df) == len(G.nodes())

    def test_community_labels_non_negative(self, community_result):
        """커뮤니티 레이블이 0 이상의 정수이어야 한다."""
        comm_df, _ = community_result
        assert (comm_df["커뮤니티"] >= 0).all()

    def test_at_least_one_community(self, community_result):
        """최소 1개의 커뮤니티가 존재해야 한다."""
        comm_df, _ = community_result
        assert comm_df["커뮤니티"].nunique() >= 1

    def test_all_nodes_assigned(self, community_result):
        """모든 노드에 커뮤니티가 할당되어야 한다."""
        comm_df, G = community_result
        assert set(comm_df["노드"]) == set(G.nodes())

    def test_empty_graph(self):
        """빈 그래프 입력 시 빈 DataFrame을 반환해야 한다."""
        G = nx.DiGraph()
        result = detect_communities(G)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


# ──────────────────────────────────────────────
# get_fraud_flow_matrix
# ──────────────────────────────────────────────
class TestGetFraudFlowMatrix:
    """get_fraud_flow_matrix() 단위 테스트."""

    @pytest.fixture(scope="class")
    def flow_df(self):
        return get_fraud_flow_matrix()

    def test_returns_dataframe(self, flow_df):
        assert isinstance(flow_df, pd.DataFrame)

    def test_expected_columns(self, flow_df):
        expected = {"source", "target", "이상거래건수", "이상거래금액"}
        assert expected.issubset(set(flow_df.columns))

    def test_not_empty(self, flow_df):
        """이상거래 흐름이 1건 이상 존재해야 한다."""
        assert len(flow_df) > 0

    def test_fraud_count_positive(self, flow_df):
        """이상거래건수가 1 이상이어야 한다 (HAVING 조건)."""
        assert (flow_df["이상거래건수"] >= 1).all()

    def test_fraud_amount_positive(self, flow_df):
        """이상거래금액이 양수이어야 한다."""
        assert (flow_df["이상거래금액"] > 0).all()

    def test_sorted_by_count_desc(self, flow_df):
        """이상거래건수 기준 내림차순 정렬이어야 한다."""
        counts = flow_df["이상거래건수"].tolist()
        assert counts == sorted(counts, reverse=True)

    def test_source_target_are_integers(self, flow_df):
        """source, target이 정수형이어야 한다."""
        assert flow_df["source"].dtype.kind in ("i", "u")
        assert flow_df["target"].dtype.kind in ("i", "u")


# ──────────────────────────────────────────────
# get_extended_network_stats
# ──────────────────────────────────────────────
class TestGetExtendedNetworkStats:
    """get_extended_network_stats() 단위 테스트."""

    @pytest.fixture(scope="class")
    def ext_stats(self):
        df = get_bank_network()
        G = build_bank_graph(df)
        return get_extended_network_stats(G)

    def test_returns_dict(self, ext_stats):
        assert isinstance(ext_stats, dict)

    def test_expected_keys(self, ext_stats):
        expected_keys = {"노드수", "엣지수", "밀도", "평균클러스터링계수", "허브노드", "허브연결수"}
        assert expected_keys.issubset(set(ext_stats.keys()))

    def test_node_count_positive(self, ext_stats):
        assert ext_stats["노드수"] > 0

    def test_edge_count_positive(self, ext_stats):
        assert ext_stats["엣지수"] > 0

    def test_density_range(self, ext_stats):
        """밀도가 0~1 범위이어야 한다."""
        assert 0 <= ext_stats["밀도"] <= 1

    def test_clustering_range(self, ext_stats):
        """평균 클러스터링 계수가 0~1 범위이어야 한다."""
        assert 0 <= ext_stats["평균클러스터링계수"] <= 1

    def test_hub_degree_positive(self, ext_stats):
        """허브 노드의 연결 수가 1 이상이어야 한다."""
        assert ext_stats["허브연결수"] >= 1

    def test_empty_graph(self):
        """빈 그래프 입력 시 기본 값을 반환해야 한다."""
        G = nx.DiGraph()
        result = get_extended_network_stats(G)
        assert result["노드수"] == 0
        assert result["엣지수"] == 0
        assert result["밀도"] == 0.0
        assert result["허브노드"] == "-"
