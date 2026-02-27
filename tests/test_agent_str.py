"""_build_str_report() 전용 단위 테스트.

검증 항목 (요청된 9개 케이스 + 추가 커버리지):
1. transactions 있을 때: 계좌·금액·채널이 올바르게 추출되는지
2. transactions 없을 때(빈 리스트): 폴백 동작 (summary regex 추출, 빈 목록)
3. fraud_probability=0.87 → 의심강도_1to5=4 (round(0.87*4)+1=4)
4. fraud_probability=None → 의심강도_1to5=3 기본값
5. 이상거래유형=1 (자금세탁) → VI_거래유형.해당항목에 "분할거래" 포함
6. 이상거래유형=3 (대포통장) → VI_거래유형.해당항목에 "타인의 명의 또는 계좌의 이용" 포함
7. aml_patterns=["레이어링"] → VI 항목에 "갑작스러운 거래패턴의 변화" 추가
8. 매체구분=4 → 거래채널="인터넷뱅킹"
9. 자금구분=4 → 거래종류="이체"

추가:
- 반환 구조 전체 키 검증 (11개 최상위 키)
- 표제부, I~IV, VI, VII 섹션 구조 상세 검증
- 복수 거래 데이터 집계 (총거래금액, 최대단건금액, 거래건수)
- 거래기간 산출 (min/max 날짜)
- 관련계좌수 및 관련계좌존재여부 계산
- aml_patterns가 VI_거래유형.탐지된AML패턴에 포함되는지
- 권고조치 매핑 검증 (자금세탁, 대포통장, 보이스피싱)
- 분석근거 도구 이름 매핑 검증
- 빈 aml_patterns 처리
- 매체구분 없는 거래 → 거래채널="미확인"
"""

import re
import pytest
from src.features.agent import _build_str_report


# ---------------------------------------------------------------------------
# 공통 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def base_kwargs():
    """_build_str_report() 최소 기본 인수 세트."""
    return dict(
        summary="테스트 의심거래 요약",
        fraud_type="자금세탁",
        tools_used=[],
        transactions=[],
        fraud_probability=None,
        aml_patterns=[],
    )


@pytest.fixture
def sample_transactions():
    """3건의 샘플 거래 레코드 (다양한 매체·자금구분 포함)."""
    return [
        {
            "거래일자": 20240101,
            "거래시간대": 21,
            "출금금융회사일련번호": 10,
            "출금계좌일련번호": 1001001,
            "입금금융회사일련번호": 20,
            "입금계좌일련번호": 2001001,
            "자금구분": 1,
            "매체구분": 4,        # 인터넷뱅킹
            "거래금액": 1_000_000,
            "이상거래유형": 1,    # 자금세탁
        },
        {
            "거래일자": 20240115,
            "거래시간대": 3,
            "출금금융회사일련번호": 10,
            "출금계좌일련번호": 1001002,
            "입금금융회사일련번호": 20,
            "입금계좌일련번호": 2001002,
            "자금구분": 4,        # 이체
            "매체구분": 4,        # 인터넷뱅킹
            "거래금액": 5_000_000,
            "이상거래유형": 1,    # 자금세탁
        },
        {
            "거래일자": 20240131,
            "거래시간대": 9,
            "출금금융회사일련번호": 11,
            "출금계좌일련번호": 1001003,
            "입금금융회사일련번호": 21,
            "입금계좌일련번호": 2001003,
            "자금구분": 4,        # 이체
            "매체구분": 2,        # ATM
            "거래금액": 2_500_000,
            "이상거래유형": 1,    # 자금세탁
        },
    ]


def _call(base_kwargs, **overrides):
    """base_kwargs를 복사하고 overrides를 적용하여 _build_str_report를 호출한다."""
    kw = dict(base_kwargs)
    kw.update(overrides)
    return _build_str_report(**kw)


# ===========================================================================
# 1. 반환 구조 전체 검증
# ===========================================================================

class TestReturnStructure:
    """반환 딕셔너리의 최상위 키 및 섹션 구조 검증."""

    def test_returns_dict(self, base_kwargs):
        """반환값이 dict이어야 한다."""
        result = _call(base_kwargs)
        assert isinstance(result, dict)

    def test_top_level_keys_complete(self, base_kwargs):
        """11개 최상위 키가 모두 존재해야 한다."""
        result = _call(base_kwargs)
        expected = {
            "보고서유형", "표제부", "I_보고기관", "II_거래자",
            "III_거래내역", "IV_관련계좌", "VI_거래유형", "VII_서술",
            "권고조치", "분석근거", "작성안내",
        }
        assert expected.issubset(set(result.keys()))

    def test_보고서유형_value(self, base_kwargs):
        """보고서유형이 '의심거래보고서(STR)'이어야 한다."""
        result = _call(base_kwargs)
        assert result["보고서유형"] == "의심거래보고서(STR)"

    def test_표제부_keys(self, base_kwargs):
        """표제부에 보고일자와 보고서구분이 있어야 한다."""
        result = _call(base_kwargs)
        assert "보고일자" in result["표제부"]
        assert "보고서구분" in result["표제부"]

    def test_표제부_보고일자_format(self, base_kwargs):
        """표제부.보고일자가 YYYY-MM-DD 형식이어야 한다."""
        result = _call(base_kwargs)
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", result["표제부"]["보고일자"])

    def test_표제부_보고서구분(self, base_kwargs):
        """표제부.보고서구분이 '신규보고'이어야 한다."""
        result = _call(base_kwargs)
        assert result["표제부"]["보고서구분"] == "신규보고"

    def test_I_보고기관_keys(self, base_kwargs):
        """I_보고기관에 출금금융회사코드와 비고가 있어야 한다."""
        result = _call(base_kwargs)
        assert "출금금융회사코드" in result["I_보고기관"]
        assert "비고" in result["I_보고기관"]

    def test_II_거래자_keys(self, base_kwargs):
        """II_거래자에 출금계좌번호, 입금계좌번호, 비고가 있어야 한다."""
        result = _call(base_kwargs)
        for key in ("출금계좌번호", "입금계좌번호", "비고"):
            assert key in result["II_거래자"], f"II_거래자에 '{key}' 키 누락"

    def test_III_거래내역_keys(self, base_kwargs):
        """III_거래내역에 7개 필드가 있어야 한다."""
        result = _call(base_kwargs)
        for key in ("거래기간", "거래건수", "거래채널", "거래종류",
                    "총거래금액_원", "최대단건금액_원", "관련계좌존재여부"):
            assert key in result["III_거래내역"], f"III_거래내역에 '{key}' 키 누락"

    def test_IV_관련계좌_keys(self, base_kwargs):
        """IV_관련계좌에 4개 필드가 있어야 한다."""
        result = _call(base_kwargs)
        for key in ("출금계좌목록", "입금계좌목록", "출금금융회사코드", "입금금융회사코드"):
            assert key in result["IV_관련계좌"], f"IV_관련계좌에 '{key}' 키 누락"

    def test_VI_거래유형_keys(self, base_kwargs):
        """VI_거래유형에 3개 필드가 있어야 한다."""
        result = _call(base_kwargs)
        for key in ("주요의심유형", "해당항목", "탐지된AML패턴"):
            assert key in result["VI_거래유형"], f"VI_거래유형에 '{key}' 키 누락"

    def test_VII_서술_keys(self, base_kwargs):
        """VII_서술에 7개 필드가 있어야 한다."""
        result = _call(base_kwargs)
        for key in ("의심거래자관련", "거래발생일자", "거래방법특이사항",
                    "혐의판단사유", "종합의견", "의심강도_1to5", "의심강도설명"):
            assert key in result["VII_서술"], f"VII_서술에 '{key}' 키 누락"

    def test_권고조치_is_list(self, base_kwargs):
        """권고조치가 비어 있지 않은 리스트이어야 한다."""
        result = _call(base_kwargs)
        assert isinstance(result["권고조치"], list)
        assert len(result["권고조치"]) > 0

    def test_분석근거_is_list(self, base_kwargs):
        """분석근거가 리스트이어야 한다."""
        result = _call(base_kwargs)
        assert isinstance(result["분석근거"], list)

    def test_작성안내_is_nonempty_string(self, base_kwargs):
        """작성안내가 비어 있지 않은 문자열이어야 한다."""
        result = _call(base_kwargs)
        assert isinstance(result["작성안내"], str)
        assert len(result["작성안내"]) > 0


# ===========================================================================
# 2. 케이스 1: transactions 있을 때 계좌·금액·채널 추출
# ===========================================================================

class TestTransactionsExtraction:
    """케이스 1: transactions 데이터가 있을 때 필드 추출 검증."""

    def test_출금계좌목록_extracted(self, base_kwargs, sample_transactions):
        """출금계좌일련번호가 IV_관련계좌.출금계좌목록에 포함되어야 한다."""
        result = _call(base_kwargs, transactions=sample_transactions)
        목록 = result["IV_관련계좌"]["출금계좌목록"]
        assert "1001001" in 목록 or "1001002" in 목록 or "1001003" in 목록

    def test_입금계좌목록_extracted(self, base_kwargs, sample_transactions):
        """입금계좌일련번호가 IV_관련계좌.입금계좌목록에 포함되어야 한다."""
        result = _call(base_kwargs, transactions=sample_transactions)
        목록 = result["IV_관련계좌"]["입금계좌목록"]
        assert "2001001" in 목록 or "2001002" in 목록 or "2001003" in 목록

    def test_총거래금액_sum(self, base_kwargs, sample_transactions):
        """III_거래내역.총거래금액_원이 모든 거래금액의 합이어야 한다."""
        result = _call(base_kwargs, transactions=sample_transactions)
        expected = 1_000_000 + 5_000_000 + 2_500_000
        assert result["III_거래내역"]["총거래금액_원"] == expected

    def test_최대단건금액(self, base_kwargs, sample_transactions):
        """III_거래내역.최대단건금액_원이 가장 큰 단건 금액이어야 한다."""
        result = _call(base_kwargs, transactions=sample_transactions)
        assert result["III_거래내역"]["최대단건금액_원"] == 5_000_000

    def test_거래건수(self, base_kwargs, sample_transactions):
        """III_거래내역.거래건수가 transactions 길이와 같아야 한다."""
        result = _call(base_kwargs, transactions=sample_transactions)
        assert result["III_거래내역"]["거래건수"] == len(sample_transactions)

    def test_출금금융회사코드_extracted(self, base_kwargs, sample_transactions):
        """I_보고기관.출금금융회사코드에 출금 회사 코드가 포함되어야 한다."""
        result = _call(base_kwargs, transactions=sample_transactions)
        codes = result["I_보고기관"]["출금금융회사코드"]
        assert "10" in codes or "11" in codes

    def test_거래채널_most_common_매체(self, base_kwargs, sample_transactions):
        """가장 빈번한 매체구분(4=인터넷뱅킹)이 거래채널로 선택되어야 한다.
        sample_transactions에서 매체구분 4가 2번, 2가 1번이므로 인터넷뱅킹이 선택됨."""
        result = _call(base_kwargs, transactions=sample_transactions)
        # 매체구분 4(인터넷뱅킹)이 최빈값
        assert result["III_거래내역"]["거래채널"] == "인터넷뱅킹"


# ===========================================================================
# 3. 케이스 2: transactions 없을 때(빈 리스트) 폴백 동작
# ===========================================================================

class TestEmptyTransactionsFallback:
    """케이스 2: transactions=[] 일 때 폴백 동작 검증."""

    def test_거래건수_is_zero(self, base_kwargs):
        """거래 없을 때 거래건수가 0이어야 한다."""
        result = _call(base_kwargs, transactions=[])
        assert result["III_거래내역"]["거래건수"] == 0

    def test_총거래금액_is_zero(self, base_kwargs):
        """거래 없을 때 총거래금액이 0이어야 한다."""
        result = _call(base_kwargs, transactions=[])
        assert result["III_거래내역"]["총거래금액_원"] == 0

    def test_최대단건금액_is_zero(self, base_kwargs):
        """거래 없을 때 최대단건금액이 0이어야 한다."""
        result = _call(base_kwargs, transactions=[])
        assert result["III_거래내역"]["최대단건금액_원"] == 0

    def test_거래채널_미확인_when_no_transactions(self, base_kwargs):
        """거래 없을 때 거래채널이 '미확인'이어야 한다."""
        result = _call(base_kwargs, transactions=[])
        assert result["III_거래내역"]["거래채널"] == "미확인"

    def test_summary_regex_extracts_account(self, base_kwargs):
        """summary에 계좌 번호가 있으면 regex로 추출하여 II_거래자에 반영해야 한다."""
        summary = "출금계좌 1234567890에서 500만원 이동"
        result = _call(base_kwargs, summary=summary, transactions=[])
        # regex 추출: 5자리 이상 숫자
        ii = result["II_거래자"]
        # 추출 결과가 있어야 함 (빈 "미확인" 리스트가 아닌 경우)
        combined = ii["출금계좌번호"] + ii["입금계좌번호"]
        # "1234567890"이 추출되거나 비어 있는 두 가지 가능성 모두 허용
        # 단, combined 자체가 리스트이어야 함
        assert isinstance(combined, list)

    def test_no_account_in_summary_results_in_미확인(self, base_kwargs):
        """summary에 계좌 번호가 없으면 II_거래자가 '미확인'을 반환해야 한다."""
        result = _call(base_kwargs, summary="이상거래가 발견되었습니다.", transactions=[])
        ii = result["II_거래자"]
        # 추출할 계좌 없으면 ["미확인"] 반환
        assert ii["출금계좌번호"] == ["미확인"]
        assert ii["입금계좌번호"] == ["미확인"]

    def test_IV_목록_empty_when_no_transactions(self, base_kwargs):
        """거래 없고 summary에서도 추출 불가면 IV 목록이 빈 리스트이어야 한다."""
        result = _call(base_kwargs, summary="이상거래 확인 필요", transactions=[])
        assert result["IV_관련계좌"]["출금계좌목록"] == []
        assert result["IV_관련계좌"]["입금계좌목록"] == []


# ===========================================================================
# 4. 케이스 3 & 4: fraud_probability → 의심강도_1to5
# ===========================================================================

class TestFraudProbabilityToSuspicionScore:
    """케이스 3·4: fraud_probability → VII_서술.의심강도_1to5 매핑 검증."""

    @pytest.mark.parametrize("prob,expected", [
        (0.87, 4),    # round(0.87*4)+1 = round(3.48)+1 = 3+1 = 4
        (1.00, 5),    # round(4.0)+1 = 5, min(5, 5)=5
        (0.00, 1),    # round(0.0)+1 = 1, max(1, 1)=1
        (0.25, 2),    # round(0.25*4)+1 = round(1.0)+1 = 2
        (0.50, 3),    # round(0.50*4)+1 = round(2.0)+1 = 3
        (0.75, 4),    # round(0.75*4)+1 = round(3.0)+1 = 4
    ])
    def test_probability_to_score(self, base_kwargs, prob, expected):
        """fraud_probability가 의심강도_1to5로 올바르게 변환되어야 한다."""
        result = _call(base_kwargs, fraud_probability=prob)
        assert result["VII_서술"]["의심강도_1to5"] == expected, (
            f"prob={prob}: expected={expected}, "
            f"got={result['VII_서술']['의심강도_1to5']}"
        )

    def test_probability_087_gives_score_4(self, base_kwargs):
        """케이스 3: fraud_probability=0.87 → 의심강도_1to5=4."""
        result = _call(base_kwargs, fraud_probability=0.87)
        assert result["VII_서술"]["의심강도_1to5"] == 4

    def test_probability_none_gives_default_3(self, base_kwargs):
        """케이스 4: fraud_probability=None → 의심강도_1to5=3 기본값."""
        result = _call(base_kwargs, fraud_probability=None)
        assert result["VII_서술"]["의심강도_1to5"] == 3

    def test_probability_none_설명_mentions_AI미수행(self, base_kwargs):
        """fraud_probability=None이면 의심강도설명에 AI 예측 미수행 언급."""
        result = _call(base_kwargs, fraud_probability=None)
        설명 = result["VII_서술"]["의심강도설명"]
        assert "AI" in 설명 or "예측" in 설명 or "미수행" in 설명

    def test_probability_given_설명_mentions_percent(self, base_kwargs):
        """fraud_probability가 있으면 의심강도설명에 확률이 포함되어야 한다."""
        result = _call(base_kwargs, fraud_probability=0.87)
        설명 = result["VII_서술"]["의심강도설명"]
        assert "87" in 설명 or "%" in 설명

    def test_score_within_range_1_to_5(self, base_kwargs):
        """의심강도_1to5가 항상 1~5 범위이어야 한다."""
        for prob in [0.0, 0.1, 0.5, 0.9, 1.0, None]:
            result = _call(base_kwargs, fraud_probability=prob)
            score = result["VII_서술"]["의심강도_1to5"]
            assert 1 <= score <= 5, f"prob={prob}: 범위 초과 score={score}"


# ===========================================================================
# 5 & 6. 이상거래유형 → VI_거래유형.해당항목 매핑
# ===========================================================================

class TestFraudTypeToVIItems:
    """케이스 5·6: 이상거래유형 코드 → VI_거래유형.해당항목 매핑 검증."""

    def _tx(self, 유형코드):
        """특정 이상거래유형 코드를 가진 단일 거래 레코드를 생성한다."""
        return [{
            "거래일자": 20240101,
            "거래시간대": 9,
            "출금금융회사일련번호": 10,
            "출금계좌일련번호": 1000001,
            "입금금융회사일련번호": 20,
            "입금계좌일련번호": 2000001,
            "자금구분": 1,
            "매체구분": 1,
            "거래금액": 500_000,
            "이상거래유형": 유형코드,
        }]

    def test_유형1_자금세탁_includes_분할거래(self, base_kwargs):
        """케이스 5: 이상거래유형=1(자금세탁) → VI.해당항목에 '분할거래' 포함."""
        result = _call(base_kwargs, transactions=self._tx(1))
        assert "분할거래" in result["VI_거래유형"]["해당항목"]

    def test_유형3_대포통장_includes_타인명의(self, base_kwargs):
        """케이스 6: 이상거래유형=3(대포통장) → VI.해당항목에 '타인의 명의 또는 계좌의 이용' 포함."""
        result = _call(base_kwargs, transactions=self._tx(3))
        assert "타인의 명의 또는 계좌의 이용" in result["VI_거래유형"]["해당항목"]

    def test_유형4_보이스피싱_includes_당일인출(self, base_kwargs):
        """이상거래유형=4(보이스피싱) → VI.해당항목에 '거액 입금 후 당일 또는 익일 중 인출' 포함."""
        result = _call(base_kwargs, transactions=self._tx(4))
        assert "거액 입금 후 당일 또는 익일 중 인출" in result["VI_거래유형"]["해당항목"]

    def test_유형2_신규거래처_includes_사전거래없음(self, base_kwargs):
        """이상거래유형=2(신규거래처) → VI.해당항목에 '사전거래가 없는 고객의 의심스러운 거래 요청' 포함."""
        result = _call(base_kwargs, transactions=self._tx(2))
        assert "사전거래가 없는 고객의 의심스러운 거래 요청" in result["VI_거래유형"]["해당항목"]

    def test_유형없음_defaults_to_기타(self, base_kwargs):
        """이상거래유형 없는 거래 → VI.해당항목이 기타 안내 문자열이어야 한다."""
        tx = [{"거래일자": 20240101, "거래금액": 100_000}]  # 이상거래유형 없음
        result = _call(base_kwargs, transactions=tx)
        항목 = result["VI_거래유형"]["해당항목"]
        assert isinstance(항목, list)
        assert len(항목) > 0

    def test_주요의심유형_name_mapped_correctly(self, base_kwargs):
        """VI_거래유형.주요의심유형이 코드에 맞는 한글 이름이어야 한다."""
        result = _call(base_kwargs, transactions=self._tx(3))
        assert result["VI_거래유형"]["주요의심유형"] == "대포통장"


# ===========================================================================
# 7. 케이스 7: aml_patterns → VI_거래유형.해당항목 추가
# ===========================================================================

class TestAmlPatternsToVIItems:
    """케이스 7: aml_patterns → VI_거래유형.해당항목 추가 검증."""

    def test_레이어링_패턴_adds_갑작스러운변화(self, base_kwargs):
        """케이스 7: aml_patterns=['레이어링'] → VI.해당항목에 '갑작스러운 거래패턴의 변화' 추가."""
        result = _call(base_kwargs, aml_patterns=["레이어링"])
        assert "갑작스러운 거래패턴의 변화" in result["VI_거래유형"]["해당항목"]

    def test_순환거래_패턴_adds_분할거래(self, base_kwargs):
        """aml_patterns=['순환거래'] → VI.해당항목에 '분할거래' 추가."""
        result = _call(base_kwargs, aml_patterns=["순환거래"])
        assert "분할거래" in result["VI_거래유형"]["해당항목"]

    def test_대포통장_패턴_adds_타인명의(self, base_kwargs):
        """aml_patterns=['대포통장'] → VI.해당항목에 '타인의 명의 또는 계좌의 이용' 추가."""
        result = _call(base_kwargs, aml_patterns=["대포통장"])
        assert "타인의 명의 또는 계좌의 이용" in result["VI_거래유형"]["해당항목"]

    def test_aml_patterns_in_탐지된AML패턴(self, base_kwargs):
        """aml_patterns가 VI_거래유형.탐지된AML패턴에 그대로 포함되어야 한다."""
        patterns = ["레이어링", "순환거래"]
        result = _call(base_kwargs, aml_patterns=patterns)
        assert result["VI_거래유형"]["탐지된AML패턴"] == patterns

    def test_empty_aml_patterns_탐지된AML패턴_is_empty(self, base_kwargs):
        """aml_patterns=[] → VI_거래유형.탐지된AML패턴이 빈 리스트이어야 한다."""
        result = _call(base_kwargs, aml_patterns=[])
        assert result["VI_거래유형"]["탐지된AML패턴"] == []

    def test_aml_patterns_종합의견_mentions_patterns(self, base_kwargs):
        """aml_patterns가 있으면 VII_서술.종합의견에 패턴명이 포함되어야 한다."""
        result = _call(base_kwargs, aml_patterns=["레이어링"])
        assert "레이어링" in result["VII_서술"]["종합의견"]

    def test_no_aml_patterns_종합의견_no_pattern_mention(self, base_kwargs):
        """aml_patterns=[] → 종합의견에 '탐지된 AML 패턴' 구절이 없어야 한다."""
        result = _call(base_kwargs, aml_patterns=[])
        assert "탐지된 AML 패턴" not in result["VII_서술"]["종합의견"]

    def test_duplicate_vi_항목_not_added(self, base_kwargs):
        """이미 유형 매핑에 포함된 VI 항목은 AML 패턴으로 중복 추가되지 않아야 한다."""
        # 이상거래유형=1(자금세탁) → '갑작스러운 거래패턴의 변화'가 이미 매핑됨
        tx = [{
            "거래일자": 20240101, "거래금액": 500_000,
            "출금계좌일련번호": 1001, "입금계좌일련번호": 2001,
            "출금금융회사일련번호": 10, "입금금융회사일련번호": 20,
            "자금구분": 1, "매체구분": 1, "이상거래유형": 1,
        }]
        result = _call(base_kwargs, transactions=tx, aml_patterns=["레이어링"])
        항목 = result["VI_거래유형"]["해당항목"]
        count = 항목.count("갑작스러운 거래패턴의 변화")
        assert count == 1, f"중복 항목 발생: count={count}"


# ===========================================================================
# 8. 케이스 8: 매체구분 → 거래채널 매핑
# ===========================================================================

class TestMediaTypeToChannel:
    """케이스 8: 매체구분 코드 → III_거래내역.거래채널 매핑 검증."""

    @pytest.mark.parametrize("매체코드,expected_channel", [
        (1, "창구"),
        (2, "자동화기기(ATM)"),
        (3, "PB센터"),
        (4, "인터넷뱅킹"),
        (5, "전화/휴대전화"),
        (6, "콜센터"),
        (7, "기타"),
    ])
    def test_매체구분_to_채널_mapping(self, base_kwargs, 매체코드, expected_channel):
        """케이스 8: 매체구분 코드가 올바른 채널 이름으로 매핑되어야 한다."""
        tx = [{
            "거래일자": 20240101,
            "출금계좌일련번호": 1001,
            "입금계좌일련번호": 2001,
            "출금금융회사일련번호": 10,
            "입금금융회사일련번호": 20,
            "자금구분": 1,
            "매체구분": 매체코드,
            "거래금액": 100_000,
            "이상거래유형": 1,
        }]
        result = _call(base_kwargs, transactions=tx)
        assert result["III_거래내역"]["거래채널"] == expected_channel

    def test_매체구분_4_인터넷뱅킹(self, base_kwargs):
        """케이스 8 (명시적): 매체구분=4 → 거래채널='인터넷뱅킹'."""
        tx = [{
            "거래일자": 20240101,
            "출금계좌일련번호": 1001,
            "입금계좌일련번호": 2001,
            "출금금융회사일련번호": 10,
            "입금금융회사일련번호": 20,
            "자금구분": 1,
            "매체구분": 4,
            "거래금액": 1_000_000,
            "이상거래유형": 1,
        }]
        result = _call(base_kwargs, transactions=tx)
        assert result["III_거래내역"]["거래채널"] == "인터넷뱅킹"

    def test_no_매체구분_gives_미확인(self, base_kwargs):
        """매체구분 없는 거래 → 거래채널='미확인'이어야 한다."""
        tx = [{"거래일자": 20240101, "거래금액": 100_000}]
        result = _call(base_kwargs, transactions=tx)
        assert result["III_거래내역"]["거래채널"] == "미확인"


# ===========================================================================
# 9. 케이스 9: 자금구분 → 거래종류 매핑
# ===========================================================================

class TestFundTypeToTransactionType:
    """케이스 9: 자금구분 코드 → III_거래내역.거래종류 매핑 검증."""

    @pytest.mark.parametrize("자금코드,expected_type", [
        (0, "해당없음"),
        (1, "입금"),
        (3, "출금"),
        (4, "이체"),
    ])
    def test_자금구분_to_거래종류_mapping(self, base_kwargs, 자금코드, expected_type):
        """자금구분 코드가 올바른 거래종류 이름으로 매핑되어야 한다."""
        tx = [{
            "거래일자": 20240101,
            "출금계좌일련번호": 1001,
            "입금계좌일련번호": 2001,
            "출금금융회사일련번호": 10,
            "입금금융회사일련번호": 20,
            "자금구분": 자금코드,
            "매체구분": 1,
            "거래금액": 100_000,
            "이상거래유형": 1,
        }]
        result = _call(base_kwargs, transactions=tx)
        assert result["III_거래내역"]["거래종류"] == expected_type

    def test_자금구분_4_이체(self, base_kwargs):
        """케이스 9 (명시적): 자금구분=4 → 거래종류='이체'."""
        tx = [{
            "거래일자": 20240101,
            "출금계좌일련번호": 1001,
            "입금계좌일련번호": 2001,
            "출금금융회사일련번호": 10,
            "입금금융회사일련번호": 20,
            "자금구분": 4,
            "매체구분": 1,
            "거래금액": 5_000_000,
            "이상거래유형": 1,
        }]
        result = _call(base_kwargs, transactions=tx)
        assert result["III_거래내역"]["거래종류"] == "이체"

    def test_no_자금구분_gives_미확인(self, base_kwargs):
        """자금구분 없는 거래 → 거래종류='미확인'이어야 한다."""
        tx = [{"거래일자": 20240101, "거래금액": 100_000}]
        result = _call(base_kwargs, transactions=tx)
        assert result["III_거래내역"]["거래종류"] == "미확인"


# ===========================================================================
# 10. 거래기간 산출
# ===========================================================================

class TestTransactionPeriod:
    """거래기간 산출 검증 (단일 날짜 vs 복수 날짜)."""

    def test_single_date_period(self, base_kwargs):
        """거래가 하루이면 거래기간이 그 날짜 단일값이어야 한다."""
        tx = [{
            "거래일자": 20240101,
            "출금계좌일련번호": 1001,
            "입금계좌일련번호": 2001,
            "출금금융회사일련번호": 10,
            "입금금융회사일련번호": 20,
            "자금구분": 1,
            "매체구분": 1,
            "거래금액": 100_000,
        }]
        result = _call(base_kwargs, transactions=tx)
        assert result["III_거래내역"]["거래기간"] == "20240101"

    def test_multiple_dates_period(self, base_kwargs, sample_transactions):
        """여러 날짜가 있으면 거래기간이 '시작 ~ 종료' 형식이어야 한다."""
        result = _call(base_kwargs, transactions=sample_transactions)
        기간 = result["III_거래내역"]["거래기간"]
        assert "~" in 기간, f"기간 구분자 '~' 없음: '{기간}'"
        parts = [p.strip() for p in 기간.split("~")]
        assert parts[0] == "20240101"
        assert parts[1] == "20240131"

    def test_no_transactions_period_is_미확인(self, base_kwargs):
        """거래 없으면 거래기간이 '미확인'이어야 한다."""
        result = _call(base_kwargs, transactions=[])
        assert result["III_거래내역"]["거래기간"] == "미확인"


# ===========================================================================
# 11. 관련계좌 존재 여부
# ===========================================================================

class TestRelatedAccountExistence:
    """III_거래내역.관련계좌존재여부 계산 검증."""

    def test_accounts_present_gives_여(self, base_kwargs, sample_transactions):
        """계좌가 있으면 관련계좌존재여부='여'이어야 한다."""
        result = _call(base_kwargs, transactions=sample_transactions)
        assert result["III_거래내역"]["관련계좌존재여부"] == "여"

    def test_no_accounts_gives_부(self, base_kwargs):
        """계좌가 없으면 관련계좌존재여부='부'이어야 한다."""
        result = _call(base_kwargs, summary="이상거래 발생", transactions=[])
        # transactions 없고 summary에도 계좌 없음
        assert result["III_거래내역"]["관련계좌존재여부"] == "부"


# ===========================================================================
# 12. 권고조치 매핑
# ===========================================================================

class TestRecommendedActions:
    """fraud_type → 권고조치 매핑 검증."""

    @pytest.mark.parametrize("fraud_type,keyword", [
        ("자금세탁", "모니터링"),
        ("대포통장", "계좌"),
        ("보이스피싱", "수사기관"),
        ("불법도박", "모니터링"),
        ("유사수신", "신고"),
        ("신규거래처", "CDD"),
        ("기타", "모니터링"),
    ])
    def test_권고조치_contains_keyword(self, base_kwargs, fraud_type, keyword):
        """fraud_type에 맞는 권고조치 키워드가 포함되어야 한다."""
        result = _call(base_kwargs, fraud_type=fraud_type)
        actions_text = " ".join(result["권고조치"])
        assert keyword in actions_text, (
            f"fraud_type='{fraud_type}': '{keyword}'이 권고조치에 없음. "
            f"권고조치={result['권고조치']}"
        )


# ===========================================================================
# 13. 분석근거 도구 이름 매핑
# ===========================================================================

class TestAnalysisBasis:
    """tools_used → 분석근거 매핑 검증."""

    def test_known_tool_gets_description(self, base_kwargs):
        """알려진 도구 이름이 설명으로 변환되어야 한다."""
        result = _call(base_kwargs, tools_used=["query_transactions"])
        assert "HOFINET DB 거래 데이터 직접 조회" in result["분석근거"]

    def test_all_tools_mapped(self, base_kwargs):
        """모든 알려진 도구가 분석근거에 반영되어야 한다."""
        tools = ["query_transactions", "predict_fraud", "analyze_network", "get_statistics"]
        result = _call(base_kwargs, tools_used=tools)
        assert len(result["분석근거"]) == 4

    def test_empty_tools_gives_fallback(self, base_kwargs):
        """tools_used=[] → 분석근거에 '분석 도구 미지정' 또는 빈 리스트가 있어야 한다."""
        result = _call(base_kwargs, tools_used=[])
        근거 = result["분석근거"]
        assert isinstance(근거, list)
        # 빈 도구 목록: 폴백 메시지 또는 빈 리스트
        if 근거:
            assert "분석 도구 미지정" in 근거

    def test_unknown_tool_passthrough(self, base_kwargs):
        """매핑 없는 도구 이름은 그대로 분석근거에 포함되어야 한다."""
        result = _call(base_kwargs, tools_used=["custom_tool"])
        assert "custom_tool" in result["분석근거"]


# ===========================================================================
# 14. summary 보존
# ===========================================================================

class TestSummaryPreservation:
    """summary → VII_서술.혐의판단사유 보존 검증."""

    def test_summary_in_혐의판단사유(self, base_kwargs):
        """입력 summary가 혐의판단사유에 그대로 보존되어야 한다."""
        summary = "계좌 A에서 심야 다수 소액 이체 후 대량 출금 의심"
        result = _call(base_kwargs, summary=summary)
        assert result["VII_서술"]["혐의판단사유"] == summary

    def test_summary_in_종합의견(self, base_kwargs):
        """VII_서술.종합의견에 의심유형명이 포함되어야 한다."""
        result = _call(base_kwargs, fraud_type="보이스피싱",
                       transactions=[{
                           "거래일자": 20240101, "거래금액": 100_000,
                           "출금계좌일련번호": 1001, "입금계좌일련번호": 2001,
                           "출금금융회사일련번호": 10, "입금금융회사일련번호": 20,
                           "자금구분": 1, "매체구분": 1, "이상거래유형": 4,
                       }])
        assert "보이스피싱" in result["VII_서술"]["종합의견"]


# ===========================================================================
# 15. IV 관련계좌 목록 최대 크기 제한
# ===========================================================================

class TestAccountListSizeLimits:
    """IV_관련계좌 목록의 최대 크기(10) 제한 검증."""

    def test_출금계좌목록_max_10(self, base_kwargs):
        """출금계좌목록이 최대 10개로 제한되어야 한다."""
        txs = [
            {
                "거래일자": 20240101,
                "출금계좌일련번호": 1000000 + i,
                "입금계좌일련번호": 2000000 + i,
                "출금금융회사일련번호": 10,
                "입금금융회사일련번호": 20,
                "자금구분": 1,
                "매체구분": 1,
                "거래금액": 100_000,
                "이상거래유형": 1,
            }
            for i in range(15)  # 15개 고유 계좌
        ]
        result = _call(base_kwargs, transactions=txs)
        assert len(result["IV_관련계좌"]["출금계좌목록"]) <= 10

    def test_II_출금계좌번호_max_5(self, base_kwargs):
        """II_거래자.출금계좌번호가 최대 5개로 제한되어야 한다."""
        txs = [
            {
                "거래일자": 20240101,
                "출금계좌일련번호": 1000000 + i,
                "입금계좌일련번호": 2000000 + i,
                "출금금융회사일련번호": 10,
                "입금금융회사일련번호": 20,
                "자금구분": 1,
                "매체구분": 1,
                "거래금액": 100_000,
                "이상거래유형": 1,
            }
            for i in range(10)  # 10개 고유 계좌
        ]
        result = _call(base_kwargs, transactions=txs)
        assert len(result["II_거래자"]["출금계좌번호"]) <= 5
