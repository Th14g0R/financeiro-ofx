from __future__ import annotations


def apply_sorting(
    request,
    queryset,
    *,
    allowed: dict[str, str],
    default: str,
    default_direction: str = "asc",
):
    sort_key = (
        request.GET.get("sort", "")
        .strip()
    )

    if sort_key not in allowed:
        sort_key = default

    direction = (
        request.GET.get("dir", "")
        .strip()
        .lower()
    )

    if direction not in {"asc", "desc"}:
        direction = default_direction

    orm_field = allowed[sort_key]

    if direction == "desc":
        orm_field = f"-{orm_field}"

    return queryset.order_by(
        orm_field,
        "id",
    )
