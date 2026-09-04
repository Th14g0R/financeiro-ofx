from __future__ import annotations

from django import template


register = template.Library()


@register.simple_tag(
    takes_context=True
)
def sort_url(
    context,
    field: str,
):
    request = context["request"]
    params = request.GET.copy()

    current_field = params.get(
        "sort",
        "",
    )
    current_direction = params.get(
        "dir",
        "asc",
    )

    next_direction = (
        "desc"
        if (
            current_field == field
            and current_direction == "asc"
        )
        else "asc"
    )

    params["sort"] = field
    params["dir"] = next_direction
    params.pop("page", None)

    encoded = params.urlencode()

    return f"?{encoded}" if encoded else "?"


@register.simple_tag(
    takes_context=True
)
def sort_icon(
    context,
    field: str,
):
    request = context["request"]
    current_field = request.GET.get(
        "sort",
        "",
    )

    if current_field != field:
        return "↕"

    direction = request.GET.get(
        "dir",
        "asc",
    )

    return "↑" if direction == "asc" else "↓"
