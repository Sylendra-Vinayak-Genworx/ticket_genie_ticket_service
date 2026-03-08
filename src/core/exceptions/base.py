"""Domain exceptions for Ticketing Service."""

from http import HTTPStatus


class TicketingGenieBaseException(Exception):
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None):
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


# ── Auth / Permission ──────────────────────────────────────────────────────
class InvalidTokenError(TicketingGenieBaseException):
    status_code = HTTPStatus.UNAUTHORIZED
    detail = "Invalid or missing token."

class InsufficientPermissionsError(TicketingGenieBaseException):
    status_code = HTTPStatus.FORBIDDEN
    detail = "You do not have permission to perform this action."

class AuthServiceUnavailableError(TicketingGenieBaseException):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    detail = "Auth Service is currently unavailable."

# ── Resource not found ─────────────────────────────────────────────────────
class TicketNotFoundError(TicketingGenieBaseException):
    status_code = HTTPStatus.NOT_FOUND
    detail = "Ticket not found."

class UserNotFoundError(TicketingGenieBaseException):
    status_code = HTTPStatus.NOT_FOUND
    detail = "User not found."

class SLARuleNotFoundError(TicketingGenieBaseException):
    status_code = HTTPStatus.NOT_FOUND
    detail = "No matching SLA rule found."

class SLANotFoundError(TicketingGenieBaseException):
    status_code = HTTPStatus.NOT_FOUND
    detail = "SLA not found."

class KeywordRuleNotFoundError(TicketingGenieBaseException):
    status_code = HTTPStatus.NOT_FOUND
    detail = "Keyword rule not found."

# ── Business rule violations ───────────────────────────────────────────────
class InvalidStatusTransitionError(TicketingGenieBaseException):
    status_code = HTTPStatus.BAD_REQUEST
    detail = "Invalid ticket status transition."

class TicketAlreadyAssignedError(TicketingGenieBaseException):
    status_code = HTTPStatus.CONFLICT
    detail = "Ticket is already assigned to this agent."

class TicketAlreadyEscalatedError(TicketingGenieBaseException):
    status_code = HTTPStatus.CONFLICT
    detail = "Ticket has already been escalated."