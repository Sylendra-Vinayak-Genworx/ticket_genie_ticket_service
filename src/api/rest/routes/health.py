from src.observability.logging.logger import get_logger
from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["Health"])
logger=get_logger(__name__)
@router.get(
    "/",
    response_model=dict,
    summary="Health check",
    description="Check the health status of the service."
)
async def health_check()-> dict:
    """
    Health check.
    
    Returns:
        dict: The expected output.
    """
    logger.info("health_check_called")
    return {"status": "ok"}
