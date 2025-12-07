#!/usr/bin/env python3
"""
Redis Streams Message Queue Implementation

This module implements a robust message queue using Redis Streams.
It supports producer-consumer patterns for asynchronous processing of tasks
(e.g., logging, analytics, background jobs).

Architectural Decision: Redis Streams
- Persistent, ordered log of events
- Consumer groups for load balancing
- Acknowledgement mechanism (XACK) for reliability
- Built-in blocking reads for efficiency

Author: Senior Solution Architect
Date: 2025-12-05
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from aioresilience import BasicLoadShedder
from redis.exceptions import RedisError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from src.core.config.settings import get_settings
from src.core.exceptions.base import QueueError, QueueFullError
from src.core.interfaces import MessageQueue, QueueMessage
from src.core.logging.logger import get_logger
from src.infrastructure.cache.redis_client import RedisClient, get_redis_client
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

logger = get_logger(__name__)


class RedisQueue(MessageQueue):
    """
    Redis Streams-based message queue wrapper.

    STAGE-QUEUE: Queue operations

    This class handles:
    - Adding messages to a stream (Producer)
    - Reading messages via consumer groups (Consumer)
    - Acknowledging processed messages
    - Handling pending/failed messages (DLQ concept can be built on top)
    """

    def __init__(self, stream_name: str, group_name: str = "default_group"):
        """
        Initialize the Redis Queue.

        Args:
            stream_name: Name of the Redis stream key.
            group_name: Name of the consumer group.
        """
        self.settings = get_settings()
        self.stream_name = f"queue:{stream_name}"
        self.group_name = group_name
        self._redis: RedisClient | None = None
        self._initialized = False
        self._metrics = get_metrics_collector()

        # Backpressure configuration
        self.max_depth = self.settings.queue.QUEUE_MAX_DEPTH
        self.backpressure_threshold = self.settings.queue.QUEUE_BACKPRESSURE_THRESHOLD
        self.backpressure_max_retries = self.settings.queue.QUEUE_BACKPRESSURE_MAX_RETRIES
        self.backpressure_base_delay = self.settings.queue.QUEUE_BACKPRESSURE_BASE_DELAY
        self.backpressure_max_delay = self.settings.queue.QUEUE_BACKPRESSURE_MAX_DELAY

        # Load shedding (if enabled)
        self.load_shedder = None
        if self.settings.queue.QUEUE_LOAD_SHEDDING_ENABLED:
            self.load_shedder = BasicLoadShedder(
                max_requests=self.settings.queue.QUEUE_LOAD_SHEDDING_MAX_REQUESTS
            )

        logger.info(
            "Redis Queue initialized",
            stage="QUEUE.0",
            stream=self.stream_name,
            group=self.group_name,
            max_depth=self.max_depth,
            backpressure_threshold=self.backpressure_threshold,
            load_shedding_enabled=self.settings.queue.QUEUE_LOAD_SHEDDING_ENABLED,
        )

    async def initialize(self) -> None:
        """
        Initialize Redis connection and consumer group.

        STAGE-QUEUE.1: Initialization
        """
        if self._initialized:
            return

        self._redis = get_redis_client()
        await self._redis.connect()

        # Ensure consumer group exists
        try:
            # MKSTREAM option creates the stream if it doesn't exist
            await self._redis.client.xgroup_create(
                self.stream_name,
                self.group_name,
                id="0",  # Start from beginning
                mkstream=True,
            )
            logger.info("Consumer group created", stage="QUEUE.1", group=self.group_name)
        except RedisError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists, which is fine
                pass
            else:
                logger.error("Failed to create consumer group", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to create consumer group: {e}")

        self._initialized = True

    async def produce(self, payload: dict[str, Any], max_len: int | None = None) -> str:
        """
        Add a message to the queue with backpressure handling.

        STAGE-QUEUE.PROD: Produce message

        Args:
            payload: Dictionary data to send.
            max_len: Maximum length of the stream (approximate trimming).
                If None, uses configured max_depth.

        Returns:
            str: The ID of the added message.
        """
        if not self._initialized:
            await self.initialize()

        # Use configured max_len if not provided
        if max_len is None:
            max_len = self.max_depth

        # Record produce attempt
        self._metrics.record_queue_produce_attempt("redis")

        try:
            # Check current stream length for backpressure
            stream_length = await self._redis.client.xlen(self.stream_name)

            # Record current queue depth
            self._metrics.record_queue_depth(self.stream_name, stream_length)

            # Check load shedding first (if enabled)
            if self.load_shedder is not None:
                if not await self.load_shedder.accept():
                    self._metrics.record_queue_produce_failure("redis", "load_shedding")
                    logger.warning(
                        "Load shedding active - rejecting request",
                        stage="QUEUE.LOAD_SHEDDING",
                        stream=self.stream_name,
                    )
                    raise QueueFullError(f"Load shedding active for queue {self.stream_name}")

            # Check if we're approaching capacity (backpressure threshold)
            if stream_length >= int(self.backpressure_threshold * max_len):
                if stream_length >= max_len:
                    # Queue is full - apply backpressure with retries
                    logger.warning(
                        "Queue at capacity, applying backpressure",
                        stage="QUEUE.BACKPRESSURE",
                        stream=self.stream_name,
                        current_length=stream_length,
                        max_length=max_len,
                        retries=self.backpressure_max_retries,
                    )

                    # Use tenacity for retry with exponential backoff
                    message_id = await self._produce_with_backpressure(payload, max_len)
                    self._metrics.record_queue_produce_success("redis")
                    return message_id
                else:
                    # Approaching capacity - log warning
                    logger.warning(
                        "Queue approaching capacity",
                        stage="QUEUE.WARNING",
                        stream=self.stream_name,
                        current_length=stream_length,
                        max_length=max_len,
                        utilization=round(stream_length / max_len * 100, 1),
                    )

            # Normal produce operation
            message_id = await self._produce_message(payload, max_len)
            self._metrics.record_queue_produce_success("redis")
            return message_id

        except RedisError as e:
            self._metrics.record_queue_produce_failure("redis", "redis_error")
            logger.error("Failed to produce message", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to produce message: {e}")
        except QueueFullError:
            # Re-raise QueueFullError (already logged and metrics recorded)
            raise

    async def _produce_with_backpressure(self, payload: dict[str, Any], max_len: int) -> str:
        """
        Produce message with backpressure retry logic.

        Args:
            payload: Message payload
            max_len: Maximum stream length

        Returns:
            str: Message ID

        Raises:
            QueueFullError: When all retries are exhausted
        """

        @retry(
            stop=stop_after_attempt(self.backpressure_max_retries),
            wait=wait_exponential_jitter(
                initial=self.backpressure_base_delay, max=self.backpressure_max_delay
            ),
            retry=retry_if_exception_type(QueueFullError),
            before_sleep=lambda retry_state: logger.info(
                "Backpressure retry",
                stage="QUEUE.RETRY",
                attempt=retry_state.attempt_number,
                delay=round(retry_state.idle_for, 3),
                stream=self.stream_name,
            ),
        )
        async def _retry_produce():
            # Check stream length on each retry
            stream_length = await self._redis.client.xlen(self.stream_name)

            if stream_length >= max_len:
                self._metrics.record_queue_backpressure_retry("redis")
                raise QueueFullError(
                    f"Queue full after {self.backpressure_max_retries} retries: "
                    f"{stream_length}/{max_len} messages in {self.stream_name}"
                )

            # Try to produce
            return await self._produce_message(payload, max_len)

        try:
            return await _retry_produce()
        except QueueFullError:
            self._metrics.record_queue_produce_failure("redis", "queue_full")
            raise

    async def _produce_message(self, payload: dict[str, Any], max_len: int) -> str:
        """
        Internal method to produce a single message.

        Args:
            payload: Message payload
            max_len: Maximum stream length

        Returns:
            str: Message ID
        """
        # Add timestamp if not present
        if "timestamp" not in payload:
            payload["timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Redis streams store strings, so we might need to serialize nested dicts
        # But xadd handles simple dicts of string->string/number well.
        # For complex objects, JSON dump them.
        message_data = {}
        for k, v in payload.items():
            if isinstance(v, dict | list | bool):
                message_data[k] = json.dumps(v)
            else:
                message_data[k] = str(v)

        message_id = await self._redis.client.xadd(
            self.stream_name, message_data, maxlen=max_len, approximate=True
        )

        logger.debug("Message produced", stage="QUEUE.PROD", id=message_id)
        return message_id

    async def consume(
        self, consumer_name: str, batch_size: int = 10, block_ms: int = 2000
    ) -> list[QueueMessage]:
        """
        Consume messages from the queue.

        STAGE-QUEUE.CONS: Consume messages

        Args:
            consumer_name: Unique name for this consumer instance.
            batch_size: Number of messages to fetch.
            block_ms: Time to block waiting for messages (0 for infinite).

        Returns:
            List[QueueMessage]: List of received messages.
        """
        if not self._initialized:
            await self.initialize()

        try:
            # Read from consumer group
            # ">" means "messages never delivered to other consumers"
            streams = {self.stream_name: ">"}

            response = await self._redis.client.xreadgroup(
                self.group_name, consumer_name, streams, count=batch_size, block=block_ms
            )

            messages = []
            if response:
                # response format: [[stream_name, [[id, {data}]]]]
                for stream, msg_list in response:
                    for msg_id, msg_data in msg_list:
                        # Parse data back to native types if needed
                        parsed_data = {}
                        for k, v in msg_data.items():
                            try:
                                # Try to parse JSON if it looks like it
                                if v.startswith("{") or v.startswith("["):
                                    parsed_data[k] = json.loads(v)
                                else:
                                    parsed_data[k] = v
                            except (json.JSONDecodeError, AttributeError):
                                parsed_data[k] = v

                        messages.append(
                            QueueMessage(
                                id=msg_id,
                                payload=parsed_data,
                                timestamp=parsed_data.get("timestamp", ""),
                            )
                        )

            return messages

        except RedisError as e:
            logger.error("Failed to consume messages", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to consume messages: {e}")

    async def acknowledge(self, message_id: str) -> None:
        """
        Acknowledge a processed message.

        STAGE-QUEUE.ACK: Acknowledge message

        Args:
            message_id: The ID of the message to acknowledge.
        """
        if not self._initialized:
            await self.initialize()

        try:
            await self._redis.client.xack(self.stream_name, self.group_name, message_id)
        except RedisError as e:
            logger.error("Failed to acknowledge message", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to acknowledge message: {e}")

    async def start_consumer_loop(
        self,
        consumer_name: str,
        handler: Callable[[QueueMessage], Awaitable[None]],
        batch_size: int = 10,
    ) -> None:
        """
        Start a continuous consumer loop.

        Args:
            consumer_name: Unique consumer name.
            handler: Async function to process each message.
            batch_size: Batch size.
        """
        logger.info("Starting consumer loop", stage="QUEUE.LOOP", consumer=consumer_name)

        while True:
            try:
                messages = await self.consume(consumer_name, batch_size=batch_size)

                for msg in messages:
                    try:
                        # Process message
                        await handler(msg)

                        # Acknowledge success
                        await self.acknowledge(msg.id)

                    except Exception as e:
                        logger.error(
                            "Error processing message",
                            stage="QUEUE.PROC_ERR",
                            id=msg.id,
                            error=str(e),
                        )
                        # Logic for DLQ or retry could go here

                # Small sleep if no messages to prevent tight loop if block_ms is low
                if not messages:
                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.error("Consumer loop error", stage="QUEUE.LOOP_ERR", error=str(e))
                await asyncio.sleep(5)  # Backoff on error

    async def close(self) -> None:
        """Close the connection (no-op for Redis as client is shared)."""
        pass
