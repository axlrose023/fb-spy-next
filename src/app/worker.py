import logging

from dishka.integrations.taskiq import setup_dishka
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from app.ioc import get_async_container
from app.observability import setup_logging
from app.settings import get_config

config = get_config()
setup_logging(config.env)
logging.getLogger("taskiq").setLevel(logging.INFO)
logging.getLogger("redis").setLevel(logging.WARNING)

_redis_connection_kwargs = {
    "socket_timeout": None,
    "socket_connect_timeout": 5,
    "health_check_interval": 30,
}

redis_async_result: RedisAsyncResultBackend = RedisAsyncResultBackend(
    redis_url=config.redis_url,
    keep_results=False,
    result_ex_time=3600,
    max_connection_pool_size=20,
    **_redis_connection_kwargs,
)

broker = RedisStreamBroker(
    url=config.redis_url,
    queue_name="taskiq:stream",
    consumer_group_name="fb-spy-taskiq",
    xread_block=5000,
    xread_count=1,
    idle_timeout=60000,
    unacknowledged_lock_timeout=10,
    maxlen=10000,
    max_connection_pool_size=20,
    **_redis_connection_kwargs,
)
broker.with_result_backend(redis_async_result)

scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker)],
)

container = get_async_container()
setup_dishka(container=container, broker=broker)
