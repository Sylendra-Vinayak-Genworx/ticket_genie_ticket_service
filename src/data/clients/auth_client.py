import asyncio
import logging
from typing import Optional
from  uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict

from src.config.settings import get_settings
from src.core.exceptions.base import (
    AuthServiceUnavailableError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)


class UserDTO(BaseModel):
    """Minimal user payload returned by Auth Service /api/v1/auth/users/{uuid}"""
    model_config = ConfigDict(json_encoders={UUID: str})

    id: str
    email: str
    role: str
    full_name: Optional[str] = None
    is_active: bool = True
    is_verified: bool = False
    preferred_mode_of_contact: str = "email"
    customer_tier_id: Optional[int] = None
    lead_id: Optional[str] = None
    team_id: Optional[str] = None

    

class AuthServiceClient:
    """Thin async wrapper around Auth Service REST API."""

    def __init__(self) -> None:
        self._base_url = get_settings().auth_service_url.rstrip("/")
        self._timeout = httpx.Timeout(5.0)

    async def get_all_users(self) -> list[UserDTO]:
        """
        GET {AUTH_SERVICE_URL}/api/v1/auth/users
        Returns a list of all users. Used for periodic sync of agent profiles.
        """
        url = f"{self._base_url}/api/v1/auth/users"
        logger.debug("auth_client: fetching all users from url=%s", url)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
        except httpx.TransportError as exc:
            logger.error("auth_client: transport error fetching all users: %s", exc)
            raise AuthServiceUnavailableError("Auth Service unreachable while fetching users.")

        if resp.status_code != 200:
            logger.error(
                "auth_client: unexpected status=%s fetching all users body=%s",
                resp.status_code, resp.text,
            )
            raise AuthServiceUnavailableError(f"Auth Service returned {resp.status_code} while fetching users.")

        return [UserDTO.model_validate(u) for u in resp.json()]

    async def get_user(self, user_id: str) -> UserDTO:   
        """
        GET {AUTH_SERVICE_URL}/api/v1/auth/users/{user_id}
        user_id is the UUID string from the JWT sub claim.
        """
        url = f"{self._base_url}/api/v1/auth/users/{user_id}"
        logger.debug("auth_client: fetching user_id=%s url=%s", user_id, url)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
        except httpx.TransportError as exc:
            logger.error(
                "auth_client: transport error fetching user_id=%s: %s", user_id, exc
            )
            raise AuthServiceUnavailableError(
                f"Auth Service unreachable while fetching user {user_id}."
            )

        if resp.status_code == 404:
            raise UserNotFoundError(f"User {user_id} not found in Auth Service.")

        if resp.status_code != 200:
            logger.error(
                "auth_client: unexpected status=%s for user_id=%s body=%s",
                resp.status_code, user_id, resp.text,
            )
            raise AuthServiceUnavailableError(
                f"Auth Service returned {resp.status_code} for user {user_id}."
            )

        return UserDTO.model_validate(resp.json())

    async def get_users_bulk(self, user_ids: list[str]) -> dict[str, UserDTO]:
        """
        Fetch multiple users in parallel.
        Returns {user_id: UserDTO}. Missing users are logged and skipped.
        """
        results: dict[str, UserDTO] = {}

        async def _fetch(uid: str) -> None:
            try:
                results[uid] = await self.get_user(uid)
            except UserNotFoundError:
                logger.warning("auth_client: user_id=%s not found (bulk fetch)", uid)
            except AuthServiceUnavailableError:
                logger.error("auth_client: service unavailable for user_id=%s", uid)

        await asyncio.gather(*[_fetch(uid) for uid in set(user_ids)])
        return results
        
auth_client = AuthServiceClient()