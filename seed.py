"""
Seed realistic test tickets with embeddings for testing similarity search.

Usage (run from project root):
    python seed_test_tickets.py
"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import random

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR
if not (PROJECT_ROOT / ".env").exists():
    PROJECT_ROOT = SCRIPT_DIR.parent

os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import text
from src.data.clients.postgres_client import AsyncSessionFactory
from src.core.services.ticket_similarity_service import get_similarity_service


CUSTOMERS = [
  "4f5e4443-df8b-4806-b5d1-258761b31c39",
  "62da9483-b96a-493d-983c-e04e5cc221eb"
]

AGENTS = [
    "134995d2-4bd1-4783-b37e-7cac5ec4372e",
    "4d08d2eb-7c09-434a-b8a7-debd6ae7b893"
    
]
TEST_TICKETS = [
    {
        "title": "Cannot log in to my account",
        "description": "I'm trying to log in but it says my password is incorrect. I'm sure I'm using the right password. I tried resetting it but didn't receive the email. This is urgent as I need to access my bookings for tomorrow's show.",
        "solution": "Issue resolved: Password reset email was being blocked by spam filter. User checked spam folder and found the email. Also whitelisted noreply@bookmyticket.com for future communications. User successfully reset password and logged in.",
        "product": "bookmyticket",
        "severity": "HIGH",
        "priority": "P1",
        "area_of_concern": "Login & Authentication",
    },
    {
        "title": "Account locked after multiple login attempts",
        "description": "My account got locked after I tried logging in 5 times with wrong password. Now I can't access my bookings. This is urgent as I have a concert tonight and need to download my tickets.",
        "solution": "Account lock is a security feature that auto-expires after 30 minutes. For immediate access, verified user identity via email confirmation and manually unlocked the account. User successfully logged in and downloaded tickets.",
        "product": "bookmyticket",
        "severity": "HIGH",
        "priority": "P1",
        "area_of_concern": "Login & Authentication",
    },
    {
        "title": "Two-factor authentication not working",
        "description": "I enabled 2FA for extra security but I'm not receiving the verification codes on my phone. I've tried both SMS and email options. My phone number is correct and my email is working fine.",
        "solution": "Phone number was stored with incorrect country code format. Updated from '9876543210' to '+919876543210' format. Also cleared 2FA cache. User now receives OTP codes successfully via both SMS and email.",
        "product": "bookmyticket",
        "severity": "MEDIUM",
        "priority": "P2",
        "area_of_concern": "Login & Authentication",
    },
    {
        "title": "Payment failed but money was deducted from account",
        "description": "I tried to book tickets for a concert yesterday. The payment page showed an error and said payment failed, but Rs. 2500 was deducted from my bank account. Transaction ID: TXN789456123. No tickets were generated. Need urgent refund.",
        "solution": "Payment gateway timeout caused the issue - payment was received but confirmation failed to reach our system. Located the transaction in payment logs. Completed the booking and sent tickets to user's email. No refund needed as booking was successful.",
        "product": "bookmyticket",
        "severity": "CRITICAL",
        "priority": "P0",
        "area_of_concern": "Payment & Billing",
    },
    {
        "title": "Credit card keeps getting declined during payment",
        "description": "My credit card keeps getting declined when I try to buy tickets. The card is active and has sufficient balance. I can use it on other websites without any issues. Tried 3 times already. Very frustrating!",
        "solution": "Card issuer had flagged our domain as suspicious due to unusual transaction pattern. User contacted their bank and whitelisted bookmyticket.com. Payment successful on next attempt. Also added clearer error messaging for similar cases.",
        "product": "bookmyticket",
        "severity": "HIGH",
        "priority": "P1",
        "area_of_concern": "Payment & Billing",
    },
    {
        "title": "Refund not received after cancellation",
        "description": "I cancelled my booking 2 weeks ago as per your cancellation policy but haven't received the refund yet. Cancellation ID: CXL445566. Amount: Rs. 1800. My bank says they haven't received any refund request from your end.",
        "solution": "Refund was processed but to an old expired card ending in 4567. User updated payment method to new card ending in 8901. Reprocessed refund to new card. Amount reflected in user's account within 3 business days.",
        "product": "bookmyticket",
        "severity": "HIGH",
        "priority": "P1",
        "area_of_concern": "Cancellation & Refund",
    },
    {
        "title": "Tickets not received after successful payment",
        "description": "I completed the payment 3 hours ago and got payment confirmation SMS, but I didn't receive the tickets via email or SMS. Payment was successful and amount was deducted. Booking reference: BK123456. Show is tomorrow, need tickets urgently!",
        "solution": "Email was sent to 'user@gmial.com' instead of 'user@gmail.com' due to typo in registration. Resent tickets to correct email address. Also sent backup copy via SMS. Added email confirmation step during registration to prevent similar issues.",
        "product": "bookmyticket",
        "severity": "CRITICAL",
        "priority": "P0",
        "area_of_concern": "Ticket Booking",
    },
    {
        "title": "Cannot select seats for movie booking",
        "description": "The seat selection screen is not loading properly. I can see the seating layout and available seats highlighted in green, but when I click on them nothing happens. Tried on Chrome, Firefox, and Edge browsers. Also cleared cache.",
        "solution": "Issue caused by outdated browser cache conflicting with new seat selection UI update. Cleared application cache resolved the issue. Instructions sent to user: Settings > Privacy > Clear browsing data > Cached images and files. Booking completed successfully.",
        "product": "bookmyticket",
        "severity": "MEDIUM",
        "priority": "P2",
        "area_of_concern": "Seat Selection",
    },
    {
        "title": "Wrong show timing displayed on ticket",
        "description": "I booked tickets for 7:00 PM show yesterday but the ticket shows 9:00 PM. This is definitely not what I selected during booking. I have screenshots of my booking showing 7 PM. The 9 PM show doesn't work for me.",
        "solution": "Theater updated show timing from 7 PM to 9 PM after booking was made due to technical issues. System didn't send auto-notification to customers. Offered two options: 1) Refund, or 2) Different date same time. User chose refund.",
        "product": "bookmyticket",
        "severity": "HIGH",
        "priority": "P1",
        "area_of_concern": "Ticket Booking",
    },
    {
        "title": "App crashes when trying to view booking history",
        "description": "The mobile app crashes every time I try to view my booking history. The app opens fine and home screen works, but clicking on 'My Bookings' causes immediate crash. Using Android 13, app version 3.2.1. Need to access my upcoming concert tickets urgently.",
        "solution": "Known bug in version 3.2.1 when loading booking history with more than 50 bookings. Pushed emergency hotfix version 3.2.2 to Play Store. User updated app and issue resolved. All booking history now loads correctly with pagination.",
        "product": "bookmyticket",
        "severity": "HIGH",
        "priority": "P1",
        "area_of_concern": "Mobile App",
    },
    {
        "title": "Cannot download tickets from iOS app",
        "description": "The download ticket button in the iOS app doesn't work. When I tap it, it shows 'downloading' spinner for 2 seconds then nothing happens. No error message either. Need to download tickets for tomorrow's event. iPhone 14, iOS 16.5.",
        "solution": "iOS 16 requires explicit storage permission for downloads. User hadn't granted permission. Solution: Settings > BookMyTicket > Photos > Allow 'Read and Write'. Also updated app to show permission prompt automatically. User successfully downloaded all tickets.",
        "product": "bookmyticket",
        "severity": "MEDIUM",
        "priority": "P2",
        "area_of_concern": "Mobile App",
    },
    {
        "title": "Cancel button is disabled, cannot cancel booking",
        "description": "I need to cancel my booking as I can't attend the event due to emergency. But the cancel button is grayed out and not clickable. Event is in 3 days, so according to your policy I should be able to cancel. Booking ID: BK789012.",
        "solution": "Event organizer had disabled cancellations 72 hours before event (stricter than our standard policy). For this emergency case, made exception and processed manual cancellation with 75% refund. Refund processed successfully.",
        "product": "bookmyticket",
        "severity": "MEDIUM",
        "priority": "P2",
        "area_of_concern": "Cancellation & Refund",
    },
    {
        "title": "Search not showing newly released movies",
        "description": "When I search for movies released this week, nothing shows up. But I can see those same movies on the homepage under 'Now Showing'. Search seems broken. Tried searching by movie name, actor name, nothing works for new releases.",
        "solution": "Search index service hadn't run in 48 hours due to failed cron job. Manually triggered full reindex. All new content now searchable. Fixed the cron job scheduling issue. Search now updates every 2 hours automatically.",
        "product": "bookmyticket",
        "severity": "MEDIUM",
        "priority": "P2",
        "area_of_concern": "Website & UI",
    },
    {
        "title": "Not receiving any booking confirmation emails",
        "description": "I made 3 bookings in the last week but didn't receive any confirmation emails for any of them. I can see all bookings in my account, so they were successful. My email address is correct in profile. Checked spam folder too.",
        "solution": "Email delivery service had IP reputation issue causing emails to be rejected by Gmail. Switched to backup SMTP relay. Manually resent all 3 confirmation emails. User received all emails. Also whitelisted our domain to prevent future filtering.",
        "product": "bookmyticket",
        "severity": "MEDIUM",
        "priority": "P2",
        "area_of_concern": "Notifications & Alerts",
    },
    {
        "title": "Cannot update email address in my profile",
        "description": "I'm trying to change my registered email address from old company email to personal email, but it says 'email already in use'. But it's my own email! My old email is no longer accessible, so I need to update it urgently.",
        "solution": "User had accidentally created a second account with new email last month. Found both accounts. Merged accounts, consolidated all booking history to primary account. Set new email as primary. Deleted duplicate account. All data preserved.",
        "product": "bookmyticket",
        "severity": "LOW",
        "priority": "P3",
        "area_of_concern": "Account Management",
    },
    {
        "title": "How to permanently delete my account and all data",
        "description": "I want to permanently delete my BookMyTicket account and all associated personal data as per GDPR and data privacy regulations. I don't see any account deletion option in settings. Please guide me on the process.",
        "solution": "Sent account deletion form link via email. User filled form and confirmed deletion request. As per policy: 30-day grace period before permanent deletion. All data (profile, bookings, payment info) will be permanently deleted. Confirmation email sent with deletion date.",
        "product": "bookmyticket",
        "severity": "LOW",
        "priority": "P3",
        "area_of_concern": "Account Management",
    },
]


async def get_next_ticket_number(session) -> str:
    result = await session.execute(
        text("SELECT MAX(ticket_number) FROM tickets WHERE ticket_number LIKE 'TKT-%'")
    )
    last = result.scalar()
    next_num = (int(last.split('-')[1]) + 1) if last else 1
    return f"TKT-{next_num:04d}"


async def get_area_id(session, area_name: str) -> int:
    result = await session.execute(
        text("SELECT area_id, name FROM areas_of_concern ORDER BY area_id")
    )
    rows = result.fetchall()
    for area_id, name in rows:
        if name.lower() == area_name.lower():
            return area_id
    available = ", ".join(f"'{n}'" for _, n in rows)
    raise ValueError(f"area_of_concern '{area_name}' not found. Available: {available}")


async def create_test_ticket(session, ticket_data: dict, customer_id: str, agent_id: str, similarity_service):
    ticket_number = await get_next_ticket_number(session)
    area_id = await get_area_id(session, ticket_data["area_of_concern"])

    days_ago = random.randint(7, 30)
    created_at = datetime.now() - timedelta(days=days_ago)
    resolution_hours = random.uniform(0.5, 4)
    resolved_at = created_at + timedelta(hours=resolution_hours)

    insert_ticket = text("""
        INSERT INTO tickets (
            ticket_number, title, description, product, environment,
            area_of_concern, severity, priority, status, source,
            customer_id, assignee_id, queue_type, routing_status,
            resolution_sla_total_pause_duration, escalation_level,
            is_escalated, is_breached, auto_closed,
            created_at, updated_at, resolution_sla_completed_at
        ) VALUES (
            :ticket_number, :title, :description, :product, 'PROD',
            :area_id, :severity, :priority, 'RESOLVED', 'UI',
            :customer_id, :agent_id, 'DIRECT', 'SUCCESS',
            0, 0,
            false, false, false,
            :created_at, :updated_at, :resolution_sla_completed_at
        ) RETURNING ticket_id
    """)

    result = await session.execute(
        insert_ticket,
        {
            "ticket_number": ticket_number,
            "title": ticket_data["title"],
            "description": ticket_data["description"],
            "product": ticket_data["product"],
            "area_id": area_id,
            "severity": ticket_data["severity"],
            "priority": ticket_data["priority"],
            "customer_id": customer_id,
            "agent_id": agent_id,
            "created_at": created_at,
            "updated_at": resolved_at,
            "resolution_sla_completed_at": resolved_at,
        }
    )

    ticket_id = result.scalar()

    insert_comment = text("""
        INSERT INTO ticket_comments (
            ticket_id, author_id, author_role, body,
            is_internal, is_mandatory_note, triggers_hold, triggers_resume,
            created_at
        ) VALUES (
            :ticket_id, :agent_id, 'AGENT', :body,
            false, false, false, false,
            :created_at
        )
    """)

    comment_time = created_at + timedelta(hours=max(resolution_hours - 0.5, 0.1))
    await session.execute(
        insert_comment,
        {
            "ticket_id": ticket_id,
            "agent_id": agent_id,
            "body": ticket_data["solution"],
            "created_at": comment_time,
        }
    )

    text_to_embed = f"{ticket_data['title']}\n\n{ticket_data['description']}"
    await similarity_service.generate_and_store_embedding(
        ticket_id=ticket_id,
        content=text_to_embed,
        session=session
    )

    return ticket_id, ticket_number


async def seed_test_tickets():
    print("=" * 70)
    print("SEED TEST TICKETS FOR SIMILARITY SEARCH")
    print("=" * 70)
    print()
    print(f"📁 Working directory: {os.getcwd()}")

    if not Path(".env").exists():
        print("❌ ERROR: .env file not found!")
        print("Run from: cd /home/sylendra/projects/ticketing_genie/backend/ticketing_service")
        return

    print("✓ Found .env file\n")

    similarity_service = get_similarity_service()

    async with AsyncSessionFactory() as session:
        print(f"✓ Using your actual database users:")
        print(f"  Customers: {len(CUSTOMERS)} users")
        print(f"  Agents: {len(AGENTS)} users\n")
        print(f"Creating {len(TEST_TICKETS)} realistic test tickets...\n")

        success_count = 0
        error_count = 0

        for i, ticket_data in enumerate(TEST_TICKETS, 1):
            try:
                customer_id = random.choice(CUSTOMERS)
                agent_id = random.choice(AGENTS)

                # Savepoint per ticket — failure rolls back only this ticket
                await session.begin_nested()

                ticket_id, ticket_number = await create_test_ticket(
                    session, ticket_data, customer_id, agent_id, similarity_service
                )

                await session.commit()  # releases savepoint
                success_count += 1

                title_preview = ticket_data['title'][:55] + "..." if len(ticket_data['title']) > 55 else ticket_data['title']
                print(f"✓ [{i:2d}/{len(TEST_TICKETS)}] {ticket_number}: {title_preview}")

            except Exception as e:
                await session.rollback()  # rolls back to savepoint only
                error_count += 1
                print(f"✗ [{i:2d}/{len(TEST_TICKETS)}] Failed: {ticket_data['title'][:50]}...")
                print(f"   Error: {e}")

        await session.commit()  # final commit

        print()
        print("=" * 70)
        print("SEEDING COMPLETE")
        print("=" * 70)
        print(f"  ✓ Created:  {success_count} tickets")
        print(f"  ✗ Failed:   {error_count} tickets")
        print(f"  Total:      {len(TEST_TICKETS)} tickets")
        print("=" * 70)

        if success_count > 0:
            print()
            print("✅ TEST TICKETS CREATED SUCCESSFULLY!")
            print()
            print("🧪 TEST THE FEATURE NOW:")
            print()
            print("1️⃣  Test Backend API:")
            print("   curl 'http://localhost:8000/api/tickets/similarity?query=cannot+login+password+issue'")
            print()
            print("2️⃣  Test Frontend:")
            print("   • Go to: http://localhost:5173/tickets/create")
            print("   • Type: 'I cannot log in to my account'")
            print("   • Should see 2-3 similar tickets with solutions!")
            print()
            print("3️⃣  View Your Test Tickets:")
            print("   • Login as agent")
            print("   • Filter by: Status = RESOLVED, Search 'TKT-'")
            print()


if __name__ == "__main__":
    print()
    print("🚀 Starting test data seeding...")
    print()
    try:
        asyncio.run(seed_test_tickets())
    except KeyboardInterrupt:
        print("\n\n⚠️  Seeding cancelled by user")
    except Exception as e:
        print(f"\n\n❌ Seeding failed: {e}")
        import traceback
        traceback.print_exc()