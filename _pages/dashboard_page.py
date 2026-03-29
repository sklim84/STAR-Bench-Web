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
    1: "Counter", 2: "ATM", 3: "PB Center",
    4: "Internet Banking", 5: "Phone/Mobile", 6: "Call Center", 7: "Other",
}
_FUND_LABELS = {0: "N/A", 1: "Deposit", 3: "Withdrawal", 4: "Transfer"}


def _int_to_date(d: int) -> _date:
    """YYYYMMDD 정수를 datetime.date로 변환한다."""
    s = str(d)
    return _date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _date_to_int(d: _date) -> int:
    """datetime.date를 YYYYMMDD 정수로 변환한다."""
    return int(d.strftime("%Y%m%d"))


def _format_amount(amount):
    """Format amount into a human-readable string."""
    amount = float(amount)
    if amount >= 1_000_000_000:
        return f"{amount / 1_000_000_000:,.1f}B"
    elif amount >= 1_000_000:
        return f"{amount / 1_000_000:,.1f}M"
    elif amount >= 1_000:
        return f"{amount / 1_000:,.0f}K"
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

    with st.expander("🔍 Data Filters", expanded=True):
        col_date1, col_date2, col_bank, col_fraud = st.columns([1.5, 1.5, 2, 2])

        with col_date1:
            date_from_d = st.date_input(
                "Start Date", value=min_d, min_value=min_d, max_value=max_d,
                key="filter_date_from",
            )
            date_from = _date_to_int(date_from_d)

        with col_date2:
            date_to_d = st.date_input(
                "End Date", value=max_d, min_value=min_d, max_value=max_d,
                key="filter_date_to",
            )
            date_to = _date_to_int(date_to_d)

        with col_bank:
            selected_banks = st.multiselect(
                "Sender Institution",
                options=bank_options,
                format_func=lambda x: f"Institution {x}",
                key="filter_banks",
            )

        with col_fraud:
            if not fraud_type_options.empty:
                fraud_type_map = {
                    int(row["이상거래유형"]): f"{int(row['이상거래유형'])}. {row['이상거래설명']}"
                    for _, row in fraud_type_options.iterrows()
                }
                selected_fraud_types = st.multiselect(
                    "Fraud Type",
                    options=list(fraud_type_map.keys()),
                    format_func=lambda x: fraud_type_map.get(x, str(x)),
                    key="filter_fraud_types",
                )
            else:
                selected_fraud_types = []

        if date_from > date_to:
            st.warning("Start date is later than end date. Ignoring date filter.")
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
    st.markdown('<p class="page-title">Analytics Dashboard</p>', unsafe_allow_html=True)

    filters = _render_filters()

    # ── Summary metric cards (always shown) ──
    try:
        summary = get_summary(filters)
        if summary.empty:
            st.info("No data found for the selected criteria.")
            return
        row = summary.iloc[0]
        if row['총거래'] == 0:
            st.info("No data found for the selected criteria.")
            return
    except Exception as e:
        st.error(f"Unable to load summary data: {e}")
        return

    fraud_ratio = f"{row['이상거래비율']:.2f}%"
    total_txn = int(row['총거래'])
    fraud_txn = int(row['이상거래'])

    st.markdown('<p class="section-header">Transaction Summary</p>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    _metric(c1, "Total Transactions",   f"{total_txn:,}",              "2021 Q4 ~ 2024 Q4")
    _metric(c2, "Fraud Transactions",   f"{fraud_txn:,}",              f"{fraud_ratio} of total")
    _metric(c3, "Fraud Ratio",          fraud_ratio,                   "Fraud / Total")
    _metric(c4, "Sender Accounts",      f"{int(row['출금계좌수']):,}",  "Unique accounts")
    _metric(c5, "Receiver Accounts",    f"{int(row['입금계좌수']):,}",  "Unique accounts")

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

            st.markdown('<p class="section-header">Fraud Amount Analysis</p>', unsafe_allow_html=True)
            ac1, ac2, ac3, ac4 = st.columns(4)
            _metric(ac1, "Total Fraud Amount",    _format_amount(fraud_total_amount), "Sum of fraud=1")
            _metric(ac2, "Avg Fraud Amount",      _format_amount(fraud_avg_amount),   "Per fraud transaction")
            _metric(ac3, "Avg Normal Amount",     _format_amount(normal_avg_amount),  "Per normal transaction")
            _metric(ac4, "Fraud/Normal Ratio",    ratio_str,                          "Fraud avg / Normal avg", white=True)
    except Exception:
        pass

    # ── 세부 분석 탭 (선택된 탭만 쿼리 실행하여 지연 로딩) ──
    tab_names = ["📈 Trend Analysis", "🔍 Transaction Analysis", "⚠️ Fraud Types", "🏦 Financial Institutions"]
    selected_tab = st.radio(
        "Detailed Analysis",
        tab_names,
        horizontal=True,
        key="dashboard_tab",
        label_visibility="collapsed",
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # ─────────────────────────────────────────────
    # 탭1: 추이 분석 – 월별 거래 추이
    # ─────────────────────────────────────────────
    if selected_tab == tab_names[0]:
        st.markdown('<p class="section-header">Monthly Transaction Trend</p>', unsafe_allow_html=True)
        try:
            monthly = get_monthly_trend(filters)
            if monthly.empty:
                st.info("No monthly data found for the selected criteria.")
            else:
                monthly["연월str"] = monthly["연월"].astype(str).str[:4] + "-" + monthly["연월"].astype(str).str[4:]

                fig_monthly = make_subplots(specs=[[{"secondary_y": True}]])
                fig_monthly.add_trace(
                    go.Bar(x=monthly["연월str"], y=monthly["총거래"], name="Total Transactions",
                           marker_color=BAR_COLOR, opacity=0.8),
                    secondary_y=False,
                )
                fig_monthly.add_trace(
                    go.Scatter(x=monthly["연월str"], y=monthly["이상거래비율"], name="Fraud Ratio (%)",
                               mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                    secondary_y=True,
                )
                _apply_dark(fig_monthly, height=_HF, secondary_y=True)
                fig_monthly.update_yaxes(title_text="Transaction Count",  title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                fig_monthly.update_yaxes(title_text="Fraud Ratio (%)",    title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                st.plotly_chart(fig_monthly, width='stretch')

                peak_m = monthly.loc[monthly['총거래'].idxmax(), '연월str']
                max_ratio_m = monthly.loc[monthly['이상거래비율'].idxmax()]
                mid = len(monthly) // 2
                trend_dir = "increasing" if monthly.iloc[mid:]['이상거래비율'].mean() > monthly.iloc[:mid]['이상거래비율'].mean() else "decreasing"
                _render_insight([
                    f"Peak transaction month: {peak_m}",
                    f"Highest fraud ratio: {max_ratio_m['연월str']} ({max_ratio_m['이상거래비율']:.2f}%)",
                    f"Second-half fraud ratio trend: {trend_dir}",
                ])
        except Exception as e:
            st.error(f"Unable to load monthly trend data: {e}")

    # ─────────────────────────────────────────────
    # 탭2: 거래 분석 – 시간대 / 금액구간 / 매체 / 자금
    # ─────────────────────────────────────────────
    elif selected_tab == tab_names[1]:
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown('<p class="section-header">Hourly Distribution</p>', unsafe_allow_html=True)
            try:
                hourly = get_hourly_distribution(filters)
                if hourly.empty:
                    st.info("No hourly data found for the selected criteria.")
                else:
                    hourly["시간대명"] = hourly["거래시간대"].apply(lambda h: f"{h:02d}~{h+3:02d}시")

                    fig_hour = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_hour.add_trace(
                        go.Bar(x=hourly["시간대명"], y=hourly["총거래"], name="Total Transactions",
                               marker_color=BAR_COLOR, opacity=0.8),
                        secondary_y=False,
                    )
                    fig_hour.add_trace(
                        go.Scatter(x=hourly["시간대명"], y=hourly["이상거래비율"], name="Fraud Ratio (%)",
                                   mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                        secondary_y=True,
                    )
                    _apply_dark(fig_hour, height=_H2, secondary_y=True)
                    fig_hour.update_yaxes(title_text="Transaction Count",  title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                    fig_hour.update_yaxes(title_text="Fraud Ratio (%)",    title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                    st.plotly_chart(fig_hour, width='stretch')

                    peak_h = hourly.loc[hourly['총거래'].idxmax(), '시간대명']
                    max_ratio_h = hourly.loc[hourly['이상거래비율'].idxmax()]
                    min_ratio_h = hourly.loc[hourly['이상거래비율'].idxmin()]
                    _render_insight([
                        f"Peak transaction hours: {peak_h}",
                        f"Highest fraud ratio: {max_ratio_h['시간대명']} ({max_ratio_h['이상거래비율']:.2f}%)",
                        f"Lowest fraud ratio: {min_ratio_h['시간대명']} ({min_ratio_h['이상거래비율']:.2f}%)",
                    ])
            except Exception as e:
                st.error(f"Unable to load hourly data: {e}")

        with col_right:
            st.markdown('<p class="section-header">Amount Range Distribution</p>', unsafe_allow_html=True)
            try:
                amount = get_amount_distribution(filters)
                if amount.empty:
                    st.info("No amount data found for the selected criteria.")
                else:
                    fig_amt = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_amt.add_trace(
                        go.Bar(x=amount["금액구간"], y=amount["총거래"], name="Total Transactions",
                               marker_color=BAR_COLOR, opacity=0.8),
                        secondary_y=False,
                    )
                    fig_amt.add_trace(
                        go.Scatter(x=amount["금액구간"], y=amount["이상거래비율"], name="Fraud Ratio (%)",
                                   mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                        secondary_y=True,
                    )
                    _apply_dark(fig_amt, height=_H2, secondary_y=True)
                    fig_amt.update_yaxes(title_text="Transaction Count",  title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                    fig_amt.update_yaxes(title_text="Fraud Ratio (%)",    title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                    st.plotly_chart(fig_amt, width='stretch')

                    peak_a = amount.loc[amount['총거래'].idxmax(), '금액구간']
                    max_ratio_a = amount.loc[amount['이상거래비율'].idxmax()]
                    _render_insight([
                        f"Peak amount range: {peak_a}",
                        f"Highest fraud ratio range: {max_ratio_a['금액구간']} ({max_ratio_a['이상거래비율']:.2f}%)",
                    ])
            except Exception as e:
                st.error(f"Unable to load amount range data: {e}")

        col_left2, col_right2 = st.columns(2)

        with col_left2:
            st.markdown('<p class="section-header">Channel Distribution</p>', unsafe_allow_html=True)
            try:
                medium = get_medium_distribution(filters)
                if medium.empty:
                    st.info("No channel data found for the selected criteria.")
                else:
                    medium["매체명"] = medium["매체구분"].map(_MEDIUM_LABELS).fillna("Channel " + medium["매체구분"].astype(str))

                    fig_med = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_med.add_trace(
                        go.Bar(x=medium["매체명"], y=medium["총거래"], name="Total Transactions",
                               marker_color=BAR_COLOR, opacity=0.8),
                        secondary_y=False,
                    )
                    fig_med.add_trace(
                        go.Scatter(x=medium["매체명"], y=medium["이상거래비율"], name="Fraud Ratio (%)",
                                   mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                        secondary_y=True,
                    )
                    _apply_dark(fig_med, height=_H2, secondary_y=True)
                    fig_med.update_yaxes(title_text="Transaction Count",  title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                    fig_med.update_yaxes(title_text="Fraud Ratio (%)",    title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                    st.plotly_chart(fig_med, width='stretch')

                    peak_med = medium.loc[medium['총거래'].idxmax(), '매체명']
                    max_ratio_med = medium.loc[medium['이상거래비율'].idxmax()]
                    _render_insight([
                        f"Peak transaction channel: {peak_med}",
                        f"Highest fraud ratio channel: {max_ratio_med['매체명']} ({max_ratio_med['이상거래비율']:.2f}%)",
                    ])
            except Exception as e:
                st.error(f"Unable to load channel data: {e}")

        with col_right2:
            st.markdown('<p class="section-header">Fund Type Distribution</p>', unsafe_allow_html=True)
            try:
                fund_type = get_fund_type_distribution(filters)
                if fund_type.empty:
                    st.info("No fund type data found for the selected criteria.")
                else:
                    fund_type["자금명"] = fund_type["자금구분"].map(_FUND_LABELS).fillna("Fund " + fund_type["자금구분"].astype(str))

                    fig_fund = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_fund.add_trace(
                        go.Bar(x=fund_type["자금명"], y=fund_type["총거래"], name="Total Transactions",
                               marker_color=BAR_COLOR, opacity=0.8),
                        secondary_y=False,
                    )
                    fig_fund.add_trace(
                        go.Scatter(x=fund_type["자금명"], y=fund_type["이상거래비율"],
                                   name="Fraud Ratio (%)",
                                   mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                        secondary_y=True,
                    )
                    _apply_dark(fig_fund, height=_H2, secondary_y=True)
                    fig_fund.update_yaxes(title_text="Transaction Count",  title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                    fig_fund.update_yaxes(title_text="Fraud Ratio (%)",    title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                    st.plotly_chart(fig_fund, width='stretch')

                    peak_fund = fund_type.loc[fund_type['총거래'].idxmax(), '자금명']
                    max_ratio_fund = fund_type.loc[fund_type['이상거래비율'].idxmax()]
                    _render_insight([
                        f"Peak fund type: {peak_fund}",
                        f"Highest fraud ratio fund type: {max_ratio_fund['자금명']} ({max_ratio_fund['이상거래비율']:.2f}%)",
                    ])
            except Exception as e:
                st.error(f"Unable to load fund type data: {e}")

    # ─────────────────────────────────────────────
    # 탭3: 이상거래 유형 – 분포 / 금액 / 히트맵 / 월별추이
    # ─────────────────────────────────────────────
    elif selected_tab == tab_names[2]:
        fraud_type = get_fraud_type_distribution(filters)
        type_map = {
            int(r["이상거래유형"]): f"{int(r['이상거래유형'])}. {r['이상거래설명']}"
            for _, r in fraud_type.iterrows()
        } if not fraud_type.empty else {}

        col_left3, col_right3 = st.columns(2)

        with col_left3:
            st.markdown('<p class="section-header">Fraud Type Distribution</p>', unsafe_allow_html=True)
            try:
                if fraud_type.empty:
                    st.info("No fraud type data found for the selected criteria.")
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
                        f"Most frequent type: {int(top1_ft['이상거래유형'])}. {top1_ft['이상거래설명']} ({top1_ft_pct:.1f}%)",
                        f"Detected fraud types: {len(fraud_type)}",
                    ])
            except Exception as e:
                st.error(f"Unable to load fraud type data: {e}")

        with col_right3:
            st.markdown('<p class="section-header">Fraud Type by Amount</p>', unsafe_allow_html=True)
            try:
                fraud_by_type = get_fraud_amount_by_type(filters)
                if fraud_by_type.empty:
                    st.info("No amount-by-type data found for the selected criteria.")
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
                    fig_fraud_amt.update_xaxes(title_text="Total Amount", title_font=dict(color="#8B8FA3", size=11))
                    fig_fraud_amt.update_yaxes(title_text="", autorange="reversed")
                    st.plotly_chart(fig_fraud_amt, width='stretch')

                    top_amt_row = fraud_by_type.loc[fraud_by_type['총금액'].idxmax()]
                    _render_insight([
                        f"Highest amount type: {int(top_amt_row['이상거래유형'])}. {top_amt_row['이상거래설명']} ({_format_amount(float(top_amt_row['총금액']))})",
                    ])
            except Exception as e:
                st.error(f"Unable to load amount-by-type data: {e}")

        st.markdown('<p class="section-header">Hourly x Fraud Type Cross Analysis</p>', unsafe_allow_html=True)
        try:
            heatmap_data = get_hourly_fraud_type_heatmap(filters)
            if heatmap_data.empty:
                st.info("No heatmap data found for the selected criteria.")
            else:
                pivot = heatmap_data.pivot_table(
                    index="이상거래유형", columns="거래시간대", values="건수", fill_value=0
                )
                y_labels = [type_map.get(int(t), f"유형 {int(t)}") for t in pivot.index]
                x_labels = [f"{int(h):02d}~{int(h)+3:02d}시" for h in pivot.columns]

                fig_heatmap = go.Figure(go.Heatmap(
                    z=pivot.values,
                    x=x_labels,
                    y=y_labels,
                    colorscale=[[0, "#F5F7FA"], [0.5, "#6EE7B7"], [1, "#059669"]],
                    hovertemplate="시간대: %{x}<br>유형: %{y}<br>건수: %{z}<extra></extra>",
                    texttemplate="%{z}",
                    textfont=dict(color="#E0E0E0", size=11),
                ))
                _apply_dark(fig_heatmap, height=360)
                fig_heatmap.update_layout(
                    xaxis_title="Time Period",
                    yaxis_title="Fraud Type",
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
                    f"Peak fraud combination: {peak_hm_type} x {peak_hm_hour} ({int(peak_hm['건수']):,} cases)",
                    f"Most frequent type across all hours: {top_type_label}",
                ])
        except Exception as e:
            st.error(f"Unable to load heatmap data: {e}")

        st.markdown('<p class="section-header">Fraud Type Monthly Trend</p>', unsafe_allow_html=True)
        try:
            trend_data = get_fraud_type_monthly_trend(filters)
            if trend_data.empty:
                st.info("No monthly trend data found for the selected criteria.")
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
                fig_trend.update_xaxes(title_text="Year-Month",       title_font=dict(color="#8B8FA3", size=11))
                fig_trend.update_yaxes(title_text="Fraud Count",    title_font=dict(color="#8B8FA3", size=11))
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
                        f"Increasing trend type: {growing} (+{type_growths[growing]:,})",
                        f"Decreasing trend type: {declining} ({type_growths[declining]:,})",
                    ])
        except Exception as e:
            st.error(f"Unable to load fraud type monthly trend data: {e}")

    # ─────────────────────────────────────────────
    # 탭4: 금융회사 – 출금/입금 상위 20
    # ─────────────────────────────────────────────
    elif selected_tab == tab_names[3]:
        st.markdown('<p class="section-header">Fraud by Financial Institution (Top 20)</p>', unsafe_allow_html=True)
        try:
            banks = get_top_banks(filters)
            if banks.empty:
                st.info("No institution data found for the selected criteria.")
            else:
                tab_out, tab_in = st.tabs(["Sender Institutions", "Receiver Institutions"])

                with tab_out:
                    banks_out = banks[banks["구분"] == "출금"].sort_values("이상거래", ascending=False).head(20)
                    if banks_out.empty:
                        st.info("No sender institution fraud data available.")
                    else:
                        banks_out["금융회사명"] = banks_out["금융회사"].astype(str)
                        fig_bank_out = make_subplots(specs=[[{"secondary_y": True}]])
                        fig_bank_out.add_trace(
                            go.Bar(x=banks_out["금융회사명"], y=banks_out["이상거래"], name="Fraud Count",
                                   marker_color=ACCENT_COLOR),
                            secondary_y=False,
                        )
                        fig_bank_out.add_trace(
                            go.Scatter(x=banks_out["금융회사명"], y=banks_out["이상거래비율"], name="Fraud Ratio (%)",
                                       mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                            secondary_y=True,
                        )
                        _apply_dark(fig_bank_out, height=_H2, secondary_y=True)
                        fig_bank_out.update_xaxes(title_text="Institution Code",   title_font=dict(color="#8B8FA3", size=11))
                        fig_bank_out.update_yaxes(title_text="Fraud Count",        title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                        fig_bank_out.update_yaxes(title_text="Fraud Ratio (%)",    title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                        st.plotly_chart(fig_bank_out, width='stretch')
                        top_out = banks_out.iloc[0]
                        _render_insight([
                            f"Top sender institution by fraud: #{int(top_out['금융회사'])} ({int(top_out['이상거래']):,} cases, ratio {top_out['이상거래비율']:.2f}%)",
                        ])

                with tab_in:
                    banks_in = banks[banks["구분"] == "입금"].sort_values("이상거래", ascending=False).head(20)
                    if banks_in.empty:
                        st.info("No receiver institution fraud data available.")
                    else:
                        banks_in["금융회사명"] = banks_in["금융회사"].astype(str)
                        fig_bank_in = make_subplots(specs=[[{"secondary_y": True}]])
                        fig_bank_in.add_trace(
                            go.Bar(x=banks_in["금융회사명"], y=banks_in["이상거래"], name="Fraud Count",
                                   marker_color=ACCENT_COLOR),
                            secondary_y=False,
                        )
                        fig_bank_in.add_trace(
                            go.Scatter(x=banks_in["금융회사명"], y=banks_in["이상거래비율"], name="Fraud Ratio (%)",
                                       mode="lines+markers", marker_color=LINE_COLOR, line=dict(width=2)),
                            secondary_y=True,
                        )
                        _apply_dark(fig_bank_in, height=_H2, secondary_y=True)
                        fig_bank_in.update_xaxes(title_text="Institution Code",   title_font=dict(color="#8B8FA3", size=11))
                        fig_bank_in.update_yaxes(title_text="Fraud Count",        title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
                        fig_bank_in.update_yaxes(title_text="Fraud Ratio (%)",    title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
                        st.plotly_chart(fig_bank_in, width='stretch')
                        top_in = banks_in.iloc[0]
                        _render_insight([
                            f"Top receiver institution by fraud: #{int(top_in['금융회사'])} ({int(top_in['이상거래']):,} cases, ratio {top_in['이상거래비율']:.2f}%)",
                        ])
        except Exception as e:
            st.error(f"Unable to load institution data: {e}")
