"""OpenAI widget HTML templates."""

from .widgets.set_active_floor import build_set_active_floor_widget_html
from .widgets.query_current_floor import build_query_current_floor_widget_html


def build_floor_summary_widget_html(*, asset_base_url: str | None = None) -> str:
    """Template builder used by the adapter."""

    return build_set_active_floor_widget_html(asset_base_url=asset_base_url)


def build_query_floor_answer_widget_html(*, asset_base_url: str | None = None) -> str:
    """Template builder for query-current-floor tool responses."""

    return build_query_current_floor_widget_html(asset_base_url=asset_base_url)
