"""A running host is insufficient when the build worker used old source."""
import httpx
import pytest

from tools.check_hosted_source import HOST, TOKEN_ENDPOINT, check


@pytest.mark.parametrize("private_owner", [False, True])
def test_viewer_identity_is_explicit_and_management_key_never_reaches_app(private_owner):
    requests = []
    expected = {"index.html": b'<div id="auth-gate"></div>', "app.js": b"new source"}

    def respond(request):
        requests.append(request)
        if str(request.url) == TOKEN_ENDPOINT:
            assert request.headers.get("Authorization") == ("Bearer management-test-only" if private_owner else None)
            return httpx.Response(200, json={"Data": {"Token": "viewer-test-only"}})
        assert request.headers.get("Authorization") is None
        assert request.headers["X-Studio-Token"] == "viewer-test-only"
        if request.url.path == "/api/conversations":
            return httpx.Response(401)
        return httpx.Response(200, content=expected["index.html" if request.url.path == "/api/workbench" else "app.js"])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = check(client, "a" * 40, expected, private_owner=private_owner,
                       owner_key="management-test-only" if private_owner else None)
    assert result["source_and_auth_gate_passed"]
    assert result["public_source_verified"] is (not private_owner)
    assert result["full_functional_acceptance"] is False
    assert all(request.method == "GET" for request in requests)
    assert set(str(request.url).split("/", 3)[2] for request in requests) == {"www.modelscope.cn", HOST.split("//")[1]}


def test_stale_script_and_missing_auth_are_not_a_successful_release():
    def respond(request):
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(200, json={"Data": {"Token": ""}})
        return httpx.Response(200, content=b"old unauthenticated application")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = check(client, "b" * 40,
                       {"index.html": b'<div id="auth-gate"></div>', "app.js": b"new source"})
    assert not result["source_and_auth_gate_passed"]
    assert not result["public_source_verified"]
    assert result["unauthenticated_conversations_http"] == 200
    assert not any(row["matches_git"] for row in result["assets"].values())
