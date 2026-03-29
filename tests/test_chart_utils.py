"""src/ui/chart_utils.py 단위 테스트."""

from unittest.mock import MagicMock

from src.ui.chart_utils import apply_theme, apply_dark


def test_apply_theme_updates_common_layout_and_axes():
    """라이트 테마 적용 시 레이아웃/축 설정이 호출되어야 한다."""
    fig = MagicMock()

    returned = apply_theme(fig, height=420, secondary_y=False)

    assert returned is fig
    fig.update_layout.assert_called_once()
    layout_kwargs = fig.update_layout.call_args.kwargs
    assert layout_kwargs["height"] == 420
    fig.update_xaxes.assert_called_once()
    assert fig.update_yaxes.call_count == 1


def test_apply_theme_updates_secondary_y_axis_when_requested():
    """secondary_y=True이면 보조 Y축 설정 호출이 추가되어야 한다."""
    fig = MagicMock()

    apply_theme(fig, secondary_y=True)

    assert fig.update_yaxes.call_count == 2
    second_call_kwargs = fig.update_yaxes.call_args_list[1].kwargs
    assert second_call_kwargs["secondary_y"] is True


def test_apply_dark_is_alias_for_apply_theme():
    """apply_dark는 apply_theme의 후방 호환 별칭이어야 한다."""
    assert apply_dark is apply_theme
