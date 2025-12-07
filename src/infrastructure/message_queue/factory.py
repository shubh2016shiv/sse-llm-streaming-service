from src.core.config.settings import get_settings
from src.core.interfaces import MessageQueue
from src.infrastructure.message_queue.kafka_queue import KafkaQueue
from src.infrastructure.message_queue.redis_queue import RedisQueue


def get_message_queue(queue_name: str, group_name: str = "default_group") -> MessageQueue:
    """
    Factory to get the configured message queue implementation.

    Args:
        queue_name: Name of the queue/topic.
        group_name: Consumer group name.

    Returns:
        MessageQueue: Configured queue instance.
    """
    settings = get_settings()
    queue_type = getattr(settings, "QUEUE_TYPE", "redis").lower()

    if queue_type == "kafka":
        return KafkaQueue(topic_name=queue_name, group_id=group_name)
    else:
        return RedisQueue(stream_name=queue_name, group_name=group_name)
