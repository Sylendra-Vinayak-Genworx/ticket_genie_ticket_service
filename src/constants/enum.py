"""
src/constants/enum.py
~~~~~~~~~~~~~~~~~~~~~
Updated enums with ASSIGNING routing status for atomic assignment locking.
"""
import enum


class UserRole(str, enum.Enum):
    CUSTOMER = "user"
    AGENT = "support_agent"
    LEAD = "team_lead"
    ADMIN = "admin"


class TicketStatus(str, enum.Enum):
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class TicketSource(str, enum.Enum):
    UI = "UI"
    EMAIL = "EMAIL"


class Severity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Priority(str, enum.Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class Environment(str, enum.Enum):
    PROD = "PROD"
    STAGE = "STAGE"
    DEV = "DEV"


class EventType(str, enum.Enum):
    CREATED = "CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    ASSIGNED = "ASSIGNED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    SEVERITY_CHANGED = "SEVERITY_CHANGED"
    SLA_BREACHED = "SLA_BREACHED"
    ESCALATED = "ESCALATED"
    COMMENT_ADDED = "COMMENT_ADDED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class NotificationChannel(str, enum.Enum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"


class NotificationStatus(str, enum.Enum):
    SENT = "SENT"
    FAILED = "FAILED"
    PENDING = "PENDING"


class MatchField(str, enum.Enum):
    SUBJECT = "SUBJECT"
    BODY = "BODY"
    BOTH = "BOTH"


class QueueType(str, enum.Enum):
    DIRECT = "DIRECT"  # assigned to specific agent or team
    OPEN = "OPEN"      # unassigned, in open queue


class RoutingStatus(str, enum.Enum):
    """
    Ticket routing status in the assignment pipeline.
    
    Values
    ------
    SUCCESS : str
        Ticket successfully assigned to an agent (assignee_id set)
    AI_FAILED : str
        AI/skill-based routing failed, ticket in team queue or OPEN
    ESCALATED : str
        Ticket escalated to lead's team due to SLA breach
    ASSIGNING : str
        Ticket currently being assigned (atomic lock to prevent races)
    """
    SUCCESS = "SUCCESS"
    AI_FAILED = "AI_FAILED"
    ESCALATED = "ESCALATED"
    ASSIGNING = "ASSIGNING"  # NEW: Prevents concurrent assignment


class CustomerTier(str, enum.Enum):
    FREE = "FREE"
    STANDARD = "STANDARD"
    ENTERPRISE = "ENTERPRISE"


class ProficiencyLevel(str, enum.Enum):
    """
    Agent proficiency levels for skill-based routing.
    Used in agent_skills table.
    """
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    EXPERT = "expert"