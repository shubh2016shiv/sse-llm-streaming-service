"""
Message Queue Factory

Factory pattern for creating message queue instances based on type.
Supports Redis and Kafka queue implementations.

NOTE: This factory is currently not integrated into the application.
The QUEUE_TYPE setting exists but is not being read by any application code.
To use this factory, callers must explicitly pass the queue_type parameter.
For automatic configuration-based selection, use get_message_queue() helper function.
"""

from src.core.interfaces.message_queue import MessageQueue
from src.infrastructure.message_queue.kafka_queue import KafkaQueue
from src.infrastructure.message_queue.redis_queue import RedisQueue


class MessageQueueFactory:
    """
    Factory for creating message queue instances.

    Supports:
    - Redis Streams (RedisQueue)
    - Kafka (KafkaQueue)
    """

    def __init__(self):
        """Initialize the message queue factory."""
        self._queue_types = {
            "redis": RedisQueue,
            "kafka": KafkaQueue,
        }

    def get(self, queue_type: str, topic: str, group_name: str = "default_group") -> MessageQueue:
        """
        Get a message queue instance.

        Args:
            queue_type: Type of queue ("redis" or "kafka")
            topic: Topic/stream name
            group_name: Consumer group name (default: "default_group")

        Returns:
            MessageQueue: Instance of the requested queue type

        Raises:
            ValueError: If queue_type is not supported
        """
        queue_type_lower = queue_type.lower()

        if queue_type_lower not in self._queue_types:
            raise ValueError(
                f"Unknown queue type: {queue_type}. "
                f"Available types: {', '.join(self._queue_types.keys())}"
            )

        queue_class = self._queue_types[queue_type_lower]

        # Create instance based on queue type
        # Note: RedisQueue and KafkaQueue have different constructor signatures
        if queue_type_lower == "redis":
            return queue_class(stream_name=topic, group_name=group_name)
        else:  # queue_type_lower == "kafka" (guaranteed by validation above)
            return queue_class(topic_name=topic, group_id=group_name)

    def get_available(self) -> list[str]:
        """
        Get list of available queue types.

        Returns:
            list[str]: List of supported queue type names
        """
        return list(self._queue_types.keys())


# ============================================================================
# Helper Function for Configuration-Based Selection
# ============================================================================

def get_message_queue(topic: str, group_name: str = "default_group") -> MessageQueue:
    """
    Factory function to get message queue instance based on QUEUE_TYPE setting.

    This is a convenience wrapper around MessageQueueFactory that automatically
    reads the QUEUE_TYPE from settings, maintaining backward compatibility with
    the original design where queue type was determined by configuration.

    Args:
        topic: Topic/stream name
        group_name: Consumer group name (default: "default_group")

    Returns:
        MessageQueue: Instance of the configured queue type

    Example:
        queue = get_message_queue("my-topic")
        await queue.initialize()
        await queue.produce({"event": "test"})
    """
    from src.core.config.settings import get_settings

    settings = get_settings()
    queue_type = getattr(settings, "QUEUE_TYPE", "redis").lower()

    factory = MessageQueueFactory()
    return factory.get(queue_type, topic, group_name)
