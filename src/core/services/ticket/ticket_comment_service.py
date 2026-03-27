from datetime import datetime, timezone
from src.constants.enum import TicketStatus, UserRole, TicketSource
from src.core.services.ticket.ticket_base_service import TicketBaseService, fire_notification
from src.data.models.postgres.ticket_attachment import TicketAttachment
from src.data.models.postgres.ticket_comment import TicketComment
from src.schemas.notification_schema import CustomerCommentRequest, AgentCommentRequest, StatusChangedRequest
from src.schemas.ticket_schema import CommentCreateRequest

class TicketCommentService(TicketBaseService):
    async def add_comment(
        self,
        comment: CommentCreateRequest,
        current_user_id: str,
        current_user_role: str,
    ):
        """
        Add comment.
        
        Args:
            comment (CommentCreateRequest): Input parameter.
            current_user_id (str): Input parameter.
            current_user_role (str): Input parameter.
        """
        now = datetime.now(timezone.utc)

        saved = await self._comment_repo.add(TicketComment(
            ticket_id=comment.ticket_id,
            author_id=current_user_id,
            author_role=current_user_role,
            body=comment.body,
            is_internal=comment.is_internal,
            triggers_hold=comment.triggers_hold,
            triggers_resume=comment.triggers_resume,
        ))

        for blob_path in (comment.attachments or []):
            clean = blob_path.split("?")[0]
            await self._attachment_repo.add(TicketAttachment(
                ticket_id=comment.ticket_id,
                comment_id=saved.comment_id,
                file_name=clean.split("/")[-1],
                file_url=clean,
                uploaded_by_user_id=current_user_id,
            ))

        if comment.is_internal:
            return saved

        ticket = await self._ticket_repo.get_by_id(comment.ticket_id, eager=False)
        if not ticket:
            return saved

        if comment.triggers_hold and ticket.status == TicketStatus.IN_PROGRESS:
            self._sla_svc.pause_resolution_sla(ticket, now)
            ticket.status = TicketStatus.ON_HOLD
            ticket = await self._ticket_repo.save(ticket)
            await self._record_transition(
                ticket,
                from_status=TicketStatus.IN_PROGRESS,
                to_status=TicketStatus.ON_HOLD,
                changed_by=current_user_id,
                reason=f"SLA paused via comment: {comment.body[:80]}",
            )
        elif comment.triggers_resume and ticket.status == TicketStatus.ON_HOLD:
            self._sla_svc.resume_resolution_sla(ticket, now)
            ticket.status = TicketStatus.IN_PROGRESS
            ticket = await self._ticket_repo.save(ticket)
            await self._record_transition(
                ticket,
                from_status=TicketStatus.ON_HOLD,
                to_status=TicketStatus.IN_PROGRESS,
                changed_by=current_user_id,
                reason=f"SLA resumed via comment: {comment.body[:80]}",
            )

        role = UserRole(current_user_role)

        if role == UserRole.CUSTOMER and ticket.assignee_id:
            try:
                customer_user = await self._auth.get_user(current_user_id)
                customer_name = customer_user.email.split("@")[0]
            except Exception:
                customer_name = "Customer"

            fire_notification(
                request=CustomerCommentRequest(
                    ticket_id=ticket.ticket_id,
                    ticket_number=ticket.ticket_number,
                    ticket_title=ticket.title,
                    customer_name=customer_name,
                    comment_body=comment.body,
                    assignee_id=ticket.assignee_id,
                ),
                auth_client=self._auth,
            )

        elif role in (UserRole.AGENT, UserRole.LEAD, UserRole.ADMIN):
            try:
                commenter = await self._auth.get_user(current_user_id)
                agent_name = commenter.email.split("@")[0]
            except Exception:
                agent_name = "Support Agent"

            if ticket.source == TicketSource.EMAIL:
                fire_notification(
                    request=AgentCommentRequest(
                        ticket_id=ticket.ticket_id,
                        ticket_number=ticket.ticket_number,
                        ticket_title=ticket.title,
                        status=ticket.status.value,
                        severity=ticket.severity.value,
                        customer_id=ticket.customer_id,
                        agent_name=agent_name,
                        comment_body=comment.body,
                    ),
                    auth_client=self._auth,
                )
            else:
                fire_notification(
                    request=StatusChangedRequest(
                        ticket_id=ticket.ticket_id,
                        ticket_number=ticket.ticket_number,
                        ticket_title=ticket.title,
                        old_status=ticket.status.value,
                        new_status=ticket.status.value,
                        severity=ticket.severity.value,
                        customer_id=ticket.customer_id,
                        agent_name=agent_name,
                    ),
                    auth_client=self._auth,
                )

        return saved
