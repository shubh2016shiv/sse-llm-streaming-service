import json
from datetime import datetime
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, KafkaError
from aioresilience import BasicLoadShedder

from src.core.config.settings import get_settings
from src.core.exceptions.base import QueueError, QueueFullError
from src.core.interfaces import MessageQueue, QueueMessage
from src.core.logging.logger import get_logger
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

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
        self._metrics = get_metrics_collector()

        # Backpressure configuration from settings
        self.buffer_memory = self.settings.queue.KAFKA_BUFFER_MEMORY
        self.max_in_flight_requests = self.settings.queue.KAFKA_MAX_IN_FLIGHT_REQUESTS

        # Load shedding (if enabled)
        self.load_shedder = None
        if self.settings.queue.QUEUE_LOAD_SHEDDING_ENABLED:
            self.load_shedder = BasicLoadShedder(
                max_requests=self.settings.queue.QUEUE_LOAD_SHEDDING_MAX_REQUESTS
            )

        self.producer: AIOKafkaProducer | None = None
        self.consumer: AIOKafkaConsumer | None = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        try:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                buffer_memory=self.buffer_memory,
                max_in_flight_requests_per_connection=self.max_in_flight_requests,
            )
            await self.producer.start()

            # Consumer is initialized on demand or here?
            # Usually consumer is separate, but for this interface we might need it.
            # We'll initialize consumer lazily in consume() or separate start_consumer method.

            self._initialized = True
            logger.info(
                "Kafka Queue initialized",
                stage="QUEUE.INIT",
                topic=self.topic,
                buffer_memory=self.buffer_memory,
                max_in_flight_requests=self.max_in_flight_requests,
            )
        except Exception as e:
            logger.error("Failed to initialize Kafka", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to initialize Kafka: {e}")

    async def produce(self, payload: dict[str, Any]) -> str:
        if not self._initialized:
            await self.initialize()

        # Check load shedding first (if enabled)
        if self.load_shedder is not None:
            if not await self.load_shedder.accept():
                self._metrics.record_queue_produce_failure("kafka", "load_shedding")
                logger.warning(
                    "Load shedding active - rejecting request",
                    stage="QUEUE.LOAD_SHEDDING",
                    topic=self.topic,
                )
                raise QueueFullError(f"Load shedding active for topic {self.topic}")

        # Record produce attempt
        self._metrics.record_queue_produce_attempt("kafka")

        try:
            if "timestamp" not in payload:
                payload["timestamp"] = datetime.utcnow().isoformat() + "Z"

            future = await self.producer.send(self.topic, payload)
            record_metadata = await future

            msg_id = f"{record_metadata.partition}-{record_metadata.offset}"
            logger.debug("Message produced to Kafka", stage="QUEUE.PROD", id=msg_id)

            self._metrics.record_queue_produce_success("kafka")
            return msg_id

        except KafkaError as e:
            # Check if this is a buffer-related error (backpressure)
            error_str = str(e).lower()
            if "buffer" in error_str or "full" in error_str or "memory" in error_str:
                self._metrics.record_queue_produce_failure("kafka", "buffer_full")
                logger.warning(
                    "Kafka producer buffer full - backpressure applied",
                    stage="QUEUE.BACKPRESSURE",
                    topic=self.topic,
                    buffer_memory=self.buffer_memory,
                    error=str(e),
                )
                raise QueueFullError(f"Kafka producer buffer full for topic {self.topic}: {e}")
            else:
                self._metrics.record_queue_produce_failure("kafka", "kafka_error")
                logger.error("Failed to produce to Kafka", stage="QUEUE.ERR", error=str(e))
                raise QueueError(f"Failed to produce to Kafka: {e}")
        except Exception as e:
            self._metrics.record_queue_produce_failure("kafka", "unknown_error")
            logger.error("Failed to produce to Kafka", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to produce to Kafka: {e}")

    async def consume(
        self, consumer_name: str, batch_size: int = 10, block_ms: int = 2000
    ) -> list[QueueMessage]:
        if not self.consumer:
            self.consumer = AIOKafkaConsumer(
                self.topic,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                value_deserializer=lambda x: json.loads(x.decode("utf-8")),
                auto_offset_reset="earliest",
                enable_auto_commit=False,  # We will commit manually
            )
            await self.consumer.start()

        try:
            # AIOKafka doesn't have a direct "fetch batch with timeout" exactly like Redis
            # But we can use getmany

            results = await self.consumer.getmany(timeout_ms=block_ms, max_records=batch_size)

            messages = []
            for tp, records in results.items():
                for record in records:
                    messages.append(
                        QueueMessage(
                            # Not used for ack in Kafka same way
                            id=f"{record.partition}-{record.offset}",
                            payload=record.value,
                            timestamp=record.value.get("timestamp", ""),
                        )
                    )

            return messages

        except Exception as e:
            logger.error("Failed to consume from Kafka", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to consume from Kafka: {e}")

    async def acknowledge(self, message_id: str) -> None:
        # In Kafka, we commit offsets.
        # This simple interface assumes individual ack, which is tricky in Kafka
        # (usually cumulative). For now, we will commit async.
        if self.consumer:
            await self.consumer.commit()

    async def close(self) -> None:
        if self.producer:
            await self.producer.stop()
        if self.consumer:
            await self.consumer.stop()
