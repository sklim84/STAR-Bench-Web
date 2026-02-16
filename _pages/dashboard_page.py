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


def render():
    st.title("기본 분석 대시보드")

    # --- 요약 지표 ---
    summary = get_summary()
    row = summary.iloc[0]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("총 거래 건수", f"{int(row['총거래']):,}")
    col2.metric("이상거래 건수", f"{int(row['이상거래']):,}")
    col3.metric("이상거래 비율", f"{row['이상거래비율']:.2f}%")
    col4.metric("출금 계좌 수", f"{int(row['출금계좌수']):,}")
    col5.metric("입금 계좌 수", f"{int(row['입금계좌수']):,}")

    st.divider()

    # --- 월별 추이 ---
    st.subheader("월별 거래 추이")

    monthly = get_monthly_trend()
    monthly["연월str"] = monthly["연월"].astype(str).str[:4] + "-" + monthly["연월"].astype(str).str[4:]

    fig_monthly = make_subplots(specs=[[{"secondary_y": True}]])
    fig_monthly.add_trace(
        go.Bar(x=monthly["연월str"], y=monthly["총거래"], name="총 거래", marker_color="#4E79A7", opacity=0.7),
        secondary_y=False,
    )
    fig_monthly.add_trace(
        go.Scatter(x=monthly["연월str"], y=monthly["이상거래비율"], name="이상거래 비율(%)", mode="lines+markers",
                   marker_color="#E15759", line=dict(width=2)),
        secondary_y=True,
    )
    fig_monthly.update_layout(height=400, legend=dict(orientation="h", y=1.12), margin=dict(t=30, b=30))
    fig_monthly.update_yaxes(title_text="거래 건수", secondary_y=False)
    fig_monthly.update_yaxes(title_text="이상거래 비율(%)", secondary_y=True)
    st.plotly_chart(fig_monthly, use_container_width=True)

    # --- 2행: 시간대 + 거래금액 ---
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("시간대별 분포")
        hourly = get_hourly_distribution()
        hourly["시간대명"] = hourly["거래시간대"].apply(lambda h: f"{h:02d}~{h+3:02d}시")

        fig_hour = make_subplots(specs=[[{"secondary_y": True}]])
        fig_hour.add_trace(
            go.Bar(x=hourly["시간대명"], y=hourly["총거래"], name="총 거래", marker_color="#4E79A7", opacity=0.7),
            secondary_y=False,
        )
        fig_hour.add_trace(
            go.Scatter(x=hourly["시간대명"], y=hourly["이상거래비율"], name="이상거래 비율(%)", mode="lines+markers",
                       marker_color="#E15759", line=dict(width=2)),
            secondary_y=True,
        )
        fig_hour.update_layout(height=350, legend=dict(orientation="h", y=1.15), margin=dict(t=30, b=30))
        fig_hour.update_yaxes(title_text="거래 건수", secondary_y=False)
        fig_hour.update_yaxes(title_text="이상거래 비율(%)", secondary_y=True)
        st.plotly_chart(fig_hour, use_container_width=True)

    with col_right:
        st.subheader("거래금액 구간별 분포")
        amount = get_amount_distribution()

        fig_amt = make_subplots(specs=[[{"secondary_y": True}]])
        fig_amt.add_trace(
            go.Bar(x=amount["금액구간"], y=amount["총거래"], name="총 거래", marker_color="#4E79A7", opacity=0.7),
            secondary_y=False,
        )
        fig_amt.add_trace(
            go.Scatter(x=amount["금액구간"], y=amount["이상거래비율"], name="이상거래 비율(%)", mode="lines+markers",
                       marker_color="#E15759", line=dict(width=2)),
            secondary_y=True,
        )
        fig_amt.update_layout(height=350, legend=dict(orientation="h", y=1.15), margin=dict(t=30, b=30))
        fig_amt.update_yaxes(title_text="거래 건수", secondary_y=False)
        fig_amt.update_yaxes(title_text="이상거래 비율(%)", secondary_y=True)
        st.plotly_chart(fig_amt, use_container_width=True)

    # --- 3행: 이상거래유형 + 매체구분 ---
    col_left2, col_right2 = st.columns(2)

    with col_left2:
        st.subheader("이상거래 유형별 분포")
        fraud_type = get_fraud_type_distribution()
        fraud_type["레이블"] = fraud_type["이상거래유형"].astype(int).astype(str) + ". " + fraud_type["이상거래설명"].fillna("")

        fig_fraud = px.pie(
            fraud_type, values="건수", names="레이블",
            color_discrete_sequence=px.colors.qualitative.Set2,
            hole=0.4,
        )
        fig_fraud.update_layout(height=380, margin=dict(t=20, b=20))
        fig_fraud.update_traces(textposition="outside", textinfo="label+percent")
        st.plotly_chart(fig_fraud, use_container_width=True)

    with col_right2:
        st.subheader("매체구분별 분포")
        medium = get_medium_distribution()
        medium["매체명"] = "매체 " + medium["매체구분"].astype(str)

        fig_med = make_subplots(specs=[[{"secondary_y": True}]])
        fig_med.add_trace(
            go.Bar(x=medium["매체명"], y=medium["총거래"], name="총 거래", marker_color="#4E79A7", opacity=0.7),
            secondary_y=False,
        )
        fig_med.add_trace(
            go.Scatter(x=medium["매체명"], y=medium["이상거래비율"], name="이상거래 비율(%)", mode="lines+markers",
                       marker_color="#E15759", line=dict(width=2)),
            secondary_y=True,
        )
        fig_med.update_layout(height=380, legend=dict(orientation="h", y=1.15), margin=dict(t=20, b=20))
        fig_med.update_yaxes(title_text="거래 건수", secondary_y=False)
        fig_med.update_yaxes(title_text="이상거래 비율(%)", secondary_y=True)
        st.plotly_chart(fig_med, use_container_width=True)

    # --- 4행: 금융회사별 이상거래 ---
    st.subheader("금융회사별 이상거래 현황 (상위 20)")

    banks = get_top_banks()

    tab_out, tab_in = st.tabs(["출금 금융회사", "입금 금융회사"])

    with tab_out:
        banks_out = banks[banks["구분"] == "출금"].sort_values("이상거래", ascending=False).head(20)
        banks_out["금융회사명"] = banks_out["금융회사"].astype(str)

        fig_bank_out = make_subplots(specs=[[{"secondary_y": True}]])
        fig_bank_out.add_trace(
            go.Bar(x=banks_out["금융회사명"], y=banks_out["이상거래"], name="이상거래 건수", marker_color="#F28E2B"),
            secondary_y=False,
        )
        fig_bank_out.add_trace(
            go.Scatter(x=banks_out["금융회사명"], y=banks_out["이상거래비율"], name="이상거래 비율(%)",
                       mode="lines+markers", marker_color="#E15759", line=dict(width=2)),
            secondary_y=True,
        )
        fig_bank_out.update_layout(height=380, legend=dict(orientation="h", y=1.12), margin=dict(t=30, b=30))
        fig_bank_out.update_xaxes(title_text="금융회사 코드")
        fig_bank_out.update_yaxes(title_text="이상거래 건수", secondary_y=False)
        fig_bank_out.update_yaxes(title_text="이상거래 비율(%)", secondary_y=True)
        st.plotly_chart(fig_bank_out, use_container_width=True)

    with tab_in:
        banks_in = banks[banks["구분"] == "입금"].sort_values("이상거래", ascending=False).head(20)
        banks_in["금융회사명"] = banks_in["금융회사"].astype(str)

        fig_bank_in = make_subplots(specs=[[{"secondary_y": True}]])
        fig_bank_in.add_trace(
            go.Bar(x=banks_in["금융회사명"], y=banks_in["이상거래"], name="이상거래 건수", marker_color="#F28E2B"),
            secondary_y=False,
        )
        fig_bank_in.add_trace(
            go.Scatter(x=banks_in["금융회사명"], y=banks_in["이상거래비율"], name="이상거래 비율(%)",
                       mode="lines+markers", marker_color="#E15759", line=dict(width=2)),
            secondary_y=True,
        )
        fig_bank_in.update_layout(height=380, legend=dict(orientation="h", y=1.12), margin=dict(t=30, b=30))
        fig_bank_in.update_xaxes(title_text="금융회사 코드")
        fig_bank_in.update_yaxes(title_text="이상거래 건수", secondary_y=False)
        fig_bank_in.update_yaxes(title_text="이상거래 비율(%)", secondary_y=True)
        st.plotly_chart(fig_bank_in, use_container_width=True)
