import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with streamable_http_client("http://127.0.0.1:8765/mcp") as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "log_agent_action",
                {
                    "project": "smoke-test-agent",
                    "action": "manual_verification",
                    "model_used": "claude-sonnet-5",
                    "tokens_used": 42,
                },
            )
            print(result.content)


if __name__ == "__main__":
    asyncio.run(main())
