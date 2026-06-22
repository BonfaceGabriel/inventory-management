import json
import logging
from typing import Dict, List, Optional

from django.conf import settings
import requests

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    return name.lower().replace(' ', '-')


def _get_relay_secret() -> str:
    return getattr(settings, 'PAYMENT_RELAY_SECRET', '')


def _get_targets() -> List[Dict]:
    return getattr(settings, 'PAYMENT_RELAY_TARGETS', [])


def get_local_branch_slug() -> str:
    name = getattr(settings, 'BRANCH_NAME', 'Main Shop')
    return _slugify(name)


def resolve_branch(slug: str) -> Optional[Dict]:
    for target in _get_targets():
        if _slugify(target.get('name', '')) == slug:
            return target
    return None


class BiRemoteService:

    @staticmethod
    def execute(branch_slug: str, tool_name: str, args: Dict) -> Dict:
        target = resolve_branch(branch_slug)
        if not target:
            return {'error': f"Unknown branch: {branch_slug}"}

        secret = _get_relay_secret()
        if not secret:
            return {'error': 'PAYMENT_RELAY_SECRET not configured'}

        url = target['url'].rstrip('/') + '/api/v1/bi/execute/'

        try:
            resp = requests.post(
                url,
                json={'tool_name': tool_name, 'args': args},
                headers={'X-Relay-Secret': secret},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(
                f"Remote execute {branch_slug}/{tool_name} returned "
                f"{resp.status_code}: {resp.text[:200]}"
            )
            return {'error': f"Remote branch returned {resp.status_code}"}
        except requests.RequestException as e:
            logger.error(f"Failed to execute {tool_name} on {branch_slug}: {e}")
            return {'error': f"Cannot reach branch {branch_slug}"}

    @staticmethod
    def list_branches() -> List[Dict]:
        branches = []
        local_name = getattr(settings, 'BRANCH_NAME', 'Main Shop')
        branches.append({
            'slug': _slugify(local_name),
            'name': local_name,
            'is_local': True,
        })
        for target in _get_targets():
            branches.append({
                'slug': _slugify(target.get('name', '')),
                'name': target.get('name', ''),
                'is_local': False,
            })
        return branches
