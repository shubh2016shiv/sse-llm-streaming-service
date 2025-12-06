import json
from datetime import datetime
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from src.config.settings import get_settings
from src.core.exceptions import QueueException
from src.core.interfaces import MessageQueue, QueueMessage
from src.core.logging import get_logger

logger = get_logger(__name__)

class KafkaQueue(MessageQueue):
    """
    Kafka-based message queue implementation.
    """

    def __init__(self, topic_name: str, group_id: str = "default_group"):
        self.settings = get_settings()
        self.topic = topic_name
        self.group_id = group_id
        self.bootstrap_servers = self.settings.KAFKA_BOOTSTRAP_SERVERS

        self.producer: AIOKafkaProducer | None = None
        self.consumer: AIOKafkaConsumer | None = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        try:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            await self.producer.start()

            # Consumer is initialized on demand or here?
            # Usually consumer is separate, but for this interface we might need it.
            # We'll initialize consumer lazily in consume() or separate start_consumer method.

            self._initialized = True
            logger.info("Kafka Queue initialized", stage="QUEUE.INIT", topic=self.topic)
        except Exception as e:
            logger.error("Failed to initialize Kafka", stage="QUEUE.ERR", error=str(e))
            raise QueueException(f"Failed to initialize Kafka: {e}")

    async def produce(self, payload: dict[str, Any]) -> str:
        if not self._initialized:
            await self.initialize()

        try:
            if "timestamp" not in payload:
                payload["timestamp"] = datetime.utcnow().isoformat() + 'Z'

            future = await self.producer.send(self.topic, payload)
            record_metadata = await future

            msg_id = f"{record_metadata.partition}-{record_metadata.offset}"
            logger.debug("Message produced to Kafka", stage="QUEUE.PROD", id=msg_id)
            return msg_id

        except Exception as e:
            logger.error("Failed to produce to Kafka", stage="QUEUE.ERR", error=str(e))
            raise QueueException(f"Failed to produce to Kafka: {e}")

    async def consume(
        self,
        consumer_name: str,
        batch_size: int = 10,
        block_ms: int = 2000
    ) -> list[QueueMessage]:
        if not self.consumer:
            self.consumer = AIOKafkaConsumer(
                self.topic,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                value_deserializer=lambda x: json.loads(x.decode('utf-8')),
                auto_offset_reset="earliest",
                enable_auto_commit=False  # We will commit manually
            )
            await self.consumer.start()

        try:
            # AIOKafka doesn't have a direct "fetch batch with timeout" exactly like Redis
            # But we can use getmany

            results = await self.consumer.getmany(
                timeout_ms=block_ms,
                max_records=batch_size
            )

            messages = []
            for tp, records in results.items():
                for record in records:
                    messages.append(QueueMessage(
                        id=f"{record.partition}-{record.offset}", # Not used for ack in Kafka same way
                        payload=record.value,
                        timestamp=record.value.get("timestamp", "")
                    ))

            return messages

        except Exception as e:
            logger.error("Failed to consume from Kafka", stage="QUEUE.ERR", error=str(e))
            raise QueueException(f"Failed to consume from Kafka: {e}")

    async def acknowledge(self, message_id: str) -> None:
        # In Kafka, we commit offsets.
        # This simple interface assumes individual ack, which is tricky in Kafka (usually cumulative).
        # For now, we will commit async.
        if self.consumer:
            await self.consumer.commit()

    async def close(self) -> None:
        if self.producer:
            await self.producer.stop()
        if self.consumer:
            await self.consumer.stop()
