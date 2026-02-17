"""기능2: 네트워크(그래프) 분석 쿼리 및 그래프 생성 모듈."""

import networkx as nx
import pandas as pd
from src.data.db import query


def get_bank_network():
    """금융회사 간 거래 네트워크 데이터를 반환한다."""
    return query("""
        SELECT
            출금금융회사일련번호 as source,
            입금금융회사일련번호 as target,
            count(*) as 총거래,
            sum(이상거래여부) as 이상거래,
            sum(거래금액) as 총금액
        FROM hofinet
        GROUP BY source, target
        ORDER BY 총거래 DESC
    """)


def get_fraud_account_network(limit=500):
    """이상거래 관련 계좌 간 네트워크 데이터를 반환한다."""
    # limit은 외부 입력이므로 int 형변환으로 안전하게 처리 (DuckDB는 LIMIT 파라미터 바인딩 미지원)
    limit = int(limit)
    return query(f"""
        SELECT
            출금계좌일련번호 as source,
            입금계좌일련번호 as target,
            count(*) as 거래횟수,
            sum(거래금액) as 총금액,
            max(이상거래유형) as 이상거래유형,
            max(이상거래설명) as 이상거래설명
        FROM hofinet
        WHERE 이상거래여부 = 1
        GROUP BY source, target
        ORDER BY 거래횟수 DESC
        LIMIT {limit}
    """)


def get_account_ego_network(account_id, hops=1):
    """특정 계좌의 ego 네트워크(n-hop 이웃)를 반환한다."""
    # account_id는 int64 계좌 번호이므로 int 형변환으로 SQL 인젝션 방지
    account_id = int(account_id)
    if hops == 1:
        return query(
            """
            SELECT
                출금계좌일련번호 as source,
                입금계좌일련번호 as target,
                count(*) as 거래횟수,
                sum(거래금액) as 총금액,
                max(이상거래여부) as 이상거래여부
            FROM hofinet
            WHERE 출금계좌일련번호 = ?
               OR 입금계좌일련번호 = ?
            GROUP BY source, target
            """,
            [account_id, account_id],
        )
    # 2-hop: 1-hop 이웃의 거래까지 포함
    # DuckDB CTE에서는 파라미터가 여러 번 참조되므로 int 변수를 f-string으로 안전하게 삽입
    return query(f"""
        WITH hop1 AS (
            SELECT DISTINCT
                CASE WHEN 출금계좌일련번호 = {account_id}
                     THEN 입금계좌일련번호 ELSE 출금계좌일련번호 END as neighbor
            FROM hofinet
            WHERE 출금계좌일련번호 = {account_id}
               OR 입금계좌일련번호 = {account_id}
        )
        SELECT
            출금계좌일련번호 as source,
            입금계좌일련번호 as target,
            count(*) as 거래횟수,
            sum(거래금액) as 총금액,
            max(이상거래여부) as 이상거래여부
        FROM hofinet
        WHERE 출금계좌일련번호 = {account_id}
           OR 입금계좌일련번호 = {account_id}
           OR 출금계좌일련번호 IN (SELECT neighbor FROM hop1)
           OR 입금계좌일련번호 IN (SELECT neighbor FROM hop1)
        GROUP BY source, target
    """)


def get_fraud_accounts():
    """이상거래에 관련된 출금 계좌 목록을 반환한다."""
    return query("""
        SELECT DISTINCT 출금계좌일련번호 as 계좌
        FROM hofinet
        WHERE 이상거래여부 = 1
        ORDER BY 계좌
    """)


def get_bank_network_stats():
    """금융회사 네트워크 요약 통계를 반환한다."""
    return query("""
        SELECT
            count(DISTINCT 출금금융회사일련번호) as 출금금융회사수,
            count(DISTINCT 입금금융회사일련번호) as 입금금융회사수,
            count(DISTINCT (CAST(출금금융회사일련번호 AS INT) * 1000 + CAST(입금금융회사일련번호 AS INT))) as 연결수
        FROM hofinet
    """)


def build_bank_graph(df):
    """DataFrame으로부터 금융회사 간 네트워크 그래프를 생성한다."""
    G = nx.DiGraph()
    for _, row in df.iterrows():
        G.add_edge(
            str(int(row["source"])),
            str(int(row["target"])),
            weight=int(row["총거래"]),
            fraud=int(row["이상거래"]),
            amount=float(row["총금액"]),
        )
    return G


def build_account_graph(df):
    """DataFrame으로부터 계좌 간 네트워크 그래프를 생성한다."""
    G = nx.DiGraph()
    for _, row in df.iterrows():
        G.add_edge(
            str(int(row["source"])),
            str(int(row["target"])),
            weight=int(row["거래횟수"]),
            amount=float(row["총금액"]),
        )
    return G


# ------------------------------------------------------------------
# 강화 기능: 중심성 지표 분석
# ------------------------------------------------------------------

def compute_centrality_metrics(G):
    """네트워크의 주요 중심성 지표를 계산하여 DataFrame으로 반환한다.

    Parameters
    ----------
    G : nx.DiGraph
        분석 대상 방향 그래프

    Returns
    -------
    pd.DataFrame
        컬럼: 노드, degree, betweenness, closeness, eigenvector
    """
    if len(G.nodes()) == 0:
        return pd.DataFrame(columns=["노드", "degree", "betweenness", "closeness", "eigenvector"])

    degree = dict(G.degree())
    betweenness = nx.betweenness_centrality(G, weight="weight")
    closeness = nx.closeness_centrality(G)

    # eigenvector centrality는 수렴하지 않을 수 있으므로 예외 처리
    try:
        eigenvector = nx.eigenvector_centrality(G, max_iter=300, weight="weight")
    except nx.PowerIterationFailedConvergence:
        eigenvector = {n: 0.0 for n in G.nodes()}

    nodes = list(G.nodes())
    df = pd.DataFrame({
        "노드": nodes,
        "degree": [degree[n] for n in nodes],
        "betweenness": [round(betweenness[n], 6) for n in nodes],
        "closeness": [round(closeness[n], 6) for n in nodes],
        "eigenvector": [round(eigenvector[n], 6) for n in nodes],
    })
    return df.sort_values("degree", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------
# 강화 기능: 커뮤니티 탐지
# ------------------------------------------------------------------

def detect_communities(G):
    """Greedy modularity 기반 커뮤니티 탐지를 수행한다.

    DiGraph를 undirected로 변환한 뒤 greedy_modularity_communities를 적용하고,
    각 노드에 커뮤니티 레이블을 부여한 DataFrame을 반환한다.

    Parameters
    ----------
    G : nx.DiGraph
        분석 대상 방향 그래프

    Returns
    -------
    pd.DataFrame
        컬럼: 노드, 커뮤니티
    """
    if len(G.nodes()) == 0:
        return pd.DataFrame(columns=["노드", "커뮤니티"])

    G_undirected = G.to_undirected()
    communities = nx.community.greedy_modularity_communities(G_undirected, weight="weight")

    node_community = {}
    for idx, community in enumerate(communities):
        for node in community:
            node_community[node] = idx

    df = pd.DataFrame({
        "노드": list(node_community.keys()),
        "커뮤니티": list(node_community.values()),
    })
    return df.sort_values("커뮤니티").reset_index(drop=True)


# ------------------------------------------------------------------
# 강화 기능: 금융회사 간 이상거래 흐름 매트릭스
# ------------------------------------------------------------------

def get_fraud_flow_matrix():
    """금융회사 간 이상거래 흐름 매트릭스 데이터를 반환한다.

    Returns
    -------
    pd.DataFrame
        컬럼: source, target, 이상거래건수, 이상거래금액
    """
    return query("""
        SELECT
            출금금융회사일련번호 as source,
            입금금융회사일련번호 as target,
            sum(이상거래여부) as 이상거래건수,
            sum(거래금액) as 이상거래금액
        FROM hofinet
        WHERE 이상거래여부 = 1
        GROUP BY source, target
        HAVING 이상거래건수 > 0
        ORDER BY 이상거래건수 DESC
    """)


# ------------------------------------------------------------------
# 강화 기능: 네트워크 통계 확장
# ------------------------------------------------------------------

def get_extended_network_stats(G):
    """네트워크의 확장 통계를 계산하여 딕셔너리로 반환한다.

    Parameters
    ----------
    G : nx.DiGraph
        분석 대상 방향 그래프

    Returns
    -------
    dict
        밀도, 평균 클러스터링 계수, 허브 노드 등의 통계
    """
    if len(G.nodes()) == 0:
        return {
            "노드수": 0,
            "엣지수": 0,
            "밀도": 0.0,
            "평균클러스터링계수": 0.0,
            "허브노드": "-",
            "허브연결수": 0,
        }

    density = nx.density(G)

    # 클러스터링 계수는 undirected 변환 후 계산
    G_undirected = G.to_undirected()
    avg_clustering = nx.average_clustering(G_undirected, weight="weight")

    # 가장 연결이 많은 노드 (허브)
    degree_dict = dict(G.degree())
    hub_node = max(degree_dict, key=degree_dict.get)
    hub_degree = degree_dict[hub_node]

    return {
        "노드수": len(G.nodes()),
        "엣지수": len(G.edges()),
        "밀도": round(density, 4),
        "평균클러스터링계수": round(avg_clustering, 4),
        "허브노드": hub_node,
        "허브연결수": hub_degree,
    }
