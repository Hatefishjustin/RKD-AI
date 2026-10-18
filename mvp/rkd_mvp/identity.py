from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .api_service import ApiError


@dataclass(frozen=True)
class RequestIdentity:
    organization_id: str
    actor_id: str
    actor_type: str = "human"
    is_admin: bool = False
    csrf_token: str = ""


class IdentityProvider(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> RequestIdentity: ...


class DevHeaderIdentityProvider:
    """Local-only identity provider; production must replace it with OIDC/JWT validation."""

    def authenticate(self, headers: Mapping[str, str]) -> RequestIdentity:
        organization_id = headers.get("X-Organization-Id")
        if not organization_id:
            raise ApiError(401, "UNAUTHORIZED", "X-Organization-Id is required by the local development server")
        return RequestIdentity(organization_id, headers.get("X-Actor-Id", "local-user"))


class LocalIdentityProvider:
    """Single-user launcher identity. Development headers cannot change it."""

    def authenticate(self, headers: Mapping[str, str]) -> RequestIdentity:
        return RequestIdentity("org-local", "local-user")
