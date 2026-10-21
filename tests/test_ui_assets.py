"""A new page must never reuse the URLs of scripts or styles from an old release."""
import hashlib
import re
from pathlib import Path
from fastapi.testclient import TestClient
from trialtrust.ui_assets import versioned_html
from trialtrust.webapp import create_app


def test_resource_versions_follow_content_even_when_size_and_mtime_match():
    html='<link href="/assets/style.css"><script src="/assets/app.js"></script>'
    first=versioned_html(html,{'style.css':b'old','app.js':b'old'})
    changed=versioned_html(html,{'style.css':b'new','app.js':b'new'})
    assert first != changed
    assert '?v='+hashlib.sha256(b'new').hexdigest()[:16] in changed
    assert versioned_html(html,{'style.css':b'new','app.js':b'new'},'/api/workbench-assets/').startswith('<link href="/api/workbench-assets/')


def test_both_entries_link_exact_current_assets_and_prevent_stale_caching(tmp_path):
    with TestClient(create_app(tmp_path/'web',enable_live=False)) as client:
        for entry,prefix in [('/','/assets/'),('/api/workbench','/api/workbench-assets/')]:
            page=client.get(entry)
            assert page.status_code == 200 and page.headers['cache-control']=='no-store'
            links=re.findall(r'(?:href|src)="('+re.escape(prefix)+r'[^"?]+\?v=[a-f0-9]{16})"',page.text)
            assert len(links)==5
            for link in links:
                response=client.get(link)
                assert response.status_code==200 and response.headers['cache-control']=='no-store'
                assert hashlib.sha256(response.content).hexdigest()[:16]==link.rsplit('=',1)[1]
                name=link.split('?')[0].rsplit('/',1)[-1]
                assert response.content==(Path(__file__).parents[1]/'trialtrust/web'/name).read_bytes()
            assert '<h1>先陪 AI 走一遍，再决定交哪一步。</h1>' in page.text
