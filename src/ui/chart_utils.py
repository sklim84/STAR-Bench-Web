# ------------------------------------------------------------------
# Plotly 차트 공통 유틸리티
# 모든 _pages/ 모듈에서 공유하는 색상 상수와 다크 테마 헬퍼
# ------------------------------------------------------------------

BAR_COLOR = "#4E79A7"
LINE_COLOR = "#E15759"
ACCENT_COLOR = "#F28E2B"
MINT_COLOR = "#4ECDC4"

FRAUD_TYPE_COLORS = ["#4ECDC4", "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F"]

COMMUNITY_COLORS = [
    "#4ECDC4", "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC", "#D37295",
]


def apply_dark(fig, height: int = 380, secondary_y: bool = False):
    """Plotly figure에 글래스모피즘 다크 테마를 적용한다."""
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
