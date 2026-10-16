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
                evidence = await client.call_tool('search_demo_terms', {'query':'现行价格退改规则', 'domain':'museum'})
                assert json.loads(evidence.content[0].text)['hits']
                museum = await client.call_tool('check_demo_plan', {
                    'domain':'museum','quantity':2,'fulfillment':'entry','budget_yuan':100,
                    'total_yuan':80,'source_ids':['museum-price-v1','museum-cancel-v1']})
                assert json.loads(museum.content[0].text)['valid'] is True
    asyncio.run(check())
