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

from redis.exceptions import RedisError

from src.config.settings import get_settings
from src.core.exceptions import QueueException
from src.core.logging import get_logger
from src.core.redis import RedisClient, get_redis_client

logger = get_logger(__name__)


from src.core.interfaces import MessageQueue, QueueMessage


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

        logger.info(
            "Redis Queue initialized",
            stage="QUEUE.0",
            stream=self.stream_name,
            group=self.group_name
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
                mkstream=True
            )
            logger.info("Consumer group created", stage="QUEUE.1", group=self.group_name)
        except RedisError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists, which is fine
                pass
            else:
                logger.error("Failed to create consumer group", stage="QUEUE.ERR", error=str(e))
                raise QueueException(f"Failed to create consumer group: {e}")

        self._initialized = True

    async def produce(self, payload: dict[str, Any], max_len: int = 10000) -> str:
        """
        Add a message to the queue.

        STAGE-QUEUE.PROD: Produce message

        Args:
            payload: Dictionary data to send.
            max_len: Maximum length of the stream (approximate trimming).

        Returns:
            str: The ID of the added message.
        """
        if not self._initialized:
            await self.initialize()

        try:
            # Add timestamp if not present
            if "timestamp" not in payload:
                payload["timestamp"] = datetime.utcnow().isoformat() + 'Z'

            # Redis streams store strings, so we might need to serialize nested dicts
            # But xadd handles simple dicts of string->string/number well.
            # For complex objects, JSON dump them.
            message_data = {}
            for k, v in payload.items():
                if isinstance(v, (dict, list, bool)):
                    message_data[k] = json.dumps(v)
                else:
                    message_data[k] = str(v)

            message_id = await self._redis.client.xadd(
                self.stream_name,
                message_data,
                maxlen=max_len,
                approximate=True
            )

            logger.debug("Message produced", stage="QUEUE.PROD", id=message_id)
            return message_id

        except RedisError as e:
            logger.error("Failed to produce message", stage="QUEUE.ERR", error=str(e))
            raise QueueException(f"Failed to produce message: {e}")

    async def consume(
        self,
        consumer_name: str,
        batch_size: int = 10,
        block_ms: int = 2000
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
                self.group_name,
                consumer_name,
                streams,
                count=batch_size,
                block=block_ms
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

                        messages.append(QueueMessage(
                            id=msg_id,
                            payload=parsed_data,
                            timestamp=parsed_data.get("timestamp", "")
                        ))

            return messages

        except RedisError as e:
            logger.error("Failed to consume messages", stage="QUEUE.ERR", error=str(e))
            raise QueueException(f"Failed to consume messages: {e}")

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
            raise QueueException(f"Failed to acknowledge message: {e}")

    async def start_consumer_loop(
        self,
        consumer_name: str,
        handler: Callable[[QueueMessage], Awaitable[None]],
        batch_size: int = 10
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
                            error=str(e)
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
