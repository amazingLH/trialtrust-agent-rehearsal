"""Read-only local MCP facade. No external URLs, credentials or live actions."""
from typing import Literal
from mcp.server.fastmcp import FastMCP

from .retrieval import EvidenceIndex
from .scenarios import RunSpec, make_world

mcp = FastMCP("试托合成场景工具")


@mcp.tool()
def search_demo_terms(query: str, domain: Literal["pottery", "cleaning"] = "pottery") -> dict:
    """检索自有合成活动的现行条款；不是任何真实商家服务。"""
    if not 1 <= len(query) <= 300:
        return {"error": "query_length_out_of_bounds"}
    sources, _, _ = make_world(RunSpec(domain=domain, fulfillment="onsite" if domain == "cleaning" else "pickup"))
    return EvidenceIndex(sources).search(query, domain)


@mcp.tool()
def check_demo_plan(total_yuan: float, source_ids: list[str],
                    domain: Literal["pottery", "cleaning"] = "pottery", quantity: int = 4,
                    fulfillment: Literal["pickup", "shipping", "onsite"] = "pickup", budget_yuan: int = 300) -> dict:
    """核验自有合成条款、数量、附加费及预算。只核验，不产生草稿或真实操作。"""
    spec = RunSpec(domain=domain, quantity=quantity, fulfillment=fulfillment, budget_yuan=budget_yuan)
    _, world, _ = make_world(spec)
    return world.check_plan(total_yuan, source_ids, quantity, fulfillment)


if __name__ == "__main__":
    mcp.run(transport="stdio")
