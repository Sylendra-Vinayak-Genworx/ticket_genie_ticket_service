import logging
from src.core.services.notification.manager import NotificationManager

logger = logging.getLogger(__name__)

# Keep a reference to the original method so we can reverse or call it
_original_channels = NotificationManager._channels

def _patched_channels(user, ntype) -> set[str]:
    # Call the original method to get the base preferences
    channels = _original_channels(user, ntype)
    
    # Forcefully append 'sse' for in-app UI delivery
    channels.add("sse")
    
    return channels

def apply_notification_patch():
    """Applies the reverseable patch to inject 'sse' into all notifications."""
    if NotificationManager._channels is not _patched_channels:
        NotificationManager._channels = staticmethod(_patched_channels)
        logger.info("notification_adapter: Successfully patched NotificationManager._channels to include SSE.")

def reverse_notification_patch():
    """Reverts the NotificationManager to its original state."""
    if NotificationManager._channels is _patched_channels:
        NotificationManager._channels = staticmethod(_original_channels)
        logger.info("notification_adapter: Reversed NotificationManager patch.")
