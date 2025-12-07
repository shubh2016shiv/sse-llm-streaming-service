"""
Unit Tests for Message Queue Infrastructure

Tests factory selection, queue implementations, and error handling.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.message_queue.factory import MessageQueueFactory
from src.infrastructure.message_queue.kafka_queue import KafkaQueue
from src.infrastructure.message_queue.redis_queue import RedisQueue


@pytest.mark.unit
class TestMessageQueueFactory:
    """Test suite for MessageQueueFactory."""

    def test_factory_creation(self):
        """Test factory can be created."""
        factory = MessageQueueFactory()
        assert factory is not None

    def test_get_redis_queue(self):
        """Test factory creates Redis queue."""
        factory = MessageQueueFactory()

        # Patch get_redis_client at the source used by RedisQueue?
        # Assuming factory just instantiates, it doesn't call initialize(),
        # so no side effects usually.
        # But RedisQueue __init__ accesses Settings.
        # If Settings isn't patched, it tries to load real settings.
        # But we fixed Settings access, so it should work if env is valid or defaults work.
        # We'll just run it.
        queue = factory.get("redis", "test-topic")

        assert isinstance(queue, RedisQueue)
        assert queue.stream_name == "queue:test-topic"

    def test_get_kafka_queue(self):
        """Test factory creates Kafka queue."""
        factory = MessageQueueFactory()

        # KafkaQueue __init__ uses Settings.
        queue = factory.get("kafka", "test-topic")

        assert isinstance(queue, KafkaQueue)
        assert queue.topic == "test-topic"

    def test_get_unknown_queue_type_raises_error(self):
        """Test factory raises error for unknown queue types."""
        factory = MessageQueueFactory()

        with pytest.raises(ValueError) as exc_info:
            factory.get("unknown", "test-topic")

        assert "unknown" in str(exc_info.value).lower()

    def test_get_available_queues(self):
        """Test factory returns list of available queue types."""
        factory = MessageQueueFactory()

        available = factory.get_available()

        assert isinstance(available, list)
        assert "redis" in available
        assert "kafka" in available


@pytest.mark.unit
class TestRedisQueue:
    """Test suite for RedisQueue."""

    @pytest.fixture
    def mock_redis_client_obj(self):
        """Create a mock Redis client object."""
        mock = AsyncMock()
        mock.connect = AsyncMock()
        mock.client.xadd = AsyncMock(return_value="1-0")
        mock.client.xreadgroup = AsyncMock()
        mock.client.xlen = AsyncMock(return_value=0)
        mock.client.xack = AsyncMock()
        mock.client.xgroup_create = AsyncMock()
        return mock

    @pytest.fixture
    def redis_queue(self, mock_redis_client_obj):
        """Create RedisQueue for testing with patched dependencies."""
        # Using patch as context manager with yield
        with patch(
            "src.infrastructure.message_queue.redis_queue.get_redis_client"
        ) as mock_get_redis:
            mock_get_redis.return_value = mock_redis_client_obj

            with patch("src.infrastructure.message_queue.redis_queue.get_metrics_collector"):
                queue = RedisQueue("test-topic")
                yield queue

    @pytest.mark.asyncio
    async def test_produce_message(self, redis_queue, mock_redis_client_obj):
        """Test producing message to Redis queue."""
        message = {"event": "test", "data": "value"}

        await redis_queue.produce(message)

        # Verify connect called
        mock_redis_client_obj.connect.assert_called_once()

        # Verify xadd called
        mock_redis_client_obj.client.xadd.assert_called_once()
        call_args = mock_redis_client_obj.client.xadd.call_args
        assert call_args[0][0] == "queue:test-topic"

    @pytest.mark.asyncio
    async def test_consume_messages(self, redis_queue, mock_redis_client_obj):
        """Test consuming messages from Redis queue."""
        # Setup mock data for xreadgroup
        mock_data = [
            [
                b"queue:test-topic",
                [
                    ("1-0", {"test": "msg1"}),
                    ("2-0", {"test": "msg2"}),
                ]
            ]
        ]
        mock_redis_client_obj.client.xreadgroup.return_value = mock_data

        # Call consume
        messages = await redis_queue.consume("test-consumer")

        assert len(messages) == 2
        assert messages[0].payload["test"] == "msg1"
        assert messages[1].payload["test"] == "msg2"


@pytest.mark.unit
class TestKafkaQueue:
    """Test suite for KafkaQueue."""

    @pytest.fixture
    def kafka_queue(self):
        """Create KafkaQueue for testing."""
        with (
            patch("src.infrastructure.message_queue.kafka_queue.AIOKafkaProducer"),
            patch("src.infrastructure.message_queue.kafka_queue.AIOKafkaConsumer"),
            patch("src.infrastructure.message_queue.kafka_queue.get_metrics_collector")
        ):
            queue = KafkaQueue("test-topic")
            # We need to set mocks on the instance because logic uses them.
            # But the logic initializes them in initialize().
            # Or we can patch the class so usage in logic gets the mock.
            yield queue

    @pytest.mark.asyncio
    async def test_produce_message(self, kafka_queue):
        """Test producing message to Kafka."""
        message = {"event": "test", "data": "value"}

        # We need to grab the mocked producer returned by AIOKafkaProducer() constructor
        from src.infrastructure.message_queue.kafka_queue import AIOKafkaProducer

        # Configure the mock returned by the constructor
        mock_producer_instance = AIOKafkaProducer.return_value
        mock_producer_instance.start = AsyncMock()
        mock_producer_instance.send = AsyncMock()
        mock_producer_instance.stop = AsyncMock()

        # Configure send to return a Future-like object (awaitable)
        mock_metadata = MagicMock()
        mock_metadata.partition = 0
        mock_metadata.offset = 1

        loop = asyncio.get_running_loop()
        mock_future = loop.create_future()
        mock_future.set_result(mock_metadata)

        mock_producer_instance.send.return_value = mock_future

        await kafka_queue.produce(message)

        mock_producer_instance.start.assert_called_once()
        mock_producer_instance.send.assert_called_once()
        call_args = mock_producer_instance.send.call_args
        assert call_args[0][0] == "test-topic"

    @pytest.mark.asyncio
    async def test_consume_messages(self, kafka_queue):
        """Test consuming messages from Kafka."""
        from src.infrastructure.message_queue.kafka_queue import AIOKafkaConsumer

        mock_consumer_instance = AIOKafkaConsumer.return_value
        mock_consumer_instance.start = AsyncMock()
        mock_consumer_instance.stop = AsyncMock()

        mock_record = MagicMock()
        mock_record.value = {"test": "msg"}
        mock_record.partition = 0
        mock_record.offset = 1

        mock_consumer_instance.getmany = AsyncMock(return_value={
            "tp": [mock_record]
        })

        messages = await kafka_queue.consume("test-consumer")

        assert len(messages) == 1
        assert messages[0].payload["test"] == "msg"

    @pytest.mark.asyncio
    async def test_close_connections(self, kafka_queue):
        """Test closing Kafka connections."""
        # Initialize first (to create producer/consumer)
        from src.infrastructure.message_queue.kafka_queue import AIOKafkaConsumer, AIOKafkaProducer

        mock_producer = AIOKafkaProducer.return_value
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()

        mock_consumer = AIOKafkaConsumer.return_value # Consume creates it lazily?
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()

        # Trigger initialization of producer
        try:
             await kafka_queue.produce({})
        except Exception:
             pass

        # Trigger initialization of consumer
        try:
            await kafka_queue.consume("consumer")
        except Exception:
            pass

        await kafka_queue.close()

        mock_producer.stop.assert_called()
        mock_consumer.stop.assert_called()
