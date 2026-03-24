import logging
import httpx
import secrets
import string

from src.config.settings import get_settings
from src.data.clients.auth_client import AuthServiceClient, UserDTO
from src.data.clients.postgres_client import AsyncSessionFactory
from src.core.services.notification.email_service import EmailNotificationService
from src.templates.email_templates import _WELCOME_HTML, _WELCOME_TEXT

logger = logging.getLogger(__name__)

def _generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))

class EmailCustomerService:
    def __init__(self, auth_client: AuthServiceClient) -> None:
        self._auth = auth_client

    async def resolve_customer(
        self, sender_email: str
    ) -> tuple[UserDTO, bool, str | None]:
        settings = get_settings()
        base = settings.auth_service_url.rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(
                    f"{base}/api/v1/auth/users/by-email",
                    params={"email": sender_email},
                )
            if resp.status_code == 200:
                logger.debug("email_ingest: found existing user email=%s", sender_email)
                return UserDTO.model_validate(resp.json()), False, None
        except httpx.TransportError as exc:
            logger.warning(
                "email_ingest: auth lookup failed for %s: %s", sender_email, exc
            )

        logger.info(
            "email_ingest: sender not registered, creating account email=%s", sender_email
        )
        temp_password = _generate_temp_password()
        display_name  = sender_email.split("@")[0].replace(".", " ").title()

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                create_resp = await client.post(
                    f"{base}/api/v1/auth/signup",
                    json={
                        "email":      sender_email,
                        "password":   temp_password,
                        "full_name":  display_name,
                        "role":       "user",
                    },
                )
            create_resp.raise_for_status()
            data = create_resp.json()
            user_data = data.get("user") or data
            user_dto  = UserDTO.model_validate(user_data)
            logger.info(
                "email_ingest: created new customer account user_id=%s email=%s",
                user_dto.id, sender_email,
            )
            return user_dto, True, temp_password

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                logger.info(
                    "email_ingest: race — account already exists for %s", sender_email
                )
                async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                    resp = await client.get(
                        f"{base}/api/v1/auth/users/by-email",
                        params={"email": sender_email},
                    )
                resp.raise_for_status()
                return UserDTO.model_validate(resp.json()), False, None
            raise

    async def send_credentials_email(
        self,
        *,
        sender_email: str,
        customer_name: str,
        temp_password: str,
        ticket_number: str,
        original_message_id: str,
        ticket_id: int,
        recipient_id: str,
    ) -> None:
        settings = get_settings()
        login_url = f"{settings.FRONTEND_URL.rstrip('/')}/login"

        try:
            async with AsyncSessionFactory() as cred_session:
                svc = EmailNotificationService(cred_session)
                config = await svc._ensure_config()
                from_name = config["smtp_from_name"]

                subject = f"[{ticket_number}] Your TicketGenie account credentials"
                html = _WELCOME_HTML.format(
                    customer_name=customer_name,
                    email=sender_email,
                    temp_password=temp_password,
                    login_url=login_url,
                    ticket_number=ticket_number,
                    from_name=from_name,
                )
                text = _WELCOME_TEXT.format(
                    customer_name=customer_name,
                    email=sender_email,
                    temp_password=temp_password,
                    login_url=login_url,
                    ticket_number=ticket_number,
                    from_name=from_name,
                )
                await svc._deliver(
                    config=config,
                    ticket_id=ticket_id,
                    recipient_id=recipient_id,
                    recipient_email=sender_email,
                    subject=subject,
                    body=text,
                    event_type="EMAIL_INGEST_CREDENTIALS",
                    html_body=html,
                    in_reply_to=original_message_id,
                    references=original_message_id,
                )
                await cred_session.commit()
            logger.info(
                "email_ingest: sent credentials email to=%s ticket=%s",
                sender_email, ticket_number,
            )
        except Exception:
            logger.exception(
                "email_ingest: credentials email failed for %s — ticket still created",
                sender_email,
            )
