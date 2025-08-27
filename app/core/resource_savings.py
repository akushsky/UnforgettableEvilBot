from datetime import datetime, timedelta
from typing import Dict, List

import psutil
from sqlalchemy.orm import Session

from app.core.repository_factory import repository_factory
from app.models.database import ResourceSavings
from config.logging_config import get_logger

logger = get_logger(__name__)


class ResourceSavingsService:
    """Service for tracking and calculating resource savings from suspended users."""

    def __init__(self):
        self.logger = get_logger(__name__)
        # Average resource usage per user (calculated from historical data)
        self.avg_memory_per_user_mb = 50.0  # MB per WhatsApp connection
        self.avg_cpu_per_user_percent = 2.0  # CPU % per user
        self.avg_openai_cost_per_message_usd = 0.002  # USD per message analysis

    def calculate_savings_for_user(
        self,
        db: Session,
        user_id: int,
        period_start: datetime,
        period_end: datetime,
        reason: str = "user_suspended",
    ) -> Dict:
        """Calculate resource savings for a specific user over a time period."""
        try:
            # Get user info
            user = repository_factory.get_user_repository().get_by_id(db, user_id)
            if not user:
                return {"error": "User not found"}

            # Calculate WhatsApp connections saved
            whatsapp_connections_saved = 1 if user.whatsapp_connected else 0

            # Calculate messages that would have been processed
            messages_processed_saved = self._count_messages_in_period(
                db, user_id, period_start, period_end
            )

            # Calculate OpenAI requests saved
            # Each message typically triggers one OpenAI call
            openai_requests_saved = messages_processed_saved

            # Calculate memory savings (MB)
            memory_mb_saved = whatsapp_connections_saved * self.avg_memory_per_user_mb

            # Calculate CPU time saved (seconds)
            period_duration_hours = (period_end - period_start).total_seconds() / 3600
            cpu_seconds_saved = (
                (self.avg_cpu_per_user_percent / 100) * period_duration_hours * 3600
            )

            # Calculate cost savings
            openai_cost_saved_usd = (
                openai_requests_saved * self.avg_openai_cost_per_message_usd
            )

            # Create savings record
            savings = ResourceSavings(
                user_id=user_id,
                whatsapp_connections_saved=whatsapp_connections_saved,
                messages_processed_saved=messages_processed_saved,
                openai_requests_saved=openai_requests_saved,
                memory_mb_saved=memory_mb_saved,
                cpu_seconds_saved=cpu_seconds_saved,
                openai_cost_saved_usd=openai_cost_saved_usd,
                period_start=period_start,
                period_end=period_end,
                reason=reason,
            )

            db.add(savings)
            db.commit()

            result = {
                "user_id": user_id,
                "username": user.username,
                "whatsapp_connections_saved": whatsapp_connections_saved,
                "messages_processed_saved": messages_processed_saved,
                "openai_requests_saved": openai_requests_saved,
                "memory_mb_saved": round(memory_mb_saved, 2),
                "cpu_seconds_saved": round(cpu_seconds_saved, 2),
                "openai_cost_saved_usd": round(openai_cost_saved_usd, 4),
                "period_hours": round(period_duration_hours, 2),
                "reason": reason,
            }

            self.logger.info(
                f"Resource savings calculated for user {user_id}: {result}"
            )
            return result

        except Exception as e:
            self.logger.error(f"Error calculating savings for user {user_id}: {e}")
            db.rollback()
            return {"error": str(e)}

    def _count_messages_in_period(
        self, db: Session, user_id: int, period_start: datetime, period_end: datetime
    ) -> int:
        """Count messages that would have been processed for a user in a period."""
        # This is a simplified calculation - in reality, you'd need to track
        # actual message volume per user over time
        try:
            # Get user's monitored chats
            monitored_chats = repository_factory.get_monitored_chat_repository().get_active_chats_for_user(
                db, user_id
            )

            if not monitored_chats:
                return 0

            chat_ids = [chat.id for chat in monitored_chats]

            # Count messages in period for these chats
            messages = repository_factory.get_whatsapp_message_repository().get_messages_by_chat_ids(
                db, chat_ids, limit=10000
            )
            # Filter by period
            message_count = len(
                [
                    msg
                    for msg in messages
                    if period_start <= msg.created_at <= period_end
                ]
            )

            return message_count

        except Exception as e:
            self.logger.error(f"Error counting messages for user {user_id}: {e}")
            return 0

    def get_total_savings(self, db: Session, days_back: int = 30) -> Dict:
        """Get total resource savings across all suspended users."""
        try:
            period_start = datetime.utcnow() - timedelta(days=days_back)
            period_end = datetime.utcnow()

            # Get all savings records in the period
            savings = repository_factory.get_resource_savings_repository().get_savings_in_period(
                db, period_start, period_end
            )

            total_savings = {
                "total_whatsapp_connections_saved": sum(
                    s.whatsapp_connections_saved for s in savings
                ),
                "total_messages_processed_saved": sum(
                    s.messages_processed_saved for s in savings
                ),
                "total_openai_requests_saved": sum(
                    s.openai_requests_saved for s in savings
                ),
                "total_memory_mb_saved": round(
                    sum(s.memory_mb_saved for s in savings), 2
                ),
                "total_cpu_seconds_saved": round(
                    sum(s.cpu_seconds_saved for s in savings), 2
                ),
                "total_openai_cost_saved_usd": round(
                    sum(s.openai_cost_saved_usd for s in savings), 4
                ),
                "period_days": days_back,
                "records_count": len(savings),
            }

            return total_savings

        except Exception as e:
            self.logger.error(f"Error getting total savings: {e}")
            return {"error": str(e)}

    def get_savings_by_user(
        self, db: Session, user_id: int, days_back: int = 30
    ) -> List[Dict]:
        """Get savings history for a specific user."""
        try:
            period_start = datetime.utcnow() - timedelta(days=days_back)

            savings = repository_factory.get_resource_savings_repository().get_savings_by_user_in_period(
                db, user_id, period_start
            )

            return [
                {
                    "id": s.id,
                    "whatsapp_connections_saved": s.whatsapp_connections_saved,
                    "messages_processed_saved": s.messages_processed_saved,
                    "openai_requests_saved": s.openai_requests_saved,
                    "memory_mb_saved": round(s.memory_mb_saved, 2),
                    "cpu_seconds_saved": round(s.cpu_seconds_saved, 2),
                    "openai_cost_saved_usd": round(s.openai_cost_saved_usd, 4),
                    "period_start": s.period_start.isoformat(),
                    "period_end": s.period_end.isoformat(),
                    "reason": s.reason,
                    "created_at": s.created_at.isoformat(),
                }
                for s in savings
            ]

        except Exception as e:
            self.logger.error(f"Error getting savings for user {user_id}: {e}")
            return []

    def record_suspension_savings(
        self, db: Session, user_id: int, suspension_start: datetime
    ) -> Dict:
        """Record savings when a user is suspended."""
        try:
            # Calculate savings from suspension start to now
            period_end = datetime.utcnow()

            return self.calculate_savings_for_user(
                db, user_id, suspension_start, period_end, "user_suspended"
            )

        except Exception as e:
            self.logger.error(
                f"Error recording suspension savings for user {user_id}: {e}"
            )
            return {"error": str(e)}

    def get_current_system_savings(self) -> Dict:
        """Get current system-wide resource savings estimate."""
        try:
            # Get current system metrics
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent(interval=1)

            # Estimate savings based on suspended users
            # This would need to be enhanced with actual user data from database
            estimated_savings = {
                "current_memory_usage_mb": round(memory.used / 1024 / 1024, 2),
                "current_cpu_usage_percent": cpu_percent,
                "estimated_memory_saved_mb": 0,  # Would be calculated from suspended users
                "estimated_cpu_saved_percent": 0,  # Would be calculated from suspended users
                "timestamp": datetime.utcnow().isoformat(),
            }

            return estimated_savings

        except Exception as e:
            self.logger.error(f"Error getting current system savings: {e}")
            return {"error": str(e)}


# Global instance
resource_savings_service = ResourceSavingsService()
