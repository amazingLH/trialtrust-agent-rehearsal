"""Tie each HTML entry to the exact styles and scripts shipped with it."""
import hashlib
import re
from collections.abc import Mapping


def versioned_html(html: str, assets: Mapping[str, bytes], prefix: str = '/assets/') -> str:
    def link(match):
        name = match['name']
        version = hashlib.sha256(assets[name]).hexdigest()[:16]
        return f'{match["attribute"]}{prefix}{name}?v={version}"'
    return re.sub(r'(?P<attribute>(?:src|href)=")/assets/(?P<name>[^"?]+)"', link, html)
