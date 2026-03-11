import asyncio
import logging
import sys

from src.core.services.notification.manager import notification_manager
from src.core.services.notification.sse_service import sse_bus
from src.schemas.notification_schema import TicketCreatedRequest

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

class MockAuthClient:
    async def get_user(self, user_id):
        class MockUser:
            id = user_id
            email = "test@example.com"
            preferred_mode_of_contact = "portal"
        return MockUser()

class MockDB:
    async def commit(self): pass
    async def rollback(self): pass
    async def add(self, *args): pass

async def main():
    print("Testing SSEBus...")
    
    # Start subscriber
    q = await sse_bus.subscribe("test_user_id")
    
    # Give subscriber a moment to listen
    await asyncio.sleep(1)
    
    print("Triggering notification...")
    req = TicketCreatedRequest(
        ticket_id=999,
        ticket_number="TKT-999",
        ticket_title="Test Ticket",
        customer_id="test_user_id"
    )
    
    await notification_manager.send(req, MockDB(), MockAuthClient())
    
    print("Waiting for event...")
    try:
        event = await asyncio.wait_for(q.get(), timeout=5.0)
        print("RECEIVED EVENT:", event)
    except asyncio.TimeoutError:
        print("TIMEOUT: Event not received!")

if __name__ == "__main__":
    asyncio.run(main())
