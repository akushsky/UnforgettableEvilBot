from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.core.repository_factory import repository_factory
from app.database.connection import SessionLocal
from app.models.database import OpenAIMetrics as OpenAIMetricsDB
from config.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class OpenAIMetrics:
    """Metrics for OpenAI usage tracking"""

    total_requests: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    successful_requests: int = 0
    failed_requests: int = 0
    last_request_time: Optional[datetime] = None
    requests_by_model: Dict[str, int] = field(default_factory=dict)
    tokens_by_model: Dict[str, int] = field(default_factory=dict)
    cost_by_model: Dict[str, float] = field(default_factory=dict)


class OpenAIMonitor:
    """Monitor for OpenAI API usage and costs"""

    # OpenAI pricing per 1K tokens (as of 2024)
    PRICING = {
        "gpt-4o": {
            "input": 0.005,
            "output": 0.015,
        },  # $5.00 / 1M input, $15.00 / 1M output
        "gpt-4o-mini": {
            "input": 0.00015,
            "output": 0.0006,
        },  # $0.15 / 1M input, $0.60 / 1M output
        "gpt-4": {
            "input": 0.03,
            "output": 0.06,
        },  # $30.00 / 1M input, $60.00 / 1M output
        "gpt-3.5-turbo": {
            "input": 0.0005,
            "output": 0.0015,
        },  # $0.50 / 1M input, $1.50 / 1M output
    }

    def __init__(self):
        """Initialize OpenAI monitor"""
        self.metrics = OpenAIMetrics()
        self.daily_metrics: Dict[str, OpenAIMetrics] = defaultdict(OpenAIMetrics)
        self.hourly_metrics: Dict[str, OpenAIMetrics] = defaultdict(OpenAIMetrics)
        self.recent_requests: List[Dict] = []  # Store last 10 requests

        # Load existing data from database
        self._load_from_database()

    def _load_from_database(self):
        """Load existing OpenAI metrics from database"""
        try:
            db = SessionLocal()

            # Get all metrics from database
            db_metrics = repository_factory.get_openai_metrics_repository().get_all_metrics_ordered(
                db
            )

            if not db_metrics:
                logger.info("No existing OpenAI metrics found in database")
                return

            # Reset current metrics
            self.metrics = OpenAIMetrics()
            self.daily_metrics.clear()
            self.hourly_metrics.clear()
            self.recent_requests = []

            # Process each metric from database
            for db_metric in db_metrics:
                # Update global metrics
                self.metrics.total_requests += 1
                self.metrics.total_tokens += db_metric.total_tokens
                self.metrics.total_cost_usd += db_metric.cost_usd
                self.metrics.last_request_time = db_metric.request_time

                if db_metric.success:
                    self.metrics.successful_requests += 1
                else:
                    self.metrics.failed_requests += 1

                # Update model-specific metrics
                self.metrics.requests_by_model[db_metric.model] = (
                    self.metrics.requests_by_model.get(db_metric.model, 0) + 1
                )
                self.metrics.tokens_by_model[db_metric.model] = (
                    self.metrics.tokens_by_model.get(db_metric.model, 0)
                    + db_metric.total_tokens
                )
                self.metrics.cost_by_model[db_metric.model] = (
                    self.metrics.cost_by_model.get(db_metric.model, 0.0)
                    + db_metric.cost_usd
                )

                # Update daily metrics
                day_key = db_metric.request_time.strftime("%Y-%m-%d")
                daily = self.daily_metrics[day_key]
                daily.total_requests += 1
                daily.total_tokens += db_metric.total_tokens
                daily.total_cost_usd += db_metric.cost_usd
                daily.last_request_time = db_metric.request_time
                if db_metric.success:
                    daily.successful_requests += 1
                else:
                    daily.failed_requests += 1
                daily.requests_by_model[db_metric.model] = (
                    daily.requests_by_model.get(db_metric.model, 0) + 1
                )
                daily.tokens_by_model[db_metric.model] = (
                    daily.tokens_by_model.get(db_metric.model, 0)
                    + db_metric.total_tokens
                )
                daily.cost_by_model[db_metric.model] = (
                    daily.cost_by_model.get(db_metric.model, 0.0) + db_metric.cost_usd
                )

                # Update hourly metrics
                hour_key = db_metric.request_time.strftime("%Y-%m-%d-%H")
                hourly = self.hourly_metrics[hour_key]
                hourly.total_requests += 1
                hourly.total_tokens += db_metric.total_tokens
                hourly.total_cost_usd += db_metric.cost_usd
                hourly.last_request_time = db_metric.request_time
                if db_metric.success:
                    hourly.successful_requests += 1
                else:
                    hourly.failed_requests += 1
                hourly.requests_by_model[db_metric.model] = (
                    hourly.requests_by_model.get(db_metric.model, 0) + 1
                )
                hourly.tokens_by_model[db_metric.model] = (
                    hourly.tokens_by_model.get(db_metric.model, 0)
                    + db_metric.total_tokens
                )
                hourly.cost_by_model[db_metric.model] = (
                    hourly.cost_by_model.get(db_metric.model, 0.0) + db_metric.cost_usd
                )

                # Add to recent requests (only last 10)
                if len(self.recent_requests) < 10:
                    request_info = {
                        "model": db_metric.model,
                        "tokens": db_metric.total_tokens,
                        "cost": round(db_metric.cost_usd, 6),
                        "success": db_metric.success,
                        "timestamp": db_metric.request_time.isoformat(),
                        "error": (
                            db_metric.error_message if not db_metric.success else None
                        ),
                    }
                    self.recent_requests.append(request_info)

            # Reverse recent requests to show newest first
            self.recent_requests.reverse()

            logger.info(f"Loaded {len(db_metrics)} OpenAI metrics from database")

        except Exception as e:
            logger.error(f"Failed to load OpenAI metrics from database: {e}")
        finally:
            if "db" in locals():
                db.close()

    def calculate_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Calculate cost for token usage"""
        if model not in self.PRICING:
            logger.warning(
                f"Unknown model pricing for {model}, using gpt-4o-mini as fallback"
            )
            model = "gpt-4o-mini"

        pricing = self.PRICING[model]
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]

        return input_cost + output_cost

    def record_request(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        success: bool = True,
        error: Optional[str] = None,
    ):
        """Record an OpenAI API request"""
        now = datetime.utcnow()
        total_tokens = input_tokens + output_tokens
        cost = self.calculate_cost(model, input_tokens, output_tokens)

        # Update global metrics
        self.metrics.total_requests += 1
        self.metrics.total_tokens += total_tokens
        self.metrics.total_cost_usd += cost
        self.metrics.last_request_time = now

        if success:
            self.metrics.successful_requests += 1
        else:
            self.metrics.failed_requests += 1

        # Update model-specific metrics
        self.metrics.requests_by_model[model] = (
            self.metrics.requests_by_model.get(model, 0) + 1
        )
        self.metrics.tokens_by_model[model] = (
            self.metrics.tokens_by_model.get(model, 0) + total_tokens
        )
        self.metrics.cost_by_model[model] = (
            self.metrics.cost_by_model.get(model, 0.0) + cost
        )

        # Update daily metrics
        day_key = now.strftime("%Y-%m-%d")
        daily = self.daily_metrics[day_key]
        daily.total_requests += 1
        daily.total_tokens += total_tokens
        daily.total_cost_usd += cost
        daily.last_request_time = now
        if success:
            daily.successful_requests += 1
        else:
            daily.failed_requests += 1
        daily.requests_by_model[model] = daily.requests_by_model.get(model, 0) + 1
        daily.tokens_by_model[model] = (
            daily.tokens_by_model.get(model, 0) + total_tokens
        )
        daily.cost_by_model[model] = daily.cost_by_model.get(model, 0.0) + cost

        # Update hourly metrics
        hour_key = now.strftime("%Y-%m-%d-%H")
        hourly = self.hourly_metrics[hour_key]
        hourly.total_requests += 1
        hourly.total_tokens += total_tokens
        hourly.total_cost_usd += cost
        hourly.last_request_time = now
        if success:
            hourly.successful_requests += 1
        else:
            hourly.failed_requests += 1
        hourly.requests_by_model[model] = hourly.requests_by_model.get(model, 0) + 1
        hourly.tokens_by_model[model] = (
            hourly.tokens_by_model.get(model, 0) + total_tokens
        )
        hourly.cost_by_model[model] = hourly.cost_by_model.get(model, 0.0) + cost

        # Store recent request info
        request_info = {
            "model": model,
            "tokens": total_tokens,
            "cost": round(cost, 6),
            "success": success,
            "timestamp": now.isoformat(),
            "error": error if not success else None,
        }
        self.recent_requests.append(request_info)
        # Keep only last 10 requests
        if len(self.recent_requests) > 10:
            self.recent_requests = self.recent_requests[-10:]

        # Save to database for persistence
        try:
            db = SessionLocal()
            db_metric = OpenAIMetricsDB(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
                success=success,
                error_message=error if not success else None,
                request_time=now,
            )
            db.add(db_metric)
            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Failed to save OpenAI metrics to database: {e}")
            if "db" in locals():
                db.rollback()
                db.close()

        # Log the request
        log_message = f"OpenAI request: {model}, tokens: {total_tokens} (in: {input_tokens}, out: {output_tokens}), cost: ${cost:.6f}"
        if not success and error:
            log_message += f", error: {error}"
        logger.info(log_message)

    def get_stats(self) -> Dict:
        """Get current OpenAI statistics"""
        now = datetime.utcnow()

        # Calculate recent activity (last 24 hours)
        yesterday = now - timedelta(days=1)
        recent_24h_requests = sum(
            daily.total_requests
            for day_key, daily in self.daily_metrics.items()
            if datetime.strptime(day_key, "%Y-%m-%d") >= yesterday
        )

        recent_cost = sum(
            daily.total_cost_usd
            for day_key, daily in self.daily_metrics.items()
            if datetime.strptime(day_key, "%Y-%m-%d") >= yesterday
        )

        # Calculate hourly rate (last hour)
        last_hour = now - timedelta(hours=1)
        hourly_requests: int = sum(
            hourly.total_requests
            for hour_key, hourly in self.hourly_metrics.items()
            if datetime.strptime(hour_key, "%Y-%m-%d-%H") >= last_hour
        )

        # Calculate average tokens per request
        avg_tokens_per_request = round(
            self.metrics.total_tokens / max(self.metrics.total_requests, 1), 1
        )

        # Get recent requests (last 10 requests)
        recent_requests = []
        if hasattr(self, "recent_requests"):
            recent_requests = self.recent_requests[-10:]  # Last 10 requests

        # Prepare models usage data
        models_usage = {
            model: {
                "requests": count,
                "tokens": self.metrics.tokens_by_model.get(model, 0),
                "cost": round(self.metrics.cost_by_model.get(model, 0.0), 6),
            }
            for model, count in self.metrics.requests_by_model.items()
        }

        return {
            "total_requests": self.metrics.total_requests,
            "total_tokens": self.metrics.total_tokens,
            "total_cost_usd": round(self.metrics.total_cost_usd, 6),
            "successful_requests": self.metrics.successful_requests,
            "failed_requests": self.metrics.failed_requests,
            "success_rate": round(
                self.metrics.successful_requests
                / max(self.metrics.total_requests, 1)
                * 100,
                2,
            ),
            "last_request_time": (
                self.metrics.last_request_time.isoformat()
                if self.metrics.last_request_time
                else None
            ),
            "recent_24h": recent_24h_requests,
            "cost_24h": round(recent_cost, 6),
            "avg_tokens_per_request": avg_tokens_per_request,
            "recent_requests": recent_requests,
            "models_usage": models_usage,
            "recent_1h": {"requests": hourly_requests},
            "by_model": {
                model: {
                    "requests": count,
                    "tokens": self.metrics.tokens_by_model.get(model, 0),
                    "cost_usd": round(self.metrics.cost_by_model.get(model, 0.0), 6),
                }
                for model, count in self.metrics.requests_by_model.items()
            },
            "daily_breakdown": {
                day: {
                    "requests": daily.total_requests,
                    "tokens": daily.total_tokens,
                    "cost_usd": round(daily.total_cost_usd, 6),
                }
                for day, daily in sorted(self.daily_metrics.items(), reverse=True)[
                    :7
                ]  # Last 7 days
            },
        }

    def get_cost_estimate(self, model: str, estimated_tokens: int) -> float:
        """Get cost estimate for future requests"""
        return self.calculate_cost(
            model, estimated_tokens // 2, estimated_tokens // 2
        )  # Assume 50/50 input/output split

    def cleanup_old_data(self, days_to_keep: int = 30):
        """Clean up old metrics data"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

        # Clean daily metrics
        old_days = [
            day_key
            for day_key in self.daily_metrics.keys()
            if datetime.strptime(day_key, "%Y-%m-%d") < cutoff_date
        ]
        for day_key in old_days:
            del self.daily_metrics[day_key]

        # Clean hourly metrics (keep last 7 days)
        cutoff_hour = datetime.utcnow() - timedelta(days=7)
        old_hours = [
            hour_key
            for hour_key in self.hourly_metrics.keys()
            if datetime.strptime(hour_key, "%Y-%m-%d-%H") < cutoff_hour
        ]
        for hour_key in old_hours:
            del self.hourly_metrics[hour_key]

        logger.info(
            f"Cleaned up {len(old_days)} old daily metrics and {len(old_hours)} old hourly metrics"
        )


# Global instance
openai_monitor = OpenAIMonitor()
