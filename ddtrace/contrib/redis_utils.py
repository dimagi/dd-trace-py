from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from ddtrace.ext import net
from ddtrace.ext import redis as redisx
from ddtrace.internal import core
from ddtrace.internal.utils.formats import stringify_cache_args


SINGLE_KEY_COMMANDS = [
    "GET",
    "GETDEL",
    "GETEX",
    "GETRANGE",
    "GETSET",
    "LINDEX",
    "LRANGE",
    "RPOP",
    "LPOP",
    "HGET",
    "HGETALL",
    "HKEYS",
    "HMGET",
    "HRANDFIELD",
    "HVALS",
]
MULTI_KEY_COMMANDS = ["MGET"]
ROW_RETURNING_COMMANDS = SINGLE_KEY_COMMANDS + MULTI_KEY_COMMANDS


def _extract_conn_tags(conn_kwargs):
    """Transform redis conn info into dogtrace metas"""
    try:
        conn_tags = {
            net.TARGET_HOST: conn_kwargs["host"],
            net.TARGET_PORT: conn_kwargs["port"],
            redisx.DB: conn_kwargs.get("db") or 0,
        }
        client_name = conn_kwargs.get("client_name")
        if client_name:
            conn_tags[redisx.CLIENT_NAME] = client_name
        return conn_tags
    except Exception:
        return {}


def determine_row_count(redis_command: str, result: Optional[Union[List, Dict, str]]) -> int:
    empty_results = [b"", [], {}, None]
    # result can be an empty list / dict / string
    if result not in empty_results:
        if redis_command == "MGET":
            # only include valid key results within count
            result = [x for x in result if x not in empty_results]
            return len(result)
        elif redis_command == "HMGET":
            # only include valid key results within count
            result = [x for x in result if x not in empty_results]
            return 1 if len(result) > 0 else 0
        else:
            return 1
    else:
        return 0


async def _run_redis_command_async(span, func, args, kwargs):
    parsed_command = stringify_cache_args(args)
    redis_command = parsed_command.split(" ")[0]
    rowcount = None
    try:
        result = await func(*args, **kwargs)
        return result
    except Exception:
        rowcount = 0
        raise
    finally:
        if rowcount is None:
            rowcount = determine_row_count(redis_command=redis_command, result=result)
        if redis_command not in ROW_RETURNING_COMMANDS:
            rowcount = None
        core.dispatch("redis.async_command.post", [span, rowcount])
