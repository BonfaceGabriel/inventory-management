import httpx
import pytest

from whatsapp_bi.branch_directory import BranchDirectory, BranchDiscoveryError


@pytest.mark.parametrize(("status", "remote_url", "message"), [
    (302, None, "currently unavailable"),
    (401, None, "rejected BI_BRANCH_DISCOVERY_TOKEN"),
    (404, None, "endpoint is missing"),
    (200, "http://remote.example/api/v1/", "invalid branch directory"),
])
async def test_directory_rejects_redirects_and_invalid_configuration(status, remote_url, message):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://other.example/"}, json={
            "local": {"id": "central", "name": "Central"},
            "remote": [{"id": "remote", "name": "Remote", "base_url": remote_url}],
        })

    directory = BranchDirectory("https://central.example/api/v1/", "discovery-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        with pytest.raises(BranchDiscoveryError, match=message):
            await directory.load(http)

    assert len(requests) == 1
    assert requests[0].url.path == "/api/v1/agent/branches/"
