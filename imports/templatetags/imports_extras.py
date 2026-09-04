import json

from django import template


register = template.Library()


@register.filter
def pretty_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
