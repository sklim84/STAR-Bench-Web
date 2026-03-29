# ------------------------------------------------------------------
# Plotly 차트 공통 유틸리티
# 모든 _pages/ 모듈에서 공유하는 색상 상수와 테마 헬퍼
# ------------------------------------------------------------------

BAR_COLOR = "#4E79A7"
LINE_COLOR = "#E15759"
ACCENT_COLOR = "#F28E2B"
MINT_COLOR = "#059669"

FRAUD_TYPE_COLORS = ["#059669", "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F"]

COMMUNITY_COLORS = [
    "#059669", "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC", "#D37295",
]


def apply_theme(fig, height: int = 380, secondary_y: bool = False):
    """Plotly figure에 라이트 테마를 적용한다."""
    fig.update_layout(
        height=height,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#374151", size=12),
        legend=dict(
            orientation="h", y=1.12,
            font=dict(color="#6B7280", size=11),
            bgcolor="rgba(255,255,255,0)",
        ),
        margin=dict(t=30, b=30, l=10, r=10),
    )
    fig.update_xaxes(gridcolor="#E5E7EB", zerolinecolor="#E5E7EB",
                     tickfont=dict(color="#6B7280"))
    fig.update_yaxes(gridcolor="#E5E7EB", zerolinecolor="#E5E7EB",
                     tickfont=dict(color="#6B7280"))
    if secondary_y:
        fig.update_yaxes(gridcolor="#E5E7EB", tickfont=dict(color="#6B7280"),
                         secondary_y=True)
    return fig


# 후방 호환 별칭
apply_dark = apply_theme
