"""HOFINET 데이터 로딩 및 Parquet 변환 모듈.

CSV → Parquet 변환으로 로딩 속도를 최적화하고,
DuckDB 테이블로 적재하여 병렬 분석 쿼리를 지원한다.
"""

import time
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

import config


SCHEMA = pa.schema([
    ("거래일자", pa.int32()),
    ("거래시간대", pa.int8()),
    ("출금금융회사일련번호", pa.int16()),
    ("출금계좌일련번호", pa.int64()),
    ("입금금융회사일련번호", pa.int16()),
    ("입금계좌일련번호", pa.int64()),
    ("자금구분", pa.int8()),
    ("매체구분", pa.int8()),
    ("거래금액", pa.int64()),
    ("이상거래여부", pa.int8()),
    ("이상거래유형", pa.float32()),
    ("이상거래설명", pa.utf8()),
])

CONVERT_OPTIONS = pcsv.ConvertOptions(
    column_types={
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
        "이상거래유형": pa.float32(),
        "이상거래설명": pa.utf8(),
    }
)


def csv_to_parquet(csv_path=None, parquet_path=None, force=False):
    """CSV 파일을 Parquet으로 변환한다.

    - PyArrow의 멀티스레드 CSV 리더로 병렬 파싱
    - 최적 타입 캐스팅으로 메모리 절감 (int64 → int8/int16/int32)
    - Snappy 압축으로 디스크 I/O 최소화

    Returns:
        변환 소요 시간(초)
    """
    csv_path = csv_path or config.CSV_PATH
    parquet_path = parquet_path or config.PARQUET_PATH

    if parquet_path.exists() and not force:
        return 0.0

    start = time.time()
    table = pcsv.read_csv(
        str(csv_path),
        convert_options=CONVERT_OPTIONS,
    )
    # 이상거래유형: float32(NaN 포함) → nullable int8로 변환
    col = table.column("이상거래유형")
    col_int = pc.cast(col, pa.int8(), safe=False)
    idx = table.schema.get_field_index("이상거래유형")
    table = table.set_column(idx, pa.field("이상거래유형", pa.int8()), col_int)
    pq.write_table(
        table,
        str(parquet_path),
        compression="snappy",
        use_dictionary=["이상거래설명", "자금구분", "매체구분", "거래시간대"],
    )
    elapsed = time.time() - start
    return elapsed


def load_parquet(parquet_path=None):
    """Parquet 파일을 PyArrow Table로 로드한다."""
    parquet_path = parquet_path or config.PARQUET_PATH
    return pq.read_table(str(parquet_path))


if __name__ == "__main__":
    elapsed = csv_to_parquet(force=True)
    if elapsed > 0:
        parquet_size = config.PARQUET_PATH.stat().st_size / 1024 / 1024
        csv_size = config.CSV_PATH.stat().st_size / 1024 / 1024
        print(f"CSV ({csv_size:.0f}MB) -> Parquet ({parquet_size:.0f}MB)")
        print(f"압축률: {parquet_size/csv_size*100:.1f}%")
        print(f"변환 시간: {elapsed:.1f}초")
    else:
        print("Parquet 파일이 이미 존재합니다.")
