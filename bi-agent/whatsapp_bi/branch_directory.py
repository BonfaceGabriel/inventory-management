import os

import httpx
from pydantic import BaseModel, HttpUrl, SecretStr, ValidationError

from .models import BranchConfig, BranchIdentity, validate_api_base_url


class BranchDiscoveryError(ValueError):
    """The agent could not load a trusted branch directory."""


class RemoteBranch(BranchIdentity):
    base_url: HttpUrl


class DirectoryResponse(BaseModel):
    local: BranchIdentity
    remote: list[RemoteBranch]


class BranchDirectory:
    def __init__(self, base_url: str, token: str):
        if not base_url.strip() or not token.strip():
            raise BranchDiscoveryError("Set BI_BRANCH_DISCOVERY_URL and BI_BRANCH_DISCOVERY_TOKEN.")
        try:
            self.base_url = validate_api_base_url(HttpUrl(base_url))
        except (ValueError, ValidationError):
            raise BranchDiscoveryError("Set BI_BRANCH_DISCOVERY_URL to the inventory API base URL.") from None
        self.token = SecretStr(token.strip())

    @classmethod
    def from_env(cls) -> "BranchDirectory":
        return cls(os.getenv("BI_BRANCH_DISCOVERY_URL", ""), os.getenv("BI_BRANCH_DISCOVERY_TOKEN", ""))

    async def load(self, http: httpx.AsyncClient) -> list[BranchConfig]:
        try:
            response = await http.get(
                str(self.base_url).rstrip("/") + "/agent/branches/",
                headers={"Authorization": f"Bearer {self.token.get_secret_value()}", "Accept": "application/json"},
                timeout=10.0,
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise BranchDiscoveryError("The branch directory could not be reached.") from None
        if response.status_code in {401, 403}:
            raise BranchDiscoveryError("The branch directory rejected BI_BRANCH_DISCOVERY_TOKEN.")
        if response.status_code == 404:
            raise BranchDiscoveryError("The branch directory endpoint is missing on the configured backend.")
        if response.status_code != 200:
            raise BranchDiscoveryError("The branch directory is currently unavailable.")

        try:
            directory = DirectoryResponse.model_validate_json(response.content)
            entries = [(directory.local, self.base_url), *((branch, branch.base_url) for branch in directory.remote)]
            configs = [
                BranchConfig(
                    id=branch.id, name=branch.name, base_url=base_url,
                    token_env=f"{branch.id.upper().replace('-', '_')}_BI_TOKEN",
                )
                for branch, base_url in entries
            ]
        except ValidationError:
            raise BranchDiscoveryError("The backend returned invalid branch directory data.") from None
        if len({branch.id for branch in configs}) != len(configs):
            raise BranchDiscoveryError("The backend returned duplicate branch IDs.")
        return configs
