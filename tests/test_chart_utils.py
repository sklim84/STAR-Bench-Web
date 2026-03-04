"""src/ui/chart_utils.py 단위 테스트."""

from unittest.mock import MagicMock

from src.ui.chart_utils import apply_dark


def test_apply_dark_updates_common_layout_and_axes():
    """기본 다크 테마 적용 시 레이아웃/축 설정이 호출되어야 한다."""
    fig = MagicMock()

    returned = apply_dark(fig, height=420, secondary_y=False)

    assert returned is fig
    fig.update_layout.assert_called_once()
    layout_kwargs = fig.update_layout.call_args.kwargs
    assert layout_kwargs["height"] == 420
    fig.update_xaxes.assert_called_once()
    assert fig.update_yaxes.call_count == 1


def test_apply_dark_updates_secondary_y_axis_when_requested():
    """secondary_y=True이면 보조 Y축 설정 호출이 추가되어야 한다."""
    fig = MagicMock()

    apply_dark(fig, secondary_y=True)

    assert fig.update_yaxes.call_count == 2
    second_call_kwargs = fig.update_yaxes.call_args_list[1].kwargs
    assert second_call_kwargs["secondary_y"] is True
