import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.features.dashboard import (
    get_summary,
    get_monthly_trend,
    get_hourly_distribution,
    get_amount_distribution,
    get_fraud_type_distribution,
    get_medium_distribution,
    get_top_banks,
)

# ------------------------------------------------------------------
# 다크 테마 상수
# ------------------------------------------------------------------
BAR_COLOR = "#4E79A7"
LINE_COLOR = "#E15759"
ACCENT_COLOR = "#F28E2B"


def _apply_dark(fig, height=380, secondary_y=False):
    """Plotly figure에 다크 테마를 적용한다."""
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#C0C4D0", size=12),
        legend=dict(
            orientation="h", y=1.12,
            font=dict(color="#8B8FA3", size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(t=30, b=30, l=10, r=10),
    )
    fig.update_xaxes(gridcolor="#1E2333", zerolinecolor="#1E2333",
                     tickfont=dict(color="#8B8FA3"))
    fig.update_yaxes(gridcolor="#1E2333", zerolinecolor="#1E2333",
                     tickfont=dict(color="#8B8FA3"))
    if secondary_y:
        fig.update_yaxes(gridcolor="#1E2333", tickfont=dict(color="#8B8FA3"),
                         secondary_y=True)
    return fig


def render():
    st.markdown('<p style="color:#FFFFFF; font-size:24px; font-weight:800; margin-bottom:4px;">'
                '기본 분석 대시보드</p>', unsafe_allow_html=True)

    # ── 요약 지표 카드 ──
    summary = get_summary()
    row = summary.iloc[0]

    fraud_ratio = f"{row['이상거래비율']:.2f}%"

    c1, c2, c3, c4, c5 = st.columns(5)
    cards = [
        (c1, "총 거래 건수", f"{int(row['총거래']):,}", ""),
        (c2, "이상거래 건수", f"{int(row['이상거래']):,}", ""),
        (c3, "이상거래 비율", fraud_ratio, "이상거래 / 총거래"),
        (c4, "출금 계좌 수", f"{int(row['출금계좌수']):,}", ""),
        (c5, "입금 계좌 수", f"{int(row['입금계좌수']):,}", ""),
    ]
    for col, label, value, sub in cards:
        with col:
            sub_html = f'<div class="sub">{sub}</div>' if sub else ""
            st.markdown(f"""<div class="metric-card">
                <div class="label">{label}</div>
                <div class="value">{value}</div>
                {sub_html}
            </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── 월별 추이 ──
    st.markdown('<p class="section-header">월별 거래 추이</p>', unsafe_allow_html=True)

    monthly = get_monthly_trend()
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
    _apply_dark(fig_monthly, height=400, secondary_y=True)
    fig_monthly.update_yaxes(title_text="거래 건수", title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
    fig_monthly.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
    st.plotly_chart(fig_monthly, use_container_width=True)

    # ── 2행: 시간대 + 거래금액 ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown('<p class="section-header">시간대별 분포</p>', unsafe_allow_html=True)
        hourly = get_hourly_distribution()
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
        _apply_dark(fig_hour, height=350, secondary_y=True)
        fig_hour.update_yaxes(title_text="거래 건수", title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
        fig_hour.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
        st.plotly_chart(fig_hour, use_container_width=True)

    with col_right:
        st.markdown('<p class="section-header">거래금액 구간별 분포</p>', unsafe_allow_html=True)
        amount = get_amount_distribution()

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
        _apply_dark(fig_amt, height=350, secondary_y=True)
        fig_amt.update_yaxes(title_text="거래 건수", title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
        fig_amt.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
        st.plotly_chart(fig_amt, use_container_width=True)

    # ── 3행: 이상거래유형 + 매체구분 ──
    col_left2, col_right2 = st.columns(2)

    with col_left2:
        st.markdown('<p class="section-header">이상거래 유형별 분포</p>', unsafe_allow_html=True)
        fraud_type = get_fraud_type_distribution()
        fraud_type["레이블"] = fraud_type["이상거래유형"].astype(int).astype(str) + ". " + fraud_type["이상거래설명"].fillna("")

        fig_fraud = px.pie(
            fraud_type, values="건수", names="레이블",
            color_discrete_sequence=["#4ECDC4", "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F"],
            hole=0.45,
        )
        fig_fraud.update_layout(
            height=380,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#C0C4D0", size=11),
            legend=dict(font=dict(color="#8B8FA3", size=10), bgcolor="rgba(0,0,0,0)"),
            margin=dict(t=20, b=20, l=10, r=10),
        )
        fig_fraud.update_traces(textposition="outside", textinfo="label+percent",
                                textfont=dict(color="#C0C4D0", size=10))
        st.plotly_chart(fig_fraud, use_container_width=True)

    with col_right2:
        st.markdown('<p class="section-header">매체구분별 분포</p>', unsafe_allow_html=True)
        medium = get_medium_distribution()
        medium["매체명"] = "매체 " + medium["매체구분"].astype(str)

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
        _apply_dark(fig_med, height=380, secondary_y=True)
        fig_med.update_yaxes(title_text="거래 건수", title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
        fig_med.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
        st.plotly_chart(fig_med, use_container_width=True)

    # ── 4행: 금융회사별 이상거래 ──
    st.markdown('<p class="section-header">금융회사별 이상거래 현황 (상위 20)</p>', unsafe_allow_html=True)

    banks = get_top_banks()

    tab_out, tab_in = st.tabs(["출금 금융회사", "입금 금융회사"])

    with tab_out:
        banks_out = banks[banks["구분"] == "출금"].sort_values("이상거래", ascending=False).head(20)
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
        _apply_dark(fig_bank_out, height=380, secondary_y=True)
        fig_bank_out.update_xaxes(title_text="금융회사 코드", title_font=dict(color="#8B8FA3", size=11))
        fig_bank_out.update_yaxes(title_text="이상거래 건수", title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
        fig_bank_out.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
        st.plotly_chart(fig_bank_out, use_container_width=True)

    with tab_in:
        banks_in = banks[banks["구분"] == "입금"].sort_values("이상거래", ascending=False).head(20)
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
        _apply_dark(fig_bank_in, height=380, secondary_y=True)
        fig_bank_in.update_xaxes(title_text="금융회사 코드", title_font=dict(color="#8B8FA3", size=11))
        fig_bank_in.update_yaxes(title_text="이상거래 건수", title_font=dict(color="#8B8FA3", size=11), secondary_y=False)
        fig_bank_in.update_yaxes(title_text="이상거래 비율(%)", title_font=dict(color="#8B8FA3", size=11), secondary_y=True)
        st.plotly_chart(fig_bank_in, use_container_width=True)
