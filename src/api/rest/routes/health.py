from src.observability.logging.logger import get_logger
from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["Health"])
logger=get_logger(__name__)
@router.get("/")
async def health_check()-> dict:
    logger.info("health_check_called")
    return {"status": "ok"}
