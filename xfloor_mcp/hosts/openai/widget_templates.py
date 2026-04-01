"""OpenAI widget HTML templates."""

from .widgets.set_active_floor import build_set_active_floor_widget_html


def build_floor_summary_widget_html() -> str:
    """Backward-compatible template builder used by the adapter."""

    return build_set_active_floor_widget_html()
