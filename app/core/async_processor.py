import asyncio
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)


class TaskPriority(Enum):
    """Task priorities"""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class TaskStatus(Enum):
    """Task statuses"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AsyncTask:
    """Class for representing an asynchronous task"""

    id: str
    func: Callable
    args: tuple
    kwargs: dict
    priority: TaskPriority
    status: TaskStatus
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3


class AsyncTaskProcessor:
    """Asynchronous task processor with priorities and a retry mechanism"""

    def __init__(
        self,
        max_workers: Optional[int] = None,
        max_process_workers: Optional[int] = None,
    ):
        """Init  .

        Args:
            max_workers: Description of max_workers.
            max_process_workers: Description of max_process_workers.
        """
        # Use settings defaults if not provided
        self.max_workers = max_workers or settings.MAX_WORKERS
        self.max_process_workers = max_process_workers or settings.MAX_PROCESS_WORKERS
        self.logger = get_logger(__name__)

        # Task queues by priority (async to avoid blocking the event loop)
        self.task_queues: Dict[TaskPriority, asyncio.Queue[AsyncTask]] = {
            TaskPriority.LOW: asyncio.Queue(),
            TaskPriority.NORMAL: asyncio.Queue(),
            TaskPriority.HIGH: asyncio.Queue(),
            TaskPriority.CRITICAL: asyncio.Queue(),
        }

        # Active tasks
        self.active_tasks: Dict[str, AsyncTask] = {}
        self.completed_tasks: Dict[str, AsyncTask] = {}

        # Thread pool for CPU-intensive tasks
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self.process_pool = ProcessPoolExecutor(max_workers=max_process_workers)

        # Control flags
        self.running = False
        self._stop_event = threading.Event()

        # Store queue processing tasks
        self._queue_tasks: List[asyncio.Task] = []

        # Statistics
        self.stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "avg_processing_time": 0.0,
        }

    def start(self):
        """Start the task processor"""
        if self.running:
            self.logger.info("Async task processor is already running")
            return

        # Skip in development mode if configured
        if (
            settings.DEBUG
            and hasattr(settings, "SKIP_ASYNC_PROCESSOR")
            and settings.SKIP_ASYNC_PROCESSOR
        ):
            self.logger.info("Async task processor skipped for development")
            return

        try:
            self.running = True
            self._stop_event.clear()

            # Start handlers for each priority
            for priority in TaskPriority:
                task = asyncio.create_task(self._process_queue(priority))
                self._queue_tasks.append(task)

            self.logger.info(
                f"Async task processor started with {self.max_workers} workers"
            )
        except Exception as e:
            self.running = False
            self.logger.error(f"Failed to start async task processor: {e}")
            raise

    def stop(self):
        """Stop the task processor"""
        if not self.running:
            return

        self.logger.info("Stopping async task processor...")
        self.running = False
        self._stop_event.set()

        # Cancel all queue processing tasks
        for task in self._queue_tasks:
            if not task.done():
                task.cancel()

        # Stop pools
        try:
            self.thread_pool.shutdown(wait=True)
            self.process_pool.shutdown(wait=True)
        except Exception as e:
            self.logger.error(f"Error shutting down pools: {e}")

        self.logger.info("Async task processor stopped")

    async def submit_task(
        self,
        func: Callable,
        *args,
        priority: TaskPriority = TaskPriority.NORMAL,
        task_id: Optional[str] = None,
        max_retries: int = 3,
        **kwargs,
    ) -> str:
        """Submit a task for execution"""
        if not task_id:
            task_id = f"task_{int(time.time() * 1000)}_{id(func)}"

        task = AsyncTask(
            id=task_id,
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority,
            status=TaskStatus.PENDING,
            created_at=time.time(),
            max_retries=max_retries,
        )

        # Add to the corresponding priority queue (async, non-blocking)
        await self.task_queues[priority].put(task)
        self.active_tasks[task_id] = task
        self.stats["total_tasks"] += 1

        self.logger.debug(f"Task {task_id} submitted with priority {priority.name}")
        return task_id

    async def _process_queue(self, priority: TaskPriority):
        """Processing the queue of tasks of a specific priority"""
        self.logger.debug(f"Starting queue processor for priority {priority.name}")

        while self.running and not self._stop_event.is_set():
            try:
                # Get a task from the queue with a timeout (non-blocking for event loop)
                task = await asyncio.wait_for(
                    self.task_queues[priority].get(), timeout=1.0
                )

                # Execute the task
                await self._execute_task(task)

            except asyncio.TimeoutError:
                # Queue is empty, continue loop
                await asyncio.sleep(0.1)  # Small delay to prevent busy waiting
                continue
            except asyncio.CancelledError:
                self.logger.info(f"Queue processor for {priority.name} cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error processing queue {priority.name}: {e}")
                await asyncio.sleep(1)  # Delay before retrying

        self.logger.debug(f"Queue processor for priority {priority.name} stopped")

    async def _execute_task(self, task: AsyncTask):
        """Execute a single task"""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        try:
            self.logger.debug(
                f"Executing task {task.id} with priority {task.priority.name}"
            )

            # Determine the execution type
            if asyncio.iscoroutinefunction(task.func):
                # Asynchronous function
                result = await task.func(*task.args, **task.kwargs)
            else:
                # Synchronous function — execute in the thread pool
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.thread_pool, task.func, *task.args, **task.kwargs
                )

            # Task completed successfully
            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = time.time()

            self.stats["completed_tasks"] += 1
            self._update_avg_processing_time(task)

            self.logger.debug(f"Task {task.id} completed successfully")

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            self.logger.info(f"Task {task.id} was cancelled")
        except Exception as e:
            # Handle errors with a retry mechanism
            await self._handle_task_error(task, e)

        finally:
            # Move the task to completed
            if task.id in self.active_tasks:
                del self.active_tasks[task.id]
            self.completed_tasks[task.id] = task

    async def _handle_task_error(self, task: AsyncTask, error: Exception):
        """Handling task errors with a retry mechanism"""
        task.error = str(error)
        task.retry_count += 1

        if task.retry_count <= task.max_retries:
            # Retry the task
            self.logger.warning(
                f"Task {task.id} failed, retrying ({task.retry_count}/{task.max_retries}): {error}"
            )

            # Return the task to the queue with the same priority
            task.status = TaskStatus.PENDING
            task.started_at = None
            task.completed_at = None
            task.error = None

            # Small delay before retry
            await asyncio.sleep(min(2**task.retry_count, 60))  # Exponential backoff

            await self.task_queues[task.priority].put(task)
        else:
            # Attempt count exceeded
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()

            self.stats["failed_tasks"] += 1
            self.logger.error(
                f"Task {task.id} failed after {task.max_retries} retries: {error}"
            )

    def _update_avg_processing_time(self, task: AsyncTask):
        """Update average processing time"""
        if task.started_at and task.completed_at:
            processing_time = task.completed_at - task.started_at

            if self.stats["completed_tasks"] == 1:
                self.stats["avg_processing_time"] = processing_time
            else:
                # Compute moving average
                self.stats["avg_processing_time"] = (
                    self.stats["avg_processing_time"]
                    * (self.stats["completed_tasks"] - 1)
                    + processing_time
                ) / self.stats["completed_tasks"]

    def get_task_status(self, task_id: str) -> Optional[AsyncTask]:
        """Get task status"""
        if task_id in self.active_tasks:
            return self.active_tasks[task_id]
        elif task_id in self.completed_tasks:
            return self.completed_tasks[task_id]
        return None

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task"""
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()

            del self.active_tasks[task_id]
            self.completed_tasks[task_id] = task

            self.logger.info(f"Task {task_id} cancelled")
            return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get processor statistics"""
        queue_sizes = {
            priority.name: queue.qsize() for priority, queue in self.task_queues.items()
        }

        return {
            **self.stats,
            "active_tasks": len(self.active_tasks),
            "completed_tasks_count": len(self.completed_tasks),
            "queue_sizes": queue_sizes,
            "running": self.running,
        }

    def clear_completed_tasks(self, max_age_hours: int = 24):
        """Cleanup of old completed tasks"""
        cutoff_time = time.time() - (max_age_hours * 3600)

        tasks_to_remove = [
            task_id
            for task_id, task in self.completed_tasks.items()
            if task.completed_at and task.completed_at < cutoff_time
        ]

        for task_id in tasks_to_remove:
            del self.completed_tasks[task_id]

        self.logger.info(f"Cleared {len(tasks_to_remove)} old completed tasks")


# Global instance of the task processor
task_processor = AsyncTaskProcessor()


# Decorator for asynchronous task execution
def async_task(priority: TaskPriority = TaskPriority.NORMAL, max_retries: int = 3):
    """Decorator for asynchronous function execution"""

    def decorator(func):
        """Decorator function.

        Args:
            func: Description of func.
        """

        async def wrapper(*args, **kwargs):
            """Wrapper."""
            task_id = await task_processor.submit_task(
                func, *args, priority=priority, max_retries=max_retries, **kwargs
            )
            return task_id

        return wrapper

    return decorator
