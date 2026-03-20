"""
schemas/email_config_schema.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pydantic schemas for email configuration.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EmailConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    config_id: int
    imap_host: str
    imap_port: int
    imap_user: str
    imap_mailbox: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_from_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    updated_by: str | None
    
    # Passwords are never returned


class EmailConfigUpdateRequest(BaseModel):
    imap_host: str | None = None
    imap_port: int | None = Field(None, ge=1, le=65535)
    imap_user: str | None = None
    imap_password: str | None = Field(None, min_length=1)  # Only set if provided
    imap_mailbox: str | None = None
    
    smtp_host: str | None = None
    smtp_port: int | None = Field(None, ge=1, le=65535)
    smtp_user: str | None = None
    smtp_password: str | None = Field(None, min_length=1)  # Only set if provided
    smtp_from_name: str | None = None
    
    is_active: bool | None = None


class EmailConfigTestRequest(BaseModel):
    test_email: str = Field(..., description="Email address to send test notification")