"""src/data/loader.py 기능 테스트.

검증 항목:
- Parquet 스키마가 기대하는 컬럼과 타입을 갖는지
- 데이터 로딩 후 행 수, 컬럼 수가 올바른지
- 이상거래여부 라벨 값이 0/1만 존재하는지
- 거래금액이 양수인지
- 이상거래유형/이상거래설명의 null 패턴이 올바른지
"""

import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc
from unittest.mock import MagicMock

import config
from src.data import loader
from src.data.loader import SCHEMA, load_parquet


class TestParquetSchema:
    """Parquet 파일 스키마 검증."""

    def test_parquet_file_readable(self):
        """Parquet 파일을 읽을 수 있는지 확인."""
        table = load_parquet()
        assert table is not None
        assert len(table) > 0

    def test_column_count(self):
        """컬럼 수가 12개인지 확인."""
        table = load_parquet()
        assert table.num_columns == 12

    def test_expected_column_names(self):
        """기대하는 12개 컬럼 이름이 모두 존재하는지 확인."""
        expected_columns = [
            "거래일자", "거래시간대",
            "출금금융회사일련번호", "출금계좌일련번호",
            "입금금융회사일련번호", "입금계좌일련번호",
            "자금구분", "매체구분", "거래금액",
            "이상거래여부", "이상거래유형", "이상거래설명",
        ]
        table = load_parquet()
        actual_columns = table.column_names
        for col in expected_columns:
            assert col in actual_columns, f"컬럼 '{col}'이 없습니다"

    def test_schema_types_match(self):
        """주요 컬럼의 데이터 타입이 기대값과 일치하는지 확인."""
        table = load_parquet()
        schema = table.schema
        # 기대 타입 매핑 (loader에서 이상거래유형을 int8로 변환함)
        expected_types = {
            "거래일자": pa.int32(),
            "거래시간대": pa.int8(),
            "출금금융회사일련번호": pa.int16(),
            "출금계좌일련번호": pa.int64(),
            "입금금융회사일련번호": pa.int16(),
            "입금계좌일련번호": pa.int64(),
            "자금구분": pa.int8(),
            "매체구분": pa.int8(),
            "거래금액": pa.int64(),
            "이상거래여부": pa.int8(),
            "이상거래유형": pa.int8(),
            "이상거래설명": pa.utf8(),
        }
        for col_name, expected_type in expected_types.items():
            actual_type = schema.field(col_name).type
            assert actual_type == expected_type, (
                f"'{col_name}': 기대 {expected_type}, 실제 {actual_type}"
            )

    def test_schema_definition_has_12_fields(self):
        """SCHEMA 상수가 12개 필드를 정의하는지 확인."""
        assert len(SCHEMA) == 12


class TestDataIntegrity:
    """데이터 무결성 검증."""

    def test_row_count(self):
        """전체 행 수가 4,732,130건인지 확인."""
        table = load_parquet()
        assert table.num_rows == 4_732_130

    def test_label_values_binary(self):
        """이상거래여부가 0 또는 1만 포함하는지 확인."""
        table = load_parquet()
        col = table.column("이상거래여부")
        unique = pc.unique(col).to_pylist()
        assert set(unique) == {0, 1}, f"이상거래여부 값: {unique}"

    def test_transaction_amount_positive(self):
        """거래금액이 모두 양수인지 확인."""
        table = load_parquet()
        col = table.column("거래금액")
        min_val = pc.min(col).as_py()
        assert min_val > 0, f"최소 거래금액: {min_val}"

    def test_fraud_ratio(self):
        """이상거래 비율이 약 0.31% (0.2%~0.5% 범위)인지 확인."""
        table = load_parquet()
        col = table.column("이상거래여부")
        fraud_count = pc.sum(col).as_py()
        total = table.num_rows
        ratio = fraud_count / total
        assert 0.002 < ratio < 0.005, f"이상거래 비율: {ratio:.4f}"

    def test_null_pattern_normal_transactions(self):
        """정상거래(이상거래여부=0)의 이상거래유형/이상거래설명이 null인지 확인 (샘플)."""
        table = load_parquet()
        # 정상거래 중 이상거래유형이 null이 아닌 건수가 0이어야 함
        label_col = table.column("이상거래여부")
        type_col = table.column("이상거래유형")
        # 정상거래 마스크
        normal_mask = pc.equal(label_col, 0)
        normal_types = pc.filter(type_col, normal_mask)
        # null이 아닌 것의 수
        non_null_count = pc.sum(pc.is_valid(normal_types)).as_py()
        assert non_null_count == 0, f"정상거래 중 이상거래유형 non-null: {non_null_count}건"

    def test_fraud_transactions_have_type(self):
        """이상거래(이상거래여부=1)의 이상거래유형이 모두 채워져 있는지 확인."""
        table = load_parquet()
        label_col = table.column("이상거래여부")
        type_col = table.column("이상거래유형")
        fraud_mask = pc.equal(label_col, 1)
        fraud_types = pc.filter(type_col, fraud_mask)
        null_count = pc.sum(pc.is_null(fraud_types)).as_py()
        assert null_count == 0, f"이상거래 중 유형 null: {null_count}건"

    def test_time_slot_values(self):
        """거래시간대가 유효한 3시간 단위 슬롯인지 확인."""
        table = load_parquet()
        col = table.column("거래시간대")
        unique = set(pc.unique(col).to_pylist())
        valid_slots = {0, 3, 6, 9, 12, 15, 18, 21}
        assert unique.issubset(valid_slots), f"유효하지 않은 시간대: {unique - valid_slots}"

    def test_transaction_date_range(self):
        """거래일자가 2021~2024 범위 내인지 확인."""
        table = load_parquet()
        col = table.column("거래일자")
        min_date = pc.min(col).as_py()
        max_date = pc.max(col).as_py()
        assert min_date >= 20210101, f"최소 거래일자: {min_date}"
        assert max_date <= 20241231, f"최대 거래일자: {max_date}"


class TestCsvToParquetBranches:
    """csv_to_parquet/load_parquet 분기 테스트."""

    def test_csv_to_parquet_returns_zero_when_parquet_exists(self, tmp_path):
        """force=False이고 parquet 파일이 이미 존재하면 0.0을 반환해야 한다."""
        csv_path = tmp_path / "sample.csv"
        parquet_path = tmp_path / "sample.parquet"
        csv_path.write_text("dummy\n", encoding="utf-8")
        parquet_path.write_text("already", encoding="utf-8")

        elapsed = loader.csv_to_parquet(csv_path=csv_path, parquet_path=parquet_path, force=False)

        assert elapsed == 0.0

    def test_csv_to_parquet_force_writes_int8_fraud_type(self, monkeypatch, tmp_path):
        """force=True일 때 변환이 수행되고 이상거래유형이 int8로 기록되어야 한다."""
        csv_path = tmp_path / "input.csv"
        parquet_path = tmp_path / "out.parquet"
        csv_path.write_text("dummy\n", encoding="utf-8")

        table = pa.table({
            "이상거래유형": pa.array([1.0, None], type=pa.float32()),
        })
        write_mock = MagicMock()

        monkeypatch.setattr(loader.pcsv, "read_csv", lambda *_args, **_kwargs: table)
        monkeypatch.setattr(loader.pq, "write_table", write_mock)
        monkeypatch.setattr(loader.time, "time", MagicMock(side_effect=[100.0, 102.5]))

        elapsed = loader.csv_to_parquet(csv_path=csv_path, parquet_path=parquet_path, force=True)

        assert elapsed == 2.5
        assert write_mock.call_count == 1
        written_table = write_mock.call_args.args[0]
        assert written_table.schema.field("이상거래유형").type == pa.int8()
        assert write_mock.call_args.kwargs["compression"] == "snappy"

    def test_load_parquet_reads_from_given_path(self, monkeypatch, tmp_path):
        """load_parquet는 전달된 경로 문자열을 read_table에 넘겨야 한다."""
        parquet_path = tmp_path / "custom.parquet"
        read_mock = MagicMock(return_value="TABLE")
        monkeypatch.setattr(loader.pq, "read_table", read_mock)

        result = loader.load_parquet(parquet_path=parquet_path)

        assert result == "TABLE"
        read_mock.assert_called_once_with(str(parquet_path))
