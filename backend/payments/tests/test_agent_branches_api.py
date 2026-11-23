from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APISimpleTestCase


@override_settings(
    BI_AGENT_API_KEY="directory-test-key",
    BRANCH_NAME="Head Office",
    PAYMENT_RELAY_TARGETS=[
        {"name": "New Branch", "url": "https://new.example/", "api_key": "relay-only-secret"},
    ],
)
class AgentBranchDirectoryAPITest(APISimpleTestCase):
    def test_reads_existing_directory_without_relay_credentials(self):
        url = reverse("agent-branches")
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer incorrect-key")
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer directory-test-key")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response.json(), {
            "local": {"id": "head-office", "name": "Head Office"},
            "remote": [{"id": "new-branch", "name": "New Branch", "base_url": "https://new.example/api/v1/"}],
        })
        self.assertEqual(self.client.post(url).status_code, 405)

    @override_settings(PAYMENT_RELAY_TARGETS=[
        {"name": "New Branch", "url": "https://user:private@example.com"},
    ])
    def test_invalid_config_does_not_expose_credential_in_url(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer directory-test-key")
        response = self.client.get(reverse("agent-branches"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"code": "invalid_branch_directory"})
