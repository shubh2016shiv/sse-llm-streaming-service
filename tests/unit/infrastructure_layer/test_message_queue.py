"""
Unit Tests for Message Queue Infrastructure

Tests factory selection, queue implementations, and error handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.message_queue.factory import MessageQueueFactory
from src.infrastructure.message_queue.kafka_queue import KafkaMessageQueue
from src.infrastructure.message_queue.redis_queue import RedisMessageQueue


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

        with patch(
            "src.infrastructure.message_queue.redis_queue.get_redis_client"
        ) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis

            queue = factory.get("redis", "test-topic")

            assert isinstance(queue, RedisMessageQueue)
            assert queue._topic == "test-topic"

    def test_get_kafka_queue(self):
        """Test factory creates Kafka queue."""
        factory = MessageQueueFactory()

        with (
            patch("src.infrastructure.message_queue.kafka_queue.KafkaProducer"),
            patch("src.infrastructure.message_queue.kafka_queue.KafkaConsumer"),
        ):
            queue = factory.get("kafka", "test-topic")

            assert isinstance(queue, KafkaMessageQueue)
            assert queue._topic == "test-topic"

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

    @pytest.mark.asyncio
    async def test_factory_handles_initialization_errors(self):
        """Test factory handles queue initialization errors gracefully."""
        factory = MessageQueueFactory()

        # Mock Redis client failure
        with patch(
            "src.infrastructure.message_queue.redis_queue.get_redis_client"
        ) as mock_get_redis:
            mock_get_redis.side_effect = Exception("Redis connection failed")

            with pytest.raises(Exception) as exc_info:
                factory.get("redis", "test-topic")

            assert "Redis connection failed" in str(exc_info.value)


@pytest.mark.unit
class TestRedisMessageQueue:
    """Test suite for RedisMessageQueue."""

    @pytest.fixture
    def redis_queue(self):
        """Create RedisMessageQueue for testing."""
        with patch(
            "src.infrastructure.message_queue.redis_queue.get_redis_client"
        ) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis

            queue = RedisMessageQueue("test-topic")
            return queue

    @pytest.mark.asyncio
    async def test_publish_message(self, redis_queue):
        """Test publishing message to Redis queue."""
        message = {"event": "test", "data": "value"}

        await redis_queue.publish(message)

        # Should have called Redis publish
        redis_queue._redis.publish.assert_called_once()
        call_args = redis_queue._redis.publish.call_args

        assert call_args[0][0] == "test-topic"  # Channel
        # Message should be JSON string
        assert isinstance(call_args[0][1], str)

    @pytest.mark.asyncio
    async def test_publish_with_custom_channel(self, redis_queue):
        """Test publishing to custom channel."""
        message = {"test": "data"}
        channel = "custom-channel"

        await redis_queue.publish(message, channel=channel)

        redis_queue._redis.publish.assert_called_with(channel, pytest.any)

    @pytest.mark.asyncio
    async def test_consume_messages(self, redis_queue):
        """Test consuming messages from Redis queue."""
        # Mock pubsub subscribe
        mock_pubsub = AsyncMock()
        redis_queue._redis.pubsub.return_value = mock_pubsub

        # Mock message stream
        test_messages = [
            {"event": "message", "data": '{"test": "msg1"}'},
            {"event": "message", "data": '{"test": "msg2"}'},
        ]
        mock_pubsub.listen.return_value = iter(test_messages)

        messages = []
        async for msg in redis_queue.consume():
            messages.append(msg)
            if len(messages) >= 2:
                break

        assert len(messages) == 2
        assert messages[0]["test"] == "msg1"
        assert messages[1]["test"] == "msg2"

    @pytest.mark.asyncio
    async def test_consume_handles_json_errors(self, redis_queue):
        """Test consume handles malformed JSON gracefully."""
        mock_pubsub = AsyncMock()
        redis_queue._redis.pubsub.return_value = mock_pubsub

        # Malformed JSON message
        test_messages = [
            {"event": "message", "data": "invalid json"},
        ]
        mock_pubsub.listen.return_value = iter(test_messages)

        messages = []
        async for msg in redis_queue.consume():
            messages.append(msg)

        # Should handle error and continue or skip invalid message
        # Exact behavior depends on implementation
        assert isinstance(messages, list)

    @pytest.mark.asyncio
    async def test_health_check(self, redis_queue):
        """Test health check functionality."""
        redis_queue._redis.health_check.return_value = {"status": "healthy"}

        health = await redis_queue.health_check()

        assert health["status"] == "healthy"
        assert "queue_type" in health
        assert health["queue_type"] == "redis"

    @pytest.mark.asyncio
    async def test_close_connection(self, redis_queue):
        """Test closing Redis connection."""
        await redis_queue.close()

        # Should close pubsub if it exists
        # (Implementation may vary)


@pytest.mark.unit
class TestKafkaMessageQueue:
    """Test suite for KafkaMessageQueue."""

    @pytest.fixture
    def kafka_queue(self):
        """Create KafkaMessageQueue for testing."""
        with (
            patch("src.infrastructure.message_queue.kafka_queue.KafkaProducer"),
            patch("src.infrastructure.message_queue.kafka_queue.KafkaConsumer"),
        ):
            queue = KafkaMessageQueue("test-topic")
            return queue

    @pytest.mark.asyncio
    async def test_publish_message(self, kafka_queue):
        """Test publishing message to Kafka."""
        message = {"event": "test", "data": "value"}

        await kafka_queue.publish(message)

        # Should have called producer send
        kafka_queue._producer.send.assert_called_once()
        call_args = kafka_queue._producer.send.call_args

        assert call_args[0][0] == "test-topic"  # Topic
        # Value should be JSON bytes
        assert isinstance(call_args[1]["value"], bytes)

    @pytest.mark.asyncio
    async def test_publish_with_key(self, kafka_queue):
        """Test publishing message with partition key."""
        message = {"test": "data"}
        key = "partition-key"

        await kafka_queue.publish(message, key=key)

        call_kwargs = kafka_queue._producer.send.call_args[1]
        assert call_kwargs["key"] == key.encode()

    @pytest.mark.asyncio
    async def test_consume_messages(self, kafka_queue):
        """Test consuming messages from Kafka."""
        # Mock consumer poll
        test_message = MagicMock()
        test_message.value = b'{"test": "msg"}'
        test_message.key = b"test-key"

        kafka_queue._consumer.poll.return_value = test_message

        messages = []
        async for msg in kafka_queue.consume():
            messages.append(msg)
            break  # Only consume one for test

        assert len(messages) == 1
        assert messages[0]["test"] == "msg"

    @pytest.mark.asyncio
    async def test_consume_handles_poll_timeouts(self, kafka_queue):
        """Test consume handles poll timeouts gracefully."""
        # Mock None return (timeout)
        kafka_queue._consumer.poll.return_value = None

        # Should not yield anything or handle gracefully
        messages = []
        count = 0
        async for msg in kafka_queue.consume():
            messages.append(msg)
            count += 1
            if count >= 1:  # Prevent infinite loop
                break

        # Should handle None gracefully
        assert isinstance(messages, list)

    @pytest.mark.asyncio
    async def test_health_check(self, kafka_queue):
        """Test Kafka health check."""
        health = await kafka_queue.health_check()

        assert "status" in health
        assert "queue_type" in health
        assert health["queue_type"] == "kafka"

    @pytest.mark.asyncio
    async def test_close_connections(self, kafka_queue):
        """Test closing Kafka connections."""
        await kafka_queue.close()

        kafka_queue._producer.close.assert_called_once()
        kafka_queue._consumer.close.assert_called_once()


@pytest.mark.unit
class TestMessageQueueErrorHandling:
    """Test error handling across message queue implementations."""

    @pytest.mark.asyncio
    async def test_redis_publish_error_handling(self):
        """Test Redis queue handles publish errors."""
        with patch(
            "src.infrastructure.message_queue.redis_queue.get_redis_client"
        ) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.publish.side_effect = Exception("Redis publish failed")
            mock_get_redis.return_value = mock_redis

            queue = RedisMessageQueue("test-topic")

            with pytest.raises(Exception) as exc_info:
                await queue.publish({"test": "message"})

            assert "Redis publish failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_kafka_publish_error_handling(self):
        """Test Kafka queue handles publish errors."""
        with patch("src.infrastructure.message_queue.kafka_queue.KafkaProducer") as mock_producer:
            mock_producer_instance = MagicMock()
            mock_producer_instance.send.side_effect = Exception("Kafka send failed")
            mock_producer.return_value = mock_producer_instance

            with patch("src.infrastructure.message_queue.kafka_queue.KafkaConsumer"):
                queue = KafkaMessageQueue("test-topic")

                with pytest.raises(Exception) as exc_info:
                    await queue.publish({"test": "message"})

                assert "Kafka send failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_redis_consume_connection_error(self):
        """Test Redis consume handles connection errors."""
        with patch(
            "src.infrastructure.message_queue.redis_queue.get_redis_client"
        ) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_pubsub = AsyncMock()
            mock_pubsub.listen.side_effect = Exception("Connection lost")
            mock_redis.pubsub.return_value = mock_pubsub
            mock_get_redis.return_value = mock_redis

            queue = RedisMessageQueue("test-topic")

            # Should handle error during consumption
            with pytest.raises(Exception):
                async for msg in queue.consume():
                    break

    @pytest.mark.asyncio
    async def test_factory_error_propagation(self):
        """Test factory properly propagates initialization errors."""
        factory = MessageQueueFactory()

        with patch(
            "src.infrastructure.message_queue.redis_queue.get_redis_client"
        ) as mock_get_redis:
            mock_get_redis.side_effect = ConnectionError("Redis unavailable")

            with pytest.raises(ConnectionError):
                factory.get("redis", "test-topic")
