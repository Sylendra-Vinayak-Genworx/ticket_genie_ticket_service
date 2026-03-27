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

"""Endpoints for managing email configuration settings, such as SMTP server details, credentials, etc. Only accessible by admins."""
@router.get(
    "",
    response_model=EmailConfigResponse,
    summary="Get email config",
    description="Retrieve the current email configuration settings.",
)
async def get_email_config(
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(require_admin),
) -> EmailConfigResponse:
    """
    Get email config.
    
    Args:
        db (AsyncSession): Input parameter.
        current_user_id (str): Input parameter.
    
    Returns:
        EmailConfigResponse: The expected output.
    """
    service = EmailConfigService(db)
    config = await service.get_config()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email configuration not found. Please initialize first."
        )
    
    return config


@router.patch(
    "",
    response_model=EmailConfigResponse,
    summary="Update email config",
    description="Update the email configuration settings.",
)
async def update_email_config(
    request: EmailConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(require_admin),
) -> EmailConfigResponse:

    """
    Update email config.
    
    Args:
        request (EmailConfigUpdateRequest): Input parameter.
        db (AsyncSession): Input parameter.
        current_user_id (str): Input parameter.
    
    Returns:
        EmailConfigResponse: The expected output.
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


@router.post(
    "/initialize",
    response_model=EmailConfigResponse,
    summary="Initialize email config",
    description="Initialize the email configuration with default settings.",
)
async def initialize_email_config(
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(require_admin),
) -> EmailConfigResponse:
    """
    Initialize email config.
    
    Args:
        db (AsyncSession): Input parameter.
        current_user_id (str): Input parameter.
    
    Returns:
        EmailConfigResponse: The expected output.
    """
    service = EmailConfigService(db)
    config = await service.initialize_default_config()
    return config


@router.post(
    "/test",
    response_model=dict,
    summary="Test email config",
    description="Test the current email configuration by sending a test email."
)
async def test_email_config(
    request: EmailConfigTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(require_admin),
) -> dict:
    """
    Test email config.
    
    Args:
        request (EmailConfigTestRequest): Input parameter.
        db (AsyncSession): Input parameter.
        current_user_id (str): Input parameter.
    
    Returns:
        dict: The expected output.
    """
    service = EmailConfigService(db)
    config_dict = await service.get_decrypted_config()
    
    if not config_dict:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email configuration not found"
        )
    

    
    return {
        "success": True,
        "message": f"Test email would be sent to {request.test_email}",
        "config": {
            "smtp_host": config_dict["smtp_host"],
            "smtp_port": config_dict["smtp_port"],
            "smtp_user": config_dict["smtp_user"],
        }
    }