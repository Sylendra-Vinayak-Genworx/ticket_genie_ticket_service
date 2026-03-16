"""
api/rest/routes/email_config_routes.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Admin-only routes for managing email configuration.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import require_admin
from src.api.rest.dependencies import get_db
from src.core.services.email_config_service import EmailConfigService
from src.schemas.email_config_schema import (
    EmailConfigResponse,
    EmailConfigUpdateRequest,
    EmailConfigTestRequest,
)

router = APIRouter(prefix="/admin/email-config", tags=["Email Configuration"])


@router.get("", response_model=EmailConfigResponse)
async def get_email_config(
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(require_admin),
):
    """
    Get current email configuration (admin only).
    Passwords are never returned in the response.
    """
    service = EmailConfigService(db)
    config = await service.get_config()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email configuration not found. Please initialize first."
        )
    
    return config


@router.patch("", response_model=EmailConfigResponse)
async def update_email_config(
    request: EmailConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(require_admin),
):
    """
    Update email configuration (admin only).
    Only provided fields will be updated.
    Passwords are encrypted before storage.
    """
    service = EmailConfigService(db)
    
    try:
        updated = await service.update_config(request, current_user_id)
        return updated
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/initialize", response_model=EmailConfigResponse)
async def initialize_email_config(
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(require_admin),
):
    """
    Initialize email configuration from environment variables (admin only).
    Should only be called once during initial setup.
    """
    service = EmailConfigService(db)
    config = await service.initialize_default_config()
    return config


@router.post("/test")
async def test_email_config(
    request: EmailConfigTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(require_admin),
):
    """
    Test email configuration by sending a test email (admin only).
    """
    service = EmailConfigService(db)
    config_dict = await service.get_decrypted_config()
    
    if not config_dict:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email configuration not found"
        )
    
    # TODO: Implement actual email sending test using the config
    # For now, just return success if config exists
    
    return {
        "success": True,
        "message": f"Test email would be sent to {request.test_email}",
        "config": {
            "smtp_host": config_dict["smtp_host"],
            "smtp_port": config_dict["smtp_port"],
            "smtp_user": config_dict["smtp_user"],
        }
    }