import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date as _date

from src.features.dashboard import (
    get_summary,
    get_monthly_trend,
    get_hourly_distribution,
    get_amount_distribution,
    get_fraud_type_distribution,
    get_medium_distribution,
    get_top_banks,
    get_fund_type_distribution,
    get_fraud_amount_summary,
    get_fraud_amount_by_type,
    get_hourly_fraud_type_heatmap,
    get_fraud_type_monthly_trend,
    get_bank_options,
    get_fraud_type_options,
    get_date_range,
)
from src.ui.chart_utils import (
    BAR_COLOR, LINE_COLOR, ACCENT_COLOR, MINT_COLOR,
    FRAUD_TYPE_COLORS, apply_dark as _apply_dark,
)

# 2열 차트 공통 높이
_H2 = 380
# 전체 너비 차트 공통 높이
_HF = 420

# 매체구분/자금구분 코드 → 한국어 레이블
_MEDIUM_LABELS = {
    1: "창구", 2: "ATM", 3: "PB센터",
    4: "인터넷뱅킹", 5: "전화/휴대전화", 6: "콜센터", 7: "기타",
}
_FUND_LABELS = {0: "해당없음", 1: "입금", 3: "출금", 4: "이체"}


def _int_to_date(d: int) -> _date:
    """YYYYMMDD 정수를 datetime.date로 변환한다."""
    s = str(d)
    return _date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _date_to_int(d: _date) -> int:
    """datetime.date를 YYYYMMDD 정수로 변환한다."""
    return int(d.strftime("%Y%m%d"))


def _format_amount(amount):
    """금액을 읽기 쉬운 한국어 형식으로 포맷한다."""
    amount = float(amount)
    if amount >= 1_0000_0000:
        return f"{amount / 1_0000_0000:,.1f}억"
    elif amount >= 1_0000:
        return f"{amount / 1_0000:,.0f}만"
    else:
        return f"{amount:,.0f}"


def _render_insight(bullets: list) -> None:
    """차트 하단에 AI 분석 인사이트 카드를 렌더링한다."""
    items = "".join(f"<li>{b}</li>" for b in bullets)
    st.markdown(
        f'<div class="ai-insight"><span class="ai-label">🤖 AI 분석</span><ul>{items}</ul></div>',
        unsafe_allow_html=True,
    )


def _metric(col, label, value, sub, white=False):
    """metric-card 단일 렌더링 헬퍼."""
    value_class = "value white" if white else "value"
    with col:
        st.markdown(f"""<div class="metric-card">
            <div class="label">{label}</div>
            <div class="{value_class}">{value}</div>
            <div class="sub">{sub}</div>
        </div>""", unsafe_allow_html=True)


# ------------------------------------------------------------------
# 필터 UI
# ------------------------------------------------------------------

def _render_filters():
    """글로벌 필터 UI를 렌더링하고 필터 딕셔너리를 반환한다."""
    filters = {}

    bank_options = get_bank_options()
    fraud_type_options = get_fraud_type_options()
    min_date_int, max_date_int = get_date_range()
    min_d = _int_to_date(min_date_int)
    max_d = _int_to_date(max_date_int)

    with st.expander("🔍 데이터 필터", expanded=True):
        col_date1, col_date2, col_bank, col_fraud = st.columns([1.5, 1.5, 2, 2])

        with col_date1:
            date_from_d = st.date_input(
                "시작 일자", value=min_d, min_value=min_d, max_value=max_d,
                key="filter_date_from",
            )
            date_from = _date_to_int(date_from_d)

        with col_date2:
            date_to_d = st.date_input(
                "종료 일자", value=max_d, min_value=min_d, max_value=max_d,
                key="filter_date_to",
            )
            date_to = _date_to_int(date_to_d)

        with col_bank:
            selected_banks = st.multiselect(
                "출금 금융회사",
                options=bank_options,
                format_func=lambda x: f"금융회사 {x}",
                key="filter_banks",
            )

        with col_fraud:
            if not fraud_type_options.empty:
                fraud_type_map = {
                    int(row["이상거래유형"]): f"{int(row['이상거래유형'])}. {row['이상거래설명']}"
                    for _, row in fraud_type_options.iterrows()
                }
                selected_fraud_types = st.multiselect(
                    "이상거래 유형",
                    options=list(fraud_type_map.keys()),
                    format_func=lambda x: fraud_type_map.get(x, str(x)),
                    key="filter_fraud_types",
                )
            else:
                selected_fraud_types = []

        if date_from > date_to:
            st.warning("시작 일자가 종료 일자보다 큽니다. 기간 필터를 무시합니다.")
        else:
            if date_from != min_date_int:
                filters["date_from"] = date_from
            if date_to != max_date_int:
                filters["date_to"] = date_to

        if selected_banks:
            filters["banks"] = selected_banks
        if selected_fraud_types:
            filters["fraud_types"] = selected_fraud_types

    return filters if filters else None


# ------------------------------------------------------------------
# 메인 렌더 함수
# ------------------------------------------------------------------

def render():
    st.markdown('<p class="page-title">기본 분석 대시보드</p>', unsafe_allow_html=True)

    filters = _render_filters()

    # ── 요약 지표 카드 (항상 표시) ──
    try:
        summary = get_summary(filters)
        if summary.empty:
            st.info("선택한 조건에 해당하는 데이터가 없습니다.")
            return
        row = summary.iloc[0]
        if row['총거래'] == 0:
            st.info("선택한 조건에 해당하는 데이터가 없습니다.")
            return
    except Exception as e:
        st.error(f"요약 데이터를 불러올 수 없습니다: {e}")
        return

    fraud_ratio = f"{row['이상거래비율']:.2f}%"
    total_txn = int(row['총거래'])
    fraud_txn = int(row['이상거래'])

    st.markdown('<p class="section-header">거래 요약</p>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    _metric(c1, "총 거래 건수",   f"{total_txn:,}",              "2021 Q4 ~ 2024 Q4")
    _metric(c2, "이상거래 건수",   f"{fraud_txn:,}",              f"전체 대비 {fraud_ratio}")
    _metric(c3, "이상거래 비율",   fraud_ratio,                   "이상거래 / 총거래")
    _metric(c4, "출금 계좌 수",    f"{int(row['출금계좌수']):,}",  "고유 계좌 기준")
    _metric(c5, "입금 계좌 수",    f"{int(row['입금계좌수']):,}",  "고유 계좌 기준")

    # ── 이상거래 금액 분석 (항상 표시) ──
    try:
        fraud_amount = get_fraud_amount_summary(filters)
        if not fraud_amount.empty:
            fraud_row = fraud_amount[fraud_amount["이상거래여부"] == 1]
            normal_row = fraud_amount[fraud_amount["이상거래여부"] == 0]

            fraud_total_amount = float(fraud_row.iloc[0]["총금액"])   if not fraud_row.empty  else 0
            fraud_avg_amount   = float(fraud_row.iloc[0]["평균금액"])  if not fraud_row.empty  else 0
            normal_avg_amount  = float(normal_row.iloc[0]["평균금액"]) if not normal_row.empty else 0

            ratio_str = (
                f"{fraud_avg_amount / normal_avg_amount:.1f}배"
                if normal_avg_amount > 0 else "-"
            )

            st.markdown('<p class="section-header">이상거래 금액 분석</p>', unsafe_allow_html=True)
            ac1, ac2, ac3, ac4 = st.columns(4)
            _metric(ac1, "이상거래 총금액",    _format_amount(fraud_total_amount), "이상거래여부=1 합계")
            _metric(ac2, "이상거래 평균금액",  _format_amount(fraud_avg_amount),   "이상거래 건당 평균")
            _metric(ac3, "정상거래 평균금액",  _format_amount(normal_avg_amount),  "정상거래 건당 평균")
            _metric(ac4, "이상/정상 배율",     ratio_str,                          "이상거래 평균 / 정상거래 평균", white=True)
    except Exception:
        pass

    # ── 세부 분석 탭 ──
    tab1, tab2, tab3, tab4 = st.tabs(["📈 추이 분석", "🔍 거래 분석", "⚠️ 이상거래 유형", "🏦 금융회사"])

    # ─────────────────────────────────────────────
    # 탭1: 추이 분석 – 월별 거래 추이
    # ─────────────────────────────────────────────
    with tab1:
        st.markdown('<p class="section-header">월별 거래 추이</p>', unsafe_allow_html=True)
        try:
            monthly = get_monthly_trend(filters)
            if monthly.empty:
                st.info("선택한 조건에 해당하는 월별 데이터가 없습니다.")
            else:
                monthly["연월str"] = monthly["연월"].astype(str).str[:4] + "-" + monthly["연월"].astype(str).str[4:]

                fig_monthly = make_subplots(specs=[[{"secondary_y": True}]])
                fig_monthly.add_trace(
                    go.Bar(x=monthly["연월str"], y=monthly["총거래"], name="총 거래",
                           marker_color=BAR_COLOR, opacity=0.8),
                    secondary_y=False,
                )
                fig_monthly.add_trace(
                    go.Scatter(x=monthly["연월str"], y=monthly["이상거래비율"], name="이상거래 비율(%)",
                               mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                    secondary_y=True,
                )
                _apply_dark(fig_monthly, height=_HF, secondary_y=True)
                fig_monthly.update_yaxes(title_text="거래 건수",       title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                fig_monthly.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                st.plotly_chart(fig_monthly, width='stretch')

                peak_m = monthly.loc[monthly['총거래'].idxmax(), '연월str']
                max_ratio_m = monthly.loc[monthly['이상거래비율'].idxmax()]
                mid = len(monthly) // 2
                trend_dir = "증가" if monthly.iloc[mid:]['이상거래비율'].mean() > monthly.iloc[:mid]['이상거래비율'].mean() else "감소"
                _render_insight([
                    f"거래량 최고 월: {peak_m}",
                    f"이상거래 비율 최고: {max_ratio_m['연월str']} ({max_ratio_m['이상거래비율']:.2f}%)",
                    f"후반기 이상거래 비율 추세: {trend_dir} 방향",
                ])
        except Exception as e:
            st.error(f"월별 추이 데이터를 불러올 수 없습니다: {e}")

    # ─────────────────────────────────────────────
    # 탭2: 거래 분석 – 시간대 / 금액구간 / 매체 / 자금
    # ─────────────────────────────────────────────
    with tab2:
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown('<p class="section-header">시간대별 분포</p>', unsafe_allow_html=True)
            try:
                hourly = get_hourly_distribution(filters)
                if hourly.empty:
                    st.info("선택한 조건에 해당하는 시간대별 데이터가 없습니다.")
                else:
                    hourly["시간대명"] = hourly["거래시간대"].apply(lambda h: f"{h:02d}~{h+3:02d}시")

                    fig_hour = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_hour.add_trace(
                        go.Bar(x=hourly["시간대명"], y=hourly["총거래"], name="총 거래",
                               marker_color=BAR_COLOR, opacity=0.8),
                        secondary_y=False,
                    )
                    fig_hour.add_trace(
                        go.Scatter(x=hourly["시간대명"], y=hourly["이상거래비율"], name="이상거래 비율(%)",
                                   mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                        secondary_y=True,
                    )
                    _apply_dark(fig_hour, height=_H2, secondary_y=True)
                    fig_hour.update_yaxes(title_text="거래 건수",       title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                    fig_hour.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                    st.plotly_chart(fig_hour, width='stretch')

                    peak_h = hourly.loc[hourly['총거래'].idxmax(), '시간대명']
                    max_ratio_h = hourly.loc[hourly['이상거래비율'].idxmax()]
                    min_ratio_h = hourly.loc[hourly['이상거래비율'].idxmin()]
                    _render_insight([
                        f"거래 집중 시간대: {peak_h}",
                        f"이상거래 비율 최고: {max_ratio_h['시간대명']} ({max_ratio_h['이상거래비율']:.2f}%)",
                        f"이상거래 비율 최저: {min_ratio_h['시간대명']} ({min_ratio_h['이상거래비율']:.2f}%)",
                    ])
            except Exception as e:
                st.error(f"시간대별 데이터를 불러올 수 없습니다: {e}")

        with col_right:
            st.markdown('<p class="section-header">거래금액 구간별 분포</p>', unsafe_allow_html=True)
            try:
                amount = get_amount_distribution(filters)
                if amount.empty:
                    st.info("선택한 조건에 해당하는 금액 데이터가 없습니다.")
                else:
                    fig_amt = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_amt.add_trace(
                        go.Bar(x=amount["금액구간"], y=amount["총거래"], name="총 거래",
                               marker_color=BAR_COLOR, opacity=0.8),
                        secondary_y=False,
                    )
                    fig_amt.add_trace(
                        go.Scatter(x=amount["금액구간"], y=amount["이상거래비율"], name="이상거래 비율(%)",
                                   mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                        secondary_y=True,
                    )
                    _apply_dark(fig_amt, height=_H2, secondary_y=True)
                    fig_amt.update_yaxes(title_text="거래 건수",       title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                    fig_amt.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                    st.plotly_chart(fig_amt, width='stretch')

                    peak_a = amount.loc[amount['총거래'].idxmax(), '금액구간']
                    max_ratio_a = amount.loc[amount['이상거래비율'].idxmax()]
                    _render_insight([
                        f"거래 집중 금액 구간: {peak_a}",
                        f"이상거래 비율 최고 구간: {max_ratio_a['금액구간']} ({max_ratio_a['이상거래비율']:.2f}%)",
                    ])
            except Exception as e:
                st.error(f"금액 구간별 데이터를 불러올 수 없습니다: {e}")

        col_left2, col_right2 = st.columns(2)

        with col_left2:
            st.markdown('<p class="section-header">매체구분별 분포</p>', unsafe_allow_html=True)
            try:
                medium = get_medium_distribution(filters)
                if medium.empty:
                    st.info("선택한 조건에 해당하는 매체구분 데이터가 없습니다.")
                else:
                    medium["매체명"] = medium["매체구분"].map(_MEDIUM_LABELS).fillna("매체 " + medium["매체구분"].astype(str))

                    fig_med = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_med.add_trace(
                        go.Bar(x=medium["매체명"], y=medium["총거래"], name="총 거래",
                               marker_color=BAR_COLOR, opacity=0.8),
                        secondary_y=False,
                    )
                    fig_med.add_trace(
                        go.Scatter(x=medium["매체명"], y=medium["이상거래비율"], name="이상거래 비율(%)",
                                   mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                        secondary_y=True,
                    )
                    _apply_dark(fig_med, height=_H2, secondary_y=True)
                    fig_med.update_yaxes(title_text="거래 건수",       title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                    fig_med.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                    st.plotly_chart(fig_med, width='stretch')

                    peak_med = medium.loc[medium['총거래'].idxmax(), '매체명']
                    max_ratio_med = medium.loc[medium['이상거래비율'].idxmax()]
                    _render_insight([
                        f"거래 집중 매체: {peak_med}",
                        f"이상거래 비율 최고 매체: {max_ratio_med['매체명']} ({max_ratio_med['이상거래비율']:.2f}%)",
                    ])
            except Exception as e:
                st.error(f"매체구분 데이터를 불러올 수 없습니다: {e}")

        with col_right2:
            st.markdown('<p class="section-header">자금구분별 분포</p>', unsafe_allow_html=True)
            try:
                fund_type = get_fund_type_distribution(filters)
                if fund_type.empty:
                    st.info("선택한 조건에 해당하는 자금구분 데이터가 없습니다.")
                else:
                    fund_type["자금명"] = fund_type["자금구분"].map(_FUND_LABELS).fillna("자금 " + fund_type["자금구분"].astype(str))

                    fig_fund = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_fund.add_trace(
                        go.Bar(x=fund_type["자금명"], y=fund_type["총거래"], name="총 거래",
                               marker_color=BAR_COLOR, opacity=0.8),
                        secondary_y=False,
                    )
                    fig_fund.add_trace(
                        go.Scatter(x=fund_type["자금명"], y=fund_type["이상거래비율"],
                                   name="이상거래 비율(%)",
                                   mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                        secondary_y=True,
                    )
                    _apply_dark(fig_fund, height=_H2, secondary_y=True)
                    fig_fund.update_yaxes(title_text="거래 건수",       title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                    fig_fund.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                    st.plotly_chart(fig_fund, width='stretch')

                    peak_fund = fund_type.loc[fund_type['총거래'].idxmax(), '자금명']
                    max_ratio_fund = fund_type.loc[fund_type['이상거래비율'].idxmax()]
                    _render_insight([
                        f"거래 집중 자금구분: {peak_fund}",
                        f"이상거래 비율 최고 자금구분: {max_ratio_fund['자금명']} ({max_ratio_fund['이상거래비율']:.2f}%)",
                    ])
            except Exception as e:
                st.error(f"자금구분 데이터를 불러올 수 없습니다: {e}")

    # ─────────────────────────────────────────────
    # 탭3: 이상거래 유형 – 분포 / 금액 / 히트맵 / 월별추이
    # ─────────────────────────────────────────────
    with tab3:
        col_left3, col_right3 = st.columns(2)

        with col_left3:
            st.markdown('<p class="section-header">이상거래 유형별 분포</p>', unsafe_allow_html=True)
            try:
                fraud_type = get_fraud_type_distribution(filters)
                if fraud_type.empty:
                    st.info("선택한 조건에 해당하는 이상거래 유형 데이터가 없습니다.")
                else:
                    fraud_type["레이블"] = fraud_type["이상거래유형"].astype(int).astype(str) + ". " + fraud_type["이상거래설명"].fillna("")

                    fig_fraud = px.pie(
                        fraud_type, values="건수", names="레이블",
                        color_discrete_sequence=FRAUD_TYPE_COLORS,
                        hole=0.45,
                    )
                    _apply_dark(fig_fraud, height=_H2)
                    fig_fraud.update_layout(
                        legend=dict(font=dict(color="#8B8FA3", size=10), bgcolor="rgba(0,0,0,0)"),
                        margin=dict(t=20, b=20, l=10, r=10),
                    )
                    fig_fraud.update_traces(textposition="outside", textinfo="label+percent",
                                            textfont=dict(color="#C0C4D0", size=10))
                    st.plotly_chart(fig_fraud, width='stretch')

                    total_ft = fraud_type['건수'].sum()
                    top1_ft = fraud_type.loc[fraud_type['건수'].idxmax()]
                    top1_ft_pct = top1_ft['건수'] / total_ft * 100
                    _render_insight([
                        f"최다 발생 유형: {int(top1_ft['이상거래유형'])}. {top1_ft['이상거래설명']} ({top1_ft_pct:.1f}%)",
                        f"탐지된 이상거래 유형 수: {len(fraud_type)}종",
                    ])
            except Exception as e:
                st.error(f"이상거래 유형 데이터를 불러올 수 없습니다: {e}")

        with col_right3:
            st.markdown('<p class="section-header">이상거래 유형별 금액</p>', unsafe_allow_html=True)
            try:
                fraud_by_type = get_fraud_amount_by_type(filters)
                if fraud_by_type.empty:
                    st.info("선택한 조건에 해당하는 유형별 금액 데이터가 없습니다.")
                else:
                    fraud_by_type["레이블"] = (
                        fraud_by_type["이상거래유형"].astype(int).astype(str) + ". "
                        + fraud_by_type["이상거래설명"].fillna("")
                    )
                    fig_fraud_amt = go.Figure(go.Bar(
                        y=fraud_by_type["레이블"],
                        x=fraud_by_type["총금액"],
                        orientation="h",
                        marker_color=ACCENT_COLOR,
                        text=fraud_by_type["총금액"].apply(_format_amount),
                        textposition="auto",
                        textfont=dict(color="#E0E0E0", size=11),
                    ))
                    _apply_dark(fig_fraud_amt, height=_H2)
                    fig_fraud_amt.update_xaxes(title_text="총 거래금액", title_font=dict(color="#8B8FA3", size=11))
                    fig_fraud_amt.update_yaxes(title_text="", autorange="reversed")
                    st.plotly_chart(fig_fraud_amt, width='stretch')

                    top_amt_row = fraud_by_type.loc[fraud_by_type['총금액'].idxmax()]
                    _render_insight([
                        f"최다 금액 유형: {int(top_amt_row['이상거래유형'])}. {top_amt_row['이상거래설명']} ({_format_amount(float(top_amt_row['총금액']))})",
                    ])
            except Exception as e:
                st.error(f"유형별 금액 데이터를 불러올 수 없습니다: {e}")

        st.markdown('<p class="section-header">시간대 × 이상거래유형 교차 분석</p>', unsafe_allow_html=True)
        try:
            heatmap_data = get_hourly_fraud_type_heatmap(filters)
            if heatmap_data.empty:
                st.info("선택한 조건에 해당하는 히트맵 데이터가 없습니다.")
            else:
                pivot = heatmap_data.pivot_table(
                    index="이상거래유형", columns="거래시간대", values="건수", fill_value=0
                )
                try:
                    type_desc = get_fraud_type_distribution(filters)
                    type_map = {
                        int(r["이상거래유형"]): f"{int(r['이상거래유형'])}. {r['이상거래설명']}"
                        for _, r in type_desc.iterrows()
                    }
                except Exception:
                    type_map = {}

                y_labels = [type_map.get(int(t), f"유형 {int(t)}") for t in pivot.index]
                x_labels = [f"{int(h):02d}~{int(h)+3:02d}시" for h in pivot.columns]

                fig_heatmap = go.Figure(go.Heatmap(
                    z=pivot.values,
                    x=x_labels,
                    y=y_labels,
                    colorscale=[[0, "#1A1F2E"], [0.5, "#2A6B65"], [1, "#4ECDC4"]],
                    hovertemplate="시간대: %{x}<br>유형: %{y}<br>건수: %{z}<extra></extra>",
                    texttemplate="%{z}",
                    textfont=dict(color="#E0E0E0", size=11),
                ))
                _apply_dark(fig_heatmap, height=360)
                fig_heatmap.update_layout(
                    xaxis_title="거래 시간대",
                    yaxis_title="이상거래 유형",
                    xaxis=dict(title_font=dict(color="#8B8FA3", size=11)),
                    yaxis=dict(title_font=dict(color="#8B8FA3", size=11)),
                )
                st.plotly_chart(fig_heatmap, width='stretch')

                peak_hm = heatmap_data.loc[heatmap_data['건수'].idxmax()]
                peak_hm_type = type_map.get(int(peak_hm['이상거래유형']), f"유형 {int(peak_hm['이상거래유형'])}")
                peak_hm_hour = f"{int(peak_hm['거래시간대']):02d}~{int(peak_hm['거래시간대'])+3:02d}시"
                top_types = heatmap_data.groupby('이상거래유형')['건수'].sum().nlargest(1)
                top_type_label = type_map.get(int(top_types.index[0]), f"유형 {int(top_types.index[0])}")
                _render_insight([
                    f"이상거래 집중 조합: {peak_hm_type} × {peak_hm_hour} ({int(peak_hm['건수']):,}건)",
                    f"시간대 전체 합산 최다 유형: {top_type_label}",
                ])
        except Exception as e:
            st.error(f"히트맵 데이터를 불러올 수 없습니다: {e}")

        st.markdown('<p class="section-header">이상거래 유형별 월별 추이</p>', unsafe_allow_html=True)
        try:
            trend_data = get_fraud_type_monthly_trend(filters)
            if trend_data.empty:
                st.info("선택한 조건에 해당하는 월별 추이 데이터가 없습니다.")
            else:
                trend_data["연월str"] = (
                    trend_data["연월"].astype(str).str[:4] + "-"
                    + trend_data["연월"].astype(str).str[4:]
                )
                trend_data["레이블"] = (
                    trend_data["이상거래유형"].astype(int).astype(str) + ". "
                    + trend_data["이상거래설명"].fillna("")
                )

                fig_trend = go.Figure()
                for i, label in enumerate(trend_data["레이블"].unique()):
                    subset = trend_data[trend_data["레이블"] == label]
                    color = FRAUD_TYPE_COLORS[i % len(FRAUD_TYPE_COLORS)]
                    fig_trend.add_trace(go.Scatter(
                        x=subset["연월str"],
                        y=subset["건수"],
                        name=label,
                        mode="lines+markers",
                        line=dict(width=2, color=color),
                        marker=dict(size=6, color=color),
                    ))

                _apply_dark(fig_trend, height=_HF)
                fig_trend.update_layout(
                    legend=dict(
                        orientation="h", y=1.15,
                        font=dict(color="#8B8FA3", size=10),
                        bgcolor="rgba(0,0,0,0)",
                    ),
                )
                fig_trend.update_xaxes(title_text="연월",          title_font=dict(color="#8B8FA3", size=11))
                fig_trend.update_yaxes(title_text="이상거래 건수", title_font=dict(color="#8B8FA3", size=11))
                st.plotly_chart(fig_trend, width='stretch')

                type_growths = {}
                for lbl in trend_data['레이블'].unique():
                    subset = trend_data[trend_data['레이블'] == lbl].sort_values('연월str')
                    if len(subset) >= 2:
                        type_growths[lbl] = int(subset.iloc[-1]['건수']) - int(subset.iloc[0]['건수'])
                if type_growths:
                    growing   = max(type_growths, key=type_growths.get)
                    declining = min(type_growths, key=type_growths.get)
                    _render_insight([
                        f"증가 추세 유형: {growing} (+{type_growths[growing]:,}건)",
                        f"감소 추세 유형: {declining} ({type_growths[declining]:,}건)",
                    ])
        except Exception as e:
            st.error(f"유형별 월별 추이 데이터를 불러올 수 없습니다: {e}")

    # ─────────────────────────────────────────────
    # 탭4: 금융회사 – 출금/입금 상위 20
    # ─────────────────────────────────────────────
    with tab4:
        st.markdown('<p class="section-header">금융회사별 이상거래 현황 (상위 20)</p>', unsafe_allow_html=True)
        try:
            banks = get_top_banks(filters)
            if banks.empty:
                st.info("선택한 조건에 해당하는 금융회사 데이터가 없습니다.")
            else:
                tab_out, tab_in = st.tabs(["출금 금융회사", "입금 금융회사"])

                with tab_out:
                    banks_out = banks[banks["구분"] == "출금"].sort_values("이상거래", ascending=False).head(20)
                    if banks_out.empty:
                        st.info("출금 금융회사 이상거래 데이터가 없습니다.")
                    else:
                        banks_out["금융회사명"] = banks_out["금융회사"].astype(str)
                        fig_bank_out = make_subplots(specs=[[{"secondary_y": True}]])
                        fig_bank_out.add_trace(
                            go.Bar(x=banks_out["금융회사명"], y=banks_out["이상거래"], name="이상거래 건수",
                                   marker_color=ACCENT_COLOR),
                            secondary_y=False,
                        )
                        fig_bank_out.add_trace(
                            go.Scatter(x=banks_out["금융회사명"], y=banks_out["이상거래비율"], name="이상거래 비율(%)",
                                       mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                            secondary_y=True,
                        )
                        _apply_dark(fig_bank_out, height=_H2, secondary_y=True)
                        fig_bank_out.update_xaxes(title_text="금융회사 코드",    title_font=dict(color="#8B8FA3", size=11))
                        fig_bank_out.update_yaxes(title_text="이상거래 건수",    title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                        fig_bank_out.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                        st.plotly_chart(fig_bank_out, width='stretch')
                        top_out = banks_out.iloc[0]
                        _render_insight([
                            f"이상거래 최다 출금 금융회사: {int(top_out['금융회사'])}번 ({int(top_out['이상거래']):,}건, 비율 {top_out['이상거래비율']:.2f}%)",
                        ])

                with tab_in:
                    banks_in = banks[banks["구분"] == "입금"].sort_values("이상거래", ascending=False).head(20)
                    if banks_in.empty:
                        st.info("입금 금융회사 이상거래 데이터가 없습니다.")
                    else:
                        banks_in["금융회사명"] = banks_in["금융회사"].astype(str)
                        fig_bank_in = make_subplots(specs=[[{"secondary_y": True}]])
                        fig_bank_in.add_trace(
                            go.Bar(x=banks_in["금융회사명"], y=banks_in["이상거래"], name="이상거래 건수",
                                   marker_color=ACCENT_COLOR),
                            secondary_y=False,
                        )
                        fig_bank_in.add_trace(
                            go.Scatter(x=banks_in["금융회사명"], y=banks_in["이상거래비율"], name="이상거래 비율(%)",
                                       mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                            secondary_y=True,
                        )
                        _apply_dark(fig_bank_in, height=_H2, secondary_y=True)
                        fig_bank_in.update_xaxes(title_text="금융회사 코드",    title_font=dict(color="#8B8FA3", size=11))
                        fig_bank_in.update_yaxes(title_text="이상거래 건수",    title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                        fig_bank_in.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                        st.plotly_chart(fig_bank_in, width='stretch')
                        top_in = banks_in.iloc[0]
                        _render_insight([
                            f"이상거래 최다 입금 금융회사: {int(top_in['금융회사'])}번 ({int(top_in['이상거래']):,}건, 비율 {top_in['이상거래비율']:.2f}%)",
                        ])
        except Exception as e:
            st.error(f"금융회사 데이터를 불러올 수 없습니다: {e}")
