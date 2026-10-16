import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_stdio_protocol_and_budget_rejection():
    async def check():
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "trialtrust.mcp_server"])
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert names == {"search_demo_terms", "check_demo_plan"}
                result = await client.call_tool("check_demo_plan", {"total_yuan": 320, "source_ids": ["price-v2", "cancel-v2"]})
                data = json.loads(result.content[0].text)
                assert not data["valid"]
                assert "submitted_total" in data["conflicting_constraints"]
                assert {"user_budget", "current_price_times_quantity_plus_fee"} & set(data["conflicting_constraints"])
    asyncio.run(check())
