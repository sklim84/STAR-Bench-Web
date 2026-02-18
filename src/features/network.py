"""기능2: 네트워크(그래프) 분석 쿼리 및 그래프 생성 모듈."""

import logging

import networkx as nx
import pandas as pd
from src.data.db import query
from src.data import graph_db

logger = logging.getLogger(__name__)


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


# ==================================================================
# Memgraph Cypher 기반 AML 패턴 탐지 함수
# ==================================================================
# Memgraph 미실행 시 graceful degradation: 빈 DataFrame/dict 반환 + 경고 로그
# TRANSFER 엣지 속성: 거래일자, 거래시간대, 자금구분, 매체구분, 거래금액,
#                     이상거래여부, 이상거래유형
# Account 노드 속성: id, company_id
# ------------------------------------------------------------------


def detect_ring_transactions(min_len=3, max_len=6, min_amount=0, limit=100):
    """순환거래(ring) 사이클을 탐지한다.

    자금세탁의 핵심 패턴인 A->B->C->...->A 순환 거래를 그래프 탐색으로 찾는다.
    이상거래로 표시된 관계만 탐색 대상으로 삼는다.

    Parameters
    ----------
    min_len : int
        순환 경로의 최소 길이 (기본 3)
    max_len : int
        순환 경로의 최대 길이 (기본 6)
    min_amount : int
        순환 내 총 거래금액 최소 필터 (기본 0)
    limit : int
        반환할 최대 결과 수 (기본 100)

    Returns
    -------
    pd.DataFrame
        컬럼: ring_accounts, ring_size, total_amount, dates
        Memgraph 미실행 시 빈 DataFrame
    """
    empty = pd.DataFrame(columns=["ring_accounts", "ring_size", "total_amount", "dates"])

    if not graph_db.is_available():
        logger.warning("Memgraph 미실행으로 순환거래 탐지 불가")
        return empty

    # Memgraph는 LIMIT에 파라미터 바인딩 불가 -> int() 변환 후 f-string 삽입
    min_len = int(min_len)
    max_len = int(max_len)
    min_amount = int(min_amount)
    limit = int(limit)

    cypher = f"""
        MATCH p=(a:Account)-[:TRANSFER*{min_len}..{max_len}]->(a)
        WHERE ALL(r IN relationships(p) WHERE r.이상거래여부 = 1)
        WITH [n IN nodes(p) | n.id] AS ring_accounts,
             [r IN relationships(p) | r.거래금액] AS amounts,
             [r IN relationships(p) | r.거래일자] AS dates,
             size(relationships(p)) AS ring_size,
             reduce(s = 0, r IN relationships(p) | s + r.거래금액) AS total_amount
        WHERE total_amount >= {min_amount}
        RETURN ring_accounts, ring_size, total_amount, dates
        ORDER BY total_amount DESC
        LIMIT {limit}
    """

    records = graph_db.execute(cypher)
    if not records:
        return empty

    rows = []
    for rec in records:
        rows.append({
            "ring_accounts": rec.get("ring_accounts", []),
            "ring_size": rec.get("ring_size", 0),
            "total_amount": rec.get("total_amount", 0),
            "dates": rec.get("dates", []),
        })
    return pd.DataFrame(rows)


def detect_layering_patterns(min_layers=3, limit=100):
    """다단계 레이어링 패턴을 탐지한다.

    출발 계좌에서 중개 계좌를 거쳐 도착 계좌에 이르는
    A->B->C->...->Z 형태의 다단계 자금 이동 패턴을 찾는다.
    이상거래로 표시된 관계만 탐색 대상으로 삼는다.

    Parameters
    ----------
    min_layers : int
        최소 레이어(중간 경유) 수 (기본 3)
    limit : int
        반환할 최대 결과 수 (기본 100)

    Returns
    -------
    pd.DataFrame
        컬럼: source_account, destination_account, path_accounts, layers, total_amount
        Memgraph 미실행 시 빈 DataFrame
    """
    empty = pd.DataFrame(columns=[
        "source_account", "destination_account", "path_accounts",
        "layers", "total_amount",
    ])

    if not graph_db.is_available():
        logger.warning("Memgraph 미실행으로 레이어링 패턴 탐지 불가")
        return empty

    min_layers = int(min_layers)
    limit = int(limit)

    cypher = f"""
        MATCH p=(src:Account)-[:TRANSFER*{min_layers}..]->(dst:Account)
        WHERE src <> dst
          AND ALL(r IN relationships(p) WHERE r.이상거래여부 = 1)
        WITH src, dst,
             [n IN nodes(p) | n.id] AS path_accounts,
             size(relationships(p)) AS layers,
             reduce(s = 0, r IN relationships(p) | s + r.거래금액) AS total_amount
        WHERE layers >= {min_layers}
        RETURN src.id AS source_account,
               dst.id AS destination_account,
               path_accounts,
               layers,
               total_amount
        ORDER BY layers DESC, total_amount DESC
        LIMIT {limit}
    """

    records = graph_db.execute(cypher)
    if not records:
        return empty

    rows = []
    for rec in records:
        rows.append({
            "source_account": rec.get("source_account"),
            "destination_account": rec.get("destination_account"),
            "path_accounts": rec.get("path_accounts", []),
            "layers": rec.get("layers", 0),
            "total_amount": rec.get("total_amount", 0),
        })
    return pd.DataFrame(rows)


def detect_funnel_accounts(min_inflow=10, max_outflow=3, limit=100):
    """대포통장(funnel) 패턴을 탐지한다.

    다수의 계좌로부터 입금을 받고(inflow) 소수의 계좌로 출금하는(outflow)
    대포통장 의심 계좌를 찾는다. funnel_ratio가 높을수록 의심도가 높다.

    Parameters
    ----------
    min_inflow : int
        최소 입금 계좌 수 (기본 10)
    max_outflow : int
        최대 출금 계좌 수 (기본 3)
    limit : int
        반환할 최대 결과 수 (기본 100)

    Returns
    -------
    pd.DataFrame
        컬럼: account_id, inflow_count, inflow_amount, outflow_count,
              outflow_amount, funnel_ratio
        Memgraph 미실행 시 빈 DataFrame
    """
    empty = pd.DataFrame(columns=[
        "account_id", "inflow_count", "inflow_amount",
        "outflow_count", "outflow_amount", "funnel_ratio",
    ])

    if not graph_db.is_available():
        logger.warning("Memgraph 미실행으로 대포통장 패턴 탐지 불가")
        return empty

    min_inflow = int(min_inflow)
    max_outflow = int(max_outflow)
    limit = int(limit)

    cypher = f"""
        MATCH (s:Account)-[r1:TRANSFER]->(funnel:Account)
        WITH funnel,
             count(DISTINCT s) AS inflow_count,
             sum(r1.거래금액) AS inflow_amount
        WHERE inflow_count >= {min_inflow}
        OPTIONAL MATCH (funnel)-[r2:TRANSFER]->(d:Account)
        WITH funnel, inflow_count, inflow_amount,
             count(DISTINCT d) AS outflow_count,
             coalesce(sum(r2.거래금액), 0) AS outflow_amount
        WHERE outflow_count <= {max_outflow}
        RETURN funnel.id AS account_id,
               inflow_count,
               inflow_amount,
               outflow_count,
               outflow_amount,
               inflow_count * 1.0 / CASE WHEN outflow_count = 0
                   THEN 1 ELSE outflow_count END AS funnel_ratio
        ORDER BY funnel_ratio DESC
        LIMIT {limit}
    """

    records = graph_db.execute(cypher)
    if not records:
        return empty

    rows = []
    for rec in records:
        rows.append({
            "account_id": rec.get("account_id"),
            "inflow_count": rec.get("inflow_count", 0),
            "inflow_amount": rec.get("inflow_amount", 0),
            "outflow_count": rec.get("outflow_count", 0),
            "outflow_amount": rec.get("outflow_amount", 0),
            "funnel_ratio": round(float(rec.get("funnel_ratio", 0)), 2),
        })
    return pd.DataFrame(rows)


def get_account_ego_network_deep(account_id, hops=3):
    """N-hop 심층 ego 네트워크를 Memgraph에서 추출한다.

    지정된 계좌를 중심으로 hops 단계까지의 이웃 계좌와 그들 사이의
    거래 관계를 서브그래프로 추출한다. 기존 get_account_ego_network보다
    더 깊은 탐색이 가능하다 (최대 5-hop).

    Memgraph 미실행 시 기존 get_account_ego_network를 폴백으로 호출한다
    (DuckDB 기반, 최대 2-hop까지 지원).

    Parameters
    ----------
    account_id : int
        중심 계좌 ID
    hops : int
        탐색 깊이 (기본 3, 최대 5)

    Returns
    -------
    pd.DataFrame
        컬럼: source, target, 거래횟수, 총금액, 이상거래여부
        기존 get_account_ego_network과 동일한 스키마
    """
    account_id = int(account_id)
    hops = min(int(hops), 5)

    if not graph_db.is_available():
        logger.warning(
            "Memgraph 미실행으로 심층 ego 네트워크 탐색 불가 (DuckDB 폴백, 최대 2-hop)"
        )
        fallback_hops = min(hops, 2)
        return get_account_ego_network(account_id, hops=fallback_hops)

    cypher = f"""
        MATCH p=(center:Account {{id: $account_id}})-[:TRANSFER*1..{hops}]-(neighbor)
        WITH collect(DISTINCT neighbor) + [center] AS all_nodes
        MATCH (center:Account {{id: $account_id}})
        WITH all_nodes, center
        UNWIND all_nodes AS n
        WITH collect(DISTINCT n) AS all_nodes
        UNWIND all_nodes AS n
        MATCH (n)-[r:TRANSFER]->(m)
        WHERE m IN all_nodes
        RETURN startNode(r).id AS source,
               endNode(r).id AS target,
               count(r) AS 거래횟수,
               sum(r.거래금액) AS 총금액,
               max(r.이상거래여부) AS 이상거래여부
    """

    df = graph_db.execute_df(cypher, {"account_id": account_id})
    if df.empty:
        # Memgraph에 데이터가 없을 수 있음 -> DuckDB 폴백
        logger.info("Memgraph 결과 비어있음, DuckDB 폴백 사용")
        fallback_hops = min(hops, 2)
        return get_account_ego_network(account_id, hops=fallback_hops)

    return df


def find_shortest_path(account_a, account_b):
    """두 계좌 간 최단 거래 경로를 찾는다.

    Memgraph의 shortestPath 알고리즘을 사용하여 두 계좌를 잇는
    최소 홉(hop) 수의 경로를 탐색한다.

    Parameters
    ----------
    account_a : int
        출발 계좌 ID
    account_b : int
        도착 계좌 ID

    Returns
    -------
    dict
        {"path": [계좌ID, ...], "hops": int, "amounts": [...], "dates": [...]}
        Memgraph 미실행 시: {"error": "Memgraph 미실행으로 최단경로 탐색 불가"}
        경로 없을 시: {"path": [], "hops": 0, "amounts": [], "dates": []}
    """
    account_a = int(account_a)
    account_b = int(account_b)

    if not graph_db.is_available():
        logger.warning("Memgraph 미실행으로 최단경로 탐색 불가")
        return {"error": "Memgraph 미실행으로 최단경로 탐색 불가"}

    cypher = """
        MATCH p=shortestPath(
            (a:Account {id: $account_a})-[:TRANSFER*]-(b:Account {id: $account_b})
        )
        RETURN [n IN nodes(p) | n.id] AS path,
               size(relationships(p)) AS hops,
               [r IN relationships(p) | r.거래금액] AS amounts,
               [r IN relationships(p) | r.거래일자] AS dates
    """

    records = graph_db.execute(cypher, {
        "account_a": account_a,
        "account_b": account_b,
    })

    if not records:
        return {"path": [], "hops": 0, "amounts": [], "dates": []}

    rec = records[0]
    return {
        "path": rec.get("path", []),
        "hops": rec.get("hops", 0),
        "amounts": rec.get("amounts", []),
        "dates": rec.get("dates", []),
    }


def get_temporal_network(start_date, end_date, fraud_only=True):
    """시간 윈도우 내 거래 네트워크를 추출한다.

    지정된 기간 내의 거래만으로 구성된 네트워크를 Memgraph에서 추출한다.
    fraud_only=True이면 이상거래만 포함한다.

    Parameters
    ----------
    start_date : int
        시작 거래일자 (예: 20210101)
    end_date : int
        종료 거래일자 (예: 20241231)
    fraud_only : bool
        이상거래만 필터할지 여부 (기본 True)

    Returns
    -------
    pd.DataFrame
        컬럼: source, target, 거래횟수, 총금액, 이상거래여부
        Memgraph 미실행 시 빈 DataFrame
    """
    empty = pd.DataFrame(columns=["source", "target", "거래횟수", "총금액", "이상거래여부"])

    if not graph_db.is_available():
        logger.warning("Memgraph 미실행으로 시간 윈도우 네트워크 추출 불가")
        return empty

    start_date = int(start_date)
    end_date = int(end_date)

    # fraud_only 조건을 Cypher 문자열로 분기 (파라미터 바인딩은 boolean 지원)
    fraud_filter = "AND r.이상거래여부 = 1" if fraud_only else ""

    cypher = f"""
        MATCH (a:Account)-[r:TRANSFER]->(b:Account)
        WHERE r.거래일자 >= $start_date AND r.거래일자 <= $end_date
              {fraud_filter}
        RETURN a.id AS source, b.id AS target,
               count(r) AS 거래횟수,
               sum(r.거래금액) AS 총금액,
               max(r.이상거래여부) AS 이상거래여부
        ORDER BY 거래횟수 DESC
        LIMIT 1000
    """

    df = graph_db.execute_df(cypher, {
        "start_date": start_date,
        "end_date": end_date,
    })

    if df.empty:
        return empty

    return df


def compute_risk_score(account_id):
    """그래프 기반 복합 위험 점수를 계산한다.

    여러 그래프 지표를 종합하여 특정 계좌의 AML 위험 점수(0.0~1.0)를
    산출한다. 가중치 구성:
    - 0.4: 직접 이상거래 비율
    - 0.3: 이웃 계좌의 이상거래 비율
    - 0.2: 사이클 참여 점수
    - 0.1: 입출금 집중도

    Parameters
    ----------
    account_id : int
        분석 대상 계좌 ID

    Returns
    -------
    dict
        {
            "account_id": int,
            "risk_score": float (0.0~1.0),
            "components": {
                "fraud_ratio": float,
                "neighbor_fraud_ratio": float,
                "cycle_score": float,
                "concentration_score": float,
            }
        }
        Memgraph 미실행 시: {"account_id": ..., "risk_score": 0.0, "error": "Memgraph 미실행"}
    """
    account_id = int(account_id)

    if not graph_db.is_available():
        logger.warning("Memgraph 미실행으로 위험 점수 계산 불가")
        return {"account_id": account_id, "risk_score": 0.0, "error": "Memgraph 미실행"}

    # 1) 직접 이상거래 비율
    cypher_fraud = """
        MATCH (a:Account {id: $account_id})-[r:TRANSFER]-()
        WITH count(r) AS total_txn,
             sum(CASE WHEN r.이상거래여부 = 1 THEN 1 ELSE 0 END) AS fraud_txn
        RETURN total_txn, fraud_txn,
               CASE WHEN total_txn = 0 THEN 0.0
                    ELSE fraud_txn * 1.0 / total_txn END AS fraud_ratio
    """
    fraud_records = graph_db.execute(cypher_fraud, {"account_id": account_id})

    if not fraud_records:
        return {
            "account_id": account_id,
            "risk_score": 0.0,
            "components": {
                "fraud_ratio": 0.0,
                "neighbor_fraud_ratio": 0.0,
                "cycle_score": 0.0,
                "concentration_score": 0.0,
            },
        }

    fraud_ratio = float(fraud_records[0].get("fraud_ratio", 0.0))

    # 2) 이웃 계좌의 이상거래 비율
    cypher_neighbor = """
        MATCH (a:Account {id: $account_id})-[:TRANSFER]-(neighbor:Account)
        WITH collect(DISTINCT neighbor) AS neighbors
        UNWIND neighbors AS nb
        MATCH (nb)-[r:TRANSFER]-()
        WITH count(r) AS neighbor_total,
             sum(CASE WHEN r.이상거래여부 = 1 THEN 1 ELSE 0 END) AS neighbor_fraud
        RETURN CASE WHEN neighbor_total = 0 THEN 0.0
                    ELSE neighbor_fraud * 1.0 / neighbor_total END AS neighbor_fraud_ratio
    """
    neighbor_records = graph_db.execute(cypher_neighbor, {"account_id": account_id})
    neighbor_fraud_ratio = 0.0
    if neighbor_records:
        neighbor_fraud_ratio = float(
            neighbor_records[0].get("neighbor_fraud_ratio", 0.0)
        )

    # 3) 사이클 참여 여부 (짧은 사이클 3~4-hop 존재 여부)
    cypher_cycle = """
        MATCH p=(a:Account {id: $account_id})-[:TRANSFER*3..4]->(a)
        RETURN count(p) AS cycle_count
    """
    cycle_records = graph_db.execute(cypher_cycle, {"account_id": account_id})
    cycle_count = 0
    if cycle_records:
        cycle_count = int(cycle_records[0].get("cycle_count", 0))
    # 사이클 점수: 1개 이상 참여 시 0.5, 5개 이상이면 1.0
    cycle_score = min(cycle_count / 5.0, 1.0) if cycle_count > 0 else 0.0

    # 4) 입출금 집중도 (inflow/outflow 비율 불균형)
    cypher_concentration = """
        MATCH (a:Account {id: $account_id})
        OPTIONAL MATCH (a)<-[r_in:TRANSFER]-()
        WITH a, count(r_in) AS in_count
        OPTIONAL MATCH (a)-[r_out:TRANSFER]->()
        WITH in_count, count(r_out) AS out_count
        RETURN in_count, out_count,
               CASE WHEN (in_count + out_count) = 0 THEN 0.0
                    ELSE abs(in_count - out_count) * 1.0 / (in_count + out_count)
               END AS concentration
    """
    conc_records = graph_db.execute(cypher_concentration, {"account_id": account_id})
    concentration_score = 0.0
    if conc_records:
        concentration_score = float(conc_records[0].get("concentration", 0.0))

    # 가중 합산
    risk_score = (
        0.4 * fraud_ratio
        + 0.3 * neighbor_fraud_ratio
        + 0.2 * cycle_score
        + 0.1 * concentration_score
    )
    risk_score = round(min(max(risk_score, 0.0), 1.0), 4)

    return {
        "account_id": account_id,
        "risk_score": risk_score,
        "components": {
            "fraud_ratio": round(fraud_ratio, 4),
            "neighbor_fraud_ratio": round(neighbor_fraud_ratio, 4),
            "cycle_score": round(cycle_score, 4),
            "concentration_score": round(concentration_score, 4),
        },
    }
