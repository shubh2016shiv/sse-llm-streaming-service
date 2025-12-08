from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class QueueMessage:
    """
    Represents a message in the queue.
    """
    id: str
    payload: dict[str, Any]
    timestamp: str

class MessageQueue(ABC):
    """
    Abstract base class for message queue implementations.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize connection to the queue."""
        pass

    @abstractmethod
    async def produce(self, payload: dict[str, Any]) -> str:
        """
        Produce a message to the queue.

        Args:
            payload: Data to send.

        Returns:
            str: Message ID.
        """
        pass

    @abstractmethod
    async def consume(
        self,
        consumer_name: str,
        batch_size: int = 10,
        block_ms: int = 2000
    ) -> list[QueueMessage]:
        """
        Consume messages from the queue.

        Args:
            consumer_name: Unique consumer name.
            batch_size: Number of messages to fetch.
            block_ms: Time to block waiting for messages.

        Returns:
            List[QueueMessage]: List of messages.
        """
        pass

    @abstractmethod
    async def acknowledge(self, message_id: str) -> None:
        """
        Acknowledge a processed message.

        Args:
            message_id: ID of the message to acknowledge.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the connection."""
        pass
