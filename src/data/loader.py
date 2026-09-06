"""HOFINET Data Loading and Parquet Conversion Module.

Optimizes loading speed via CSV to Parquet conversion and
supports parallel analysis queries by loading into DuckDB tables.
"""

import time
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

import config


SCHEMA = pa.schema([
    ("date", pa.int32()),
    ("time_slot", pa.int8()),
    ("sender_bank", pa.int16()),
    ("sender_acc", pa.int64()),
    ("receiver_bank", pa.int16()),
    ("receiver_acc", pa.int64()),
    ("fund_type", pa.int8()),
    ("media_type", pa.int8()),
    ("amount", pa.int64()),
    ("is_fraud", pa.int8()),
    ("fraud_type", pa.float32()),
    ("fraud_description", pa.utf8()),
])

# Mapping for the original HOFINET CSV columns (in Korean) to PyArrow types
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
    """Converts CSV to Parquet format for optimized performance.

    - Parallel parsing with PyArrow multi-threaded CSV reader
    - Memory reduction via optimal type casting (int64 → int8/16/32)
    - Minimized disk I/O with Snappy compression

    Returns:
        float: Elapsed time in seconds
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
    # Rename original Korean columns to English schema (HOFINET.csv order)
    table = table.rename_columns([
        "date", "time_slot", "sender_bank", "sender_acc", "receiver_bank",
        "receiver_acc", "fund_type", "media_type", "amount", "is_fraud",
        "fraud_type", "fraud_description"
    ])

    # Cast fraud_type: float32(NaN) -> nullable int8
    col = table.column("fraud_type")
    col_int = pc.cast(col, pa.int8(), safe=False)
    idx = table.schema.get_field_index("fraud_type")
    table = table.set_column(idx, pa.field("fraud_type", pa.int8()), col_int)

    # zstd level 3 keeps the released Parquet well under GitHub's file-size
    # limits (~45 MB vs ~75 MB for snappy) at negligible read cost; PyArrow
    # detects the codec from the file, so the read path is unchanged.
    pq.write_table(
        table,
        str(parquet_path),
        compression="zstd",
        compression_level=3,
        use_dictionary=["fraud_description", "fund_type", "media_type", "time_slot"],
    )
    elapsed = time.time() - start
    return elapsed


def load_parquet(parquet_path=None):
    """Loads a Parquet file into a PyArrow Table."""
    parquet_path = parquet_path or config.PARQUET_PATH
    return pq.read_table(str(parquet_path))


if __name__ == "__main__":
    elapsed = csv_to_parquet(force=True)
    if elapsed > 0:
        parquet_size = config.PARQUET_PATH.stat().st_size / 1024 / 1024
        csv_size = config.CSV_PATH.stat().st_size / 1024 / 1024
        print(f"CSV ({csv_size:.0f}MB) -> Parquet ({parquet_size:.0f}MB)")
        print(f"Compression Ratio: {parquet_size/csv_size*100:.1f}%")
        print(f"Conversion Time: {elapsed:.1f}s")
    else:
        print("Parquet file already exists.")
