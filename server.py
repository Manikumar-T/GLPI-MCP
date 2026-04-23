"""GLPI MCP Server — SSE transport."""

import json
import os
from typing import Any, Optional

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route
import uvicorn

from glpi_client import GlpiClient, client_from_env

# ── Status / label maps ──────────────────────────────────────────────────────

TICKET_STATUS = {1: "New", 2: "Processing (assigned)", 3: "Processing (planned)", 4: "Pending", 5: "Solved", 6: "Closed"}
TICKET_URGENCY = {1: "Very low", 2: "Low", 3: "Medium", 4: "High", 5: "Very high"}
PROBLEM_STATUS = {1: "New", 2: "Accepted", 3: "Planned", 4: "Pending", 5: "Solved", 6: "Closed"}
CHANGE_STATUS = {
    1: "New", 2: "Evaluation", 3: "Approval", 4: "Accepted", 5: "Pending",
    6: "Test", 7: "Qualification", 8: "Applied", 9: "Review",
    10: "Closed", 11: "Refused", 12: "Canceled",
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _ok(data: Any) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, indent=2, default=str))])


def _req(args: dict, *keys: str) -> None:
    for k in keys:
        if not args.get(k):
            raise ValueError(f"'{k}' is required")


def _range(limit: int) -> str:
    return f"0-{limit - 1}"


# ── MCP server setup ─────────────────────────────────────────────────────────

app_server = Server("glpi-mcp")
_glpi: Optional[GlpiClient] = None


def glpi() -> GlpiClient:
    global _glpi
    if _glpi is None:
        _glpi = client_from_env()
    return _glpi


# ── Tool definitions ─────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    # ── Tickets ──
    Tool(name="glpi_list_tickets", description="List tickets from GLPI with optional filters",
         inputSchema={"type": "object", "properties": {
             "limit": {"type": "number", "description": "Max tickets to return (default 50)"},
             "status": {"type": "number", "description": "Filter by status (1=New … 6=Closed)"},
             "order": {"type": "string", "enum": ["ASC", "DESC"]},
         }}),
    Tool(name="glpi_get_ticket", description="Get a ticket with its followups and tasks",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_create_ticket", description="Create a new ticket",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "content": {"type": "string"},
             "urgency": {"type": "number"}, "category_id": {"type": "number"},
             "user_id_assign": {"type": "number"}, "group_id_assign": {"type": "number"},
             "type": {"type": "number", "description": "1=Incident, 2=Request"},
         }, "required": ["name", "content"]}),
    Tool(name="glpi_update_ticket", description="Update an existing ticket",
         inputSchema={"type": "object", "properties": {
             "id": {"type": "number"}, "name": {"type": "string"},
             "content": {"type": "string"}, "status": {"type": "number"}, "urgency": {"type": "number"},
         }, "required": ["id"]}),
    Tool(name="glpi_delete_ticket", description="Delete a ticket (trash or permanent)",
         inputSchema={"type": "object", "properties": {
             "id": {"type": "number"}, "force": {"type": "boolean"},
         }, "required": ["id"]}),
    Tool(name="glpi_add_followup", description="Add a followup/comment to a ticket",
         inputSchema={"type": "object", "properties": {
             "ticket_id": {"type": "number"}, "content": {"type": "string"}, "is_private": {"type": "boolean"},
         }, "required": ["ticket_id", "content"]}),
    Tool(name="glpi_add_task", description="Add a task to a ticket",
         inputSchema={"type": "object", "properties": {
             "ticket_id": {"type": "number"}, "content": {"type": "string"},
             "actiontime": {"type": "number"}, "is_private": {"type": "boolean"},
             "state": {"type": "number", "description": "0=Information, 1=To do, 2=Done"},
             "users_id_tech": {"type": "number"},
         }, "required": ["ticket_id", "content"]}),
    Tool(name="glpi_add_solution", description="Add a solution to close a ticket",
         inputSchema={"type": "object", "properties": {
             "ticket_id": {"type": "number"}, "content": {"type": "string"},
             "solutiontypes_id": {"type": "number"},
         }, "required": ["ticket_id", "content"]}),
    Tool(name="glpi_assign_ticket", description="Assign a ticket to a user",
         inputSchema={"type": "object", "properties": {
             "ticket_id": {"type": "number"}, "user_id": {"type": "number"},
             "type": {"type": "number", "description": "1=Requester, 2=Assigned, 3=Observer"},
         }, "required": ["ticket_id", "user_id"]}),
    Tool(name="glpi_get_ticket_tasks", description="Get all tasks for a ticket",
         inputSchema={"type": "object", "properties": {"ticket_id": {"type": "number"}}, "required": ["ticket_id"]}),
    Tool(name="glpi_get_ticket_followups", description="Get all followups for a ticket",
         inputSchema={"type": "object", "properties": {"ticket_id": {"type": "number"}}, "required": ["ticket_id"]}),

    # ── Problems ──
    Tool(name="glpi_list_problems", description="List ITIL problems",
         inputSchema={"type": "object", "properties": {
             "limit": {"type": "number"}, "order": {"type": "string", "enum": ["ASC", "DESC"]},
         }}),
    Tool(name="glpi_get_problem", description="Get a specific problem",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_create_problem", description="Create a new problem",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "content": {"type": "string"},
             "urgency": {"type": "number"}, "impact": {"type": "number"},
             "priority": {"type": "number"}, "category_id": {"type": "number"},
         }, "required": ["name", "content"]}),
    Tool(name="glpi_update_problem", description="Update a problem",
         inputSchema={"type": "object", "properties": {
             "id": {"type": "number"}, "name": {"type": "string"},
             "content": {"type": "string"}, "status": {"type": "number"}, "urgency": {"type": "number"},
         }, "required": ["id"]}),

    # ── Changes ──
    Tool(name="glpi_list_changes", description="List ITIL changes",
         inputSchema={"type": "object", "properties": {
             "limit": {"type": "number"}, "order": {"type": "string", "enum": ["ASC", "DESC"]},
         }}),
    Tool(name="glpi_get_change", description="Get a specific change",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_create_change", description="Create a new change request",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "content": {"type": "string"},
             "urgency": {"type": "number"}, "impact": {"type": "number"},
             "priority": {"type": "number"}, "category_id": {"type": "number"},
         }, "required": ["name", "content"]}),
    Tool(name="glpi_update_change", description="Update a change",
         inputSchema={"type": "object", "properties": {
             "id": {"type": "number"}, "name": {"type": "string"},
             "content": {"type": "string"}, "status": {"type": "number"},
         }, "required": ["id"]}),

    # ── Computers ──
    Tool(name="glpi_list_computers", description="List computers from inventory",
         inputSchema={"type": "object", "properties": {
             "limit": {"type": "number"}, "include_deleted": {"type": "boolean"},
         }}),
    Tool(name="glpi_get_computer", description="Get a computer with optional software/network details",
         inputSchema={"type": "object", "properties": {
             "id": {"type": "number"},
             "with_softwares": {"type": "boolean"}, "with_connections": {"type": "boolean"},
             "with_networkports": {"type": "boolean"},
         }, "required": ["id"]}),
    Tool(name="glpi_create_computer", description="Create a new computer in inventory",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "serial": {"type": "string"},
             "otherserial": {"type": "string"}, "contact": {"type": "string"},
             "comment": {"type": "string"}, "locations_id": {"type": "number"},
             "states_id": {"type": "number"}, "computertypes_id": {"type": "number"},
             "manufacturers_id": {"type": "number"},
         }, "required": ["name"]}),
    Tool(name="glpi_update_computer", description="Update a computer",
         inputSchema={"type": "object", "properties": {
             "id": {"type": "number"}, "name": {"type": "string"},
             "serial": {"type": "string"}, "comment": {"type": "string"},
             "locations_id": {"type": "number"}, "states_id": {"type": "number"},
         }, "required": ["id"]}),
    Tool(name="glpi_delete_computer", description="Delete a computer from inventory",
         inputSchema={"type": "object", "properties": {
             "id": {"type": "number"}, "force": {"type": "boolean"},
         }, "required": ["id"]}),

    # ── Software ──
    Tool(name="glpi_list_softwares", description="List software from inventory",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_software", description="Get a specific software",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_create_software", description="Create a software entry",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "comment": {"type": "string"},
             "manufacturers_id": {"type": "number"}, "softwarecategories_id": {"type": "number"},
         }, "required": ["name"]}),

    # ── Network equipment ──
    Tool(name="glpi_list_network_equipments", description="List network equipment",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_network_equipment", description="Get a network equipment",
         inputSchema={"type": "object", "properties": {
             "id": {"type": "number"}, "with_networkports": {"type": "boolean"},
         }, "required": ["id"]}),

    # ── Printers ──
    Tool(name="glpi_list_printers", description="List printers",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_printer", description="Get a printer",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),

    # ── Monitors ──
    Tool(name="glpi_list_monitors", description="List monitors",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_monitor", description="Get a monitor",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),

    # ── Phones ──
    Tool(name="glpi_list_phones", description="List phones",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_phone", description="Get a phone",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),

    # ── Knowledge base ──
    Tool(name="glpi_list_knowbase", description="List knowledge base articles",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_knowbase_item", description="Get a knowledge base article",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_search_knowbase", description="Search knowledge base articles",
         inputSchema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
    Tool(name="glpi_create_knowbase_item", description="Create a knowledge base article",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "answer": {"type": "string"},
             "is_faq": {"type": "boolean"}, "knowbaseitemcategories_id": {"type": "number"},
         }, "required": ["name", "answer"]}),

    # ── Contracts ──
    Tool(name="glpi_list_contracts", description="List contracts",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_contract", description="Get a contract",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_create_contract", description="Create a contract",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "num": {"type": "string"},
             "begin_date": {"type": "string"}, "duration": {"type": "number"},
             "notice": {"type": "number"}, "comment": {"type": "string"},
         }, "required": ["name"]}),

    # ── Suppliers ──
    Tool(name="glpi_list_suppliers", description="List suppliers",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_supplier", description="Get a supplier",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_create_supplier", description="Create a supplier",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "address": {"type": "string"},
             "postcode": {"type": "string"}, "town": {"type": "string"},
             "country": {"type": "string"}, "website": {"type": "string"},
             "phonenumber": {"type": "string"}, "email": {"type": "string"},
         }, "required": ["name"]}),

    # ── Locations ──
    Tool(name="glpi_list_locations", description="List locations",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_location", description="Get a location",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_create_location", description="Create a location",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "address": {"type": "string"},
             "postcode": {"type": "string"}, "town": {"type": "string"},
             "building": {"type": "string"}, "room": {"type": "string"},
             "locations_id": {"type": "number"},
         }, "required": ["name"]}),

    # ── Projects ──
    Tool(name="glpi_list_projects", description="List projects",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_project", description="Get a project",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_create_project", description="Create a project",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "code": {"type": "string"},
             "content": {"type": "string"}, "priority": {"type": "number"},
             "plan_start_date": {"type": "string"}, "plan_end_date": {"type": "string"},
             "users_id": {"type": "number"}, "groups_id": {"type": "number"},
         }, "required": ["name"]}),
    Tool(name="glpi_update_project", description="Update a project",
         inputSchema={"type": "object", "properties": {
             "id": {"type": "number"}, "name": {"type": "string"},
             "content": {"type": "string"}, "percent_done": {"type": "number"},
             "real_start_date": {"type": "string"}, "real_end_date": {"type": "string"},
         }, "required": ["id"]}),

    # ── Users ──
    Tool(name="glpi_list_users", description="List users",
         inputSchema={"type": "object", "properties": {
             "limit": {"type": "number"}, "active_only": {"type": "boolean"},
         }}),
    Tool(name="glpi_get_user", description="Get a user",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_search_user", description="Search users by name",
         inputSchema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}),
    Tool(name="glpi_create_user", description="Create a user",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "password": {"type": "string"},
             "realname": {"type": "string"}, "firstname": {"type": "string"},
             "email": {"type": "string"}, "phone": {"type": "string"},
             "profiles_id": {"type": "number"},
         }, "required": ["name"]}),

    # ── Groups ──
    Tool(name="glpi_list_groups", description="List groups",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_group", description="Get a group",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_create_group", description="Create a group",
         inputSchema={"type": "object", "properties": {
             "name": {"type": "string"}, "comment": {"type": "string"},
             "is_requester": {"type": "boolean"}, "is_assign": {"type": "boolean"},
         }, "required": ["name"]}),
    Tool(name="glpi_add_user_to_group", description="Add a user to a group",
         inputSchema={"type": "object", "properties": {
             "user_id": {"type": "number"}, "group_id": {"type": "number"},
             "is_manager": {"type": "boolean"},
         }, "required": ["user_id", "group_id"]}),

    # ── Categories / Entities / Documents ──
    Tool(name="glpi_list_categories", description="List ticket categories",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_list_entities", description="List entities",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_entity", description="Get an entity",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),
    Tool(name="glpi_list_documents", description="List documents",
         inputSchema={"type": "object", "properties": {"limit": {"type": "number"}}}),
    Tool(name="glpi_get_document", description="Get a document",
         inputSchema={"type": "object", "properties": {"id": {"type": "number"}}, "required": ["id"]}),

    # ── Stats / Session / Search ──
    Tool(name="glpi_get_ticket_stats", description="Ticket statistics by status",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="glpi_get_asset_stats", description="Asset inventory statistics",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="glpi_get_session_info", description="Current session info (profile, entities, permissions)",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="glpi_search", description="Advanced search using criteria",
         inputSchema={"type": "object", "properties": {
             "itemtype": {"type": "string"},
             "field": {"type": "number"},
             "searchtype": {"type": "string", "enum": ["contains", "equals", "notequals", "lessthan", "morethan", "under", "notunder"]},
             "value": {"type": "string"},
         }, "required": ["itemtype", "field", "searchtype", "value"]}),
]


@app_server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    g = glpi()
    a = arguments or {}

    try:
        match name:
            # ── Tickets ──────────────────────────────────────────────────────
            case "glpi_list_tickets":
                limit = a.get("limit", 50)
                tickets = await g.get_tickets({"range": _range(limit), "order": a.get("order", "DESC")})
                data = [{"id": t.get("id"), "name": t.get("name"), "status": TICKET_STATUS.get(t.get("status"), t.get("status")),
                         "urgency": TICKET_URGENCY.get(t.get("urgency"), t.get("urgency")),
                         "date": t.get("date"), "date_mod": t.get("date_mod")} for t in tickets]
                return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]

            case "glpi_get_ticket":
                _req(a, "id")
                ticket = await g.get_ticket(a["id"])
                followups = await g.get_ticket_followups(a["id"])
                tasks = await g.get_ticket_tasks(a["id"])
                return [TextContent(type="text", text=json.dumps({
                    **ticket,
                    "status_label": TICKET_STATUS.get(ticket.get("status")),
                    "urgency_label": TICKET_URGENCY.get(ticket.get("urgency")),
                    "followups": followups, "tasks": tasks,
                }, indent=2, default=str))]

            case "glpi_create_ticket":
                _req(a, "name", "content")
                result = await g.create_ticket({
                    "name": a["name"], "content": a["content"],
                    "urgency": a.get("urgency", 3), "type": a.get("type", 1),
                    **({} if not a.get("category_id") else {"itilcategories_id": a["category_id"]}),
                    **({} if not a.get("user_id_assign") else {"_users_id_assign": a["user_id_assign"]}),
                    **({} if not a.get("group_id_assign") else {"_groups_id_assign": a["group_id_assign"]}),
                })
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            case "glpi_update_ticket":
                _req(a, "id")
                updates = {k: a[k] for k in ("name", "content", "status", "urgency") if a.get(k)}
                await g.update_ticket(a["id"], updates)
                return [TextContent(type="text", text=json.dumps({"success": True, "message": f"Ticket {a['id']} updated"}))]

            case "glpi_delete_ticket":
                _req(a, "id")
                await g.delete_ticket(a["id"], a.get("force", False))
                return [TextContent(type="text", text=json.dumps({"success": True, "message": f"Ticket {a['id']} deleted"}))]

            case "glpi_add_followup":
                _req(a, "ticket_id", "content")
                result = await g.add_ticket_followup(a["ticket_id"], a["content"], a.get("is_private", False))
                return [TextContent(type="text", text=json.dumps({"success": True, "followup_id": result.get("id")}))]

            case "glpi_add_task":
                _req(a, "ticket_id", "content")
                extra = {k: a[k] for k in ("is_private", "actiontime", "state", "users_id_tech") if a.get(k) is not None}
                result = await g.add_ticket_task(a["ticket_id"], a["content"], extra)
                return [TextContent(type="text", text=json.dumps({"success": True, "task_id": result.get("id")}))]

            case "glpi_add_solution":
                _req(a, "ticket_id", "content")
                result = await g.add_ticket_solution(a["ticket_id"], a["content"], a.get("solutiontypes_id"))
                return [TextContent(type="text", text=json.dumps({"success": True, "solution_id": result.get("id")}))]

            case "glpi_assign_ticket":
                _req(a, "ticket_id", "user_id")
                result = await g.assign_ticket(a["ticket_id"], {"users_id": a["user_id"], "type": a.get("type", 2)})
                return [TextContent(type="text", text=json.dumps({"success": True, "assignment_id": result.get("id")}))]

            case "glpi_get_ticket_tasks":
                _req(a, "ticket_id")
                return [TextContent(type="text", text=json.dumps(await g.get_ticket_tasks(a["ticket_id"]), indent=2, default=str))]

            case "glpi_get_ticket_followups":
                _req(a, "ticket_id")
                return [TextContent(type="text", text=json.dumps(await g.get_ticket_followups(a["ticket_id"]), indent=2, default=str))]

            # ── Problems ─────────────────────────────────────────────────────
            case "glpi_list_problems":
                limit = a.get("limit", 50)
                problems = await g.get_problems({"range": _range(limit), "order": a.get("order", "DESC")})
                data = [{"id": p.get("id"), "name": p.get("name"),
                         "status": PROBLEM_STATUS.get(p.get("status"), p.get("status")),
                         "urgency": TICKET_URGENCY.get(p.get("urgency"), p.get("urgency")),
                         "date": p.get("date")} for p in problems]
                return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]

            case "glpi_get_problem":
                _req(a, "id")
                p = await g.get_problem(a["id"])
                return [TextContent(type="text", text=json.dumps({
                    **p,
                    "status_label": PROBLEM_STATUS.get(p.get("status")),
                    "urgency_label": TICKET_URGENCY.get(p.get("urgency")),
                }, indent=2, default=str))]

            case "glpi_create_problem":
                _req(a, "name", "content")
                result = await g.create_problem({
                    "name": a["name"], "content": a["content"],
                    **{k: a[k] for k in ("urgency", "impact", "priority") if a.get(k)},
                    **({} if not a.get("category_id") else {"itilcategories_id": a["category_id"]}),
                })
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            case "glpi_update_problem":
                _req(a, "id")
                updates = {k: a[k] for k in ("name", "content", "status", "urgency") if a.get(k)}
                await g.update_problem(a["id"], updates)
                return [TextContent(type="text", text=json.dumps({"success": True, "message": f"Problem {a['id']} updated"}))]

            # ── Changes ──────────────────────────────────────────────────────
            case "glpi_list_changes":
                limit = a.get("limit", 50)
                changes = await g.get_changes({"range": _range(limit), "order": a.get("order", "DESC")})
                data = [{"id": c.get("id"), "name": c.get("name"),
                         "status": CHANGE_STATUS.get(c.get("status"), c.get("status")),
                         "urgency": TICKET_URGENCY.get(c.get("urgency"), c.get("urgency")),
                         "date": c.get("date")} for c in changes]
                return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]

            case "glpi_get_change":
                _req(a, "id")
                c = await g.get_change(a["id"])
                return [TextContent(type="text", text=json.dumps({
                    **c,
                    "status_label": CHANGE_STATUS.get(c.get("status")),
                    "urgency_label": TICKET_URGENCY.get(c.get("urgency")),
                }, indent=2, default=str))]

            case "glpi_create_change":
                _req(a, "name", "content")
                result = await g.create_change({
                    "name": a["name"], "content": a["content"],
                    **{k: a[k] for k in ("urgency", "impact", "priority") if a.get(k)},
                    **({} if not a.get("category_id") else {"itilcategories_id": a["category_id"]}),
                })
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            case "glpi_update_change":
                _req(a, "id")
                updates = {k: a[k] for k in ("name", "content", "status") if a.get(k)}
                await g.update_change(a["id"], updates)
                return [TextContent(type="text", text=json.dumps({"success": True, "message": f"Change {a['id']} updated"}))]

            # ── Computers ────────────────────────────────────────────────────
            case "glpi_list_computers":
                limit = a.get("limit", 50)
                computers = await g.get_computers({"range": _range(limit), "is_deleted": int(a.get("include_deleted", False))})
                return [TextContent(type="text", text=json.dumps(computers, indent=2, default=str))]

            case "glpi_get_computer":
                _req(a, "id")
                params = {k: int(a[k]) for k in ("with_softwares", "with_connections", "with_networkports") if a.get(k)}
                computer = await g.get_computer(a["id"], params or None)
                return [TextContent(type="text", text=json.dumps(computer, indent=2, default=str))]

            case "glpi_create_computer":
                _req(a, "name")
                data = {k: a[k] for k in ("name", "serial", "otherserial", "contact", "comment",
                                           "locations_id", "states_id", "computertypes_id", "manufacturers_id") if a.get(k)}
                result = await g.create_computer(data)
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            case "glpi_update_computer":
                _req(a, "id")
                updates = {k: a[k] for k in ("name", "serial", "comment", "locations_id", "states_id") if a.get(k)}
                await g.update_computer(a["id"], updates)
                return [TextContent(type="text", text=json.dumps({"success": True, "message": f"Computer {a['id']} updated"}))]

            case "glpi_delete_computer":
                _req(a, "id")
                await g.delete_computer(a["id"], a.get("force", False))
                return [TextContent(type="text", text=json.dumps({"success": True, "message": f"Computer {a['id']} deleted"}))]

            # ── Software ─────────────────────────────────────────────────────
            case "glpi_list_softwares":
                softwares = await g.get_softwares({"range": _range(a.get("limit", 50))})
                return [TextContent(type="text", text=json.dumps(softwares, indent=2, default=str))]

            case "glpi_get_software":
                _req(a, "id")
                return [TextContent(type="text", text=json.dumps(await g.get_software(a["id"]), indent=2, default=str))]

            case "glpi_create_software":
                _req(a, "name")
                data = {k: a[k] for k in ("name", "comment", "manufacturers_id", "softwarecategories_id") if a.get(k)}
                result = await g.create_software(data)
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            # ── Network equipment ────────────────────────────────────────────
            case "glpi_list_network_equipments":
                eqs = await g.get_network_equipments({"range": _range(a.get("limit", 50))})
                return [TextContent(type="text", text=json.dumps(eqs, indent=2, default=str))]

            case "glpi_get_network_equipment":
                _req(a, "id")
                params = {"with_networkports": 1} if a.get("with_networkports") else None
                eq = await g.get_network_equipment(a["id"], params)
                return [TextContent(type="text", text=json.dumps(eq, indent=2, default=str))]

            # ── Printers ─────────────────────────────────────────────────────
            case "glpi_list_printers":
                return [TextContent(type="text", text=json.dumps(await g.get_printers({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_printer":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_printer(a["id"]), indent=2, default=str))]

            # ── Monitors ─────────────────────────────────────────────────────
            case "glpi_list_monitors":
                return [TextContent(type="text", text=json.dumps(await g.get_monitors({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_monitor":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_monitor(a["id"]), indent=2, default=str))]

            # ── Phones ───────────────────────────────────────────────────────
            case "glpi_list_phones":
                return [TextContent(type="text", text=json.dumps(await g.get_phones({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_phone":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_phone(a["id"]), indent=2, default=str))]

            # ── Knowledge base ───────────────────────────────────────────────
            case "glpi_list_knowbase":
                return [TextContent(type="text", text=json.dumps(await g.get_knowbase_items({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_knowbase_item":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_knowbase_item(a["id"]), indent=2, default=str))]
            case "glpi_search_knowbase":
                _req(a, "query"); return [TextContent(type="text", text=json.dumps(await g.search_knowbase(a["query"]), indent=2, default=str))]
            case "glpi_create_knowbase_item":
                _req(a, "name", "answer")
                data = {k: a[k] for k in ("name", "answer", "is_faq", "knowbaseitemcategories_id") if a.get(k) is not None}
                result = await g.create_knowbase_item(data)
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            # ── Contracts ────────────────────────────────────────────────────
            case "glpi_list_contracts":
                return [TextContent(type="text", text=json.dumps(await g.get_contracts({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_contract":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_contract(a["id"]), indent=2, default=str))]
            case "glpi_create_contract":
                _req(a, "name")
                data = {k: a[k] for k in ("name", "num", "begin_date", "duration", "notice", "comment") if a.get(k)}
                result = await g.create_contract(data)
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            # ── Suppliers ────────────────────────────────────────────────────
            case "glpi_list_suppliers":
                return [TextContent(type="text", text=json.dumps(await g.get_suppliers({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_supplier":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_supplier(a["id"]), indent=2, default=str))]
            case "glpi_create_supplier":
                _req(a, "name")
                data = {k: a[k] for k in ("name", "address", "postcode", "town", "country", "website", "phonenumber", "email") if a.get(k)}
                result = await g.create_supplier(data)
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            # ── Locations ────────────────────────────────────────────────────
            case "glpi_list_locations":
                return [TextContent(type="text", text=json.dumps(await g.get_locations({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_location":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_location(a["id"]), indent=2, default=str))]
            case "glpi_create_location":
                _req(a, "name")
                data = {k: a[k] for k in ("name", "address", "postcode", "town", "building", "room", "locations_id") if a.get(k)}
                result = await g.create_location(data)
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            # ── Projects ─────────────────────────────────────────────────────
            case "glpi_list_projects":
                return [TextContent(type="text", text=json.dumps(await g.get_projects({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_project":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_project(a["id"]), indent=2, default=str))]
            case "glpi_create_project":
                _req(a, "name")
                data = {k: a[k] for k in ("name", "code", "content", "priority", "plan_start_date", "plan_end_date", "users_id", "groups_id") if a.get(k)}
                result = await g.create_project(data)
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]
            case "glpi_update_project":
                _req(a, "id")
                updates = {k: a[k] for k in ("name", "content", "percent_done", "real_start_date", "real_end_date") if a.get(k) is not None}
                await g.update_project(a["id"], updates)
                return [TextContent(type="text", text=json.dumps({"success": True, "message": f"Project {a['id']} updated"}))]

            # ── Users ────────────────────────────────────────────────────────
            case "glpi_list_users":
                limit = a.get("limit", 50)
                params: dict = {"range": _range(limit)}
                if a.get("active_only", True):
                    params["is_active"] = 1
                return [TextContent(type="text", text=json.dumps(await g.get_users(params), indent=2, default=str))]
            case "glpi_get_user":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_user(a["id"]), indent=2, default=str))]
            case "glpi_search_user":
                _req(a, "name"); return [TextContent(type="text", text=json.dumps(await g.search_user(a["name"]), indent=2, default=str))]
            case "glpi_create_user":
                _req(a, "name")
                data = {k: a[k] for k in ("name", "password", "realname", "firstname", "email", "phone", "profiles_id") if a.get(k)}
                result = await g.create_user(data)
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            # ── Groups ───────────────────────────────────────────────────────
            case "glpi_list_groups":
                return [TextContent(type="text", text=json.dumps(await g.get_groups({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_group":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_group(a["id"]), indent=2, default=str))]
            case "glpi_create_group":
                _req(a, "name")
                data = {k: a[k] for k in ("name", "comment", "is_requester", "is_assign") if a.get(k) is not None}
                result = await g.create_group(data)
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]
            case "glpi_add_user_to_group":
                _req(a, "user_id", "group_id")
                result = await g.add_user_to_group(a["user_id"], a["group_id"], a.get("is_manager", False))
                return [TextContent(type="text", text=json.dumps({"success": True, **result}, indent=2, default=str))]

            # ── Categories / Entities / Documents ────────────────────────────
            case "glpi_list_categories":
                return [TextContent(type="text", text=json.dumps(await g.get_categories({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_list_entities":
                return [TextContent(type="text", text=json.dumps(await g.get_entities({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_entity":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_entity(a["id"]), indent=2, default=str))]
            case "glpi_list_documents":
                return [TextContent(type="text", text=json.dumps(await g.get_documents({"range": _range(a.get("limit", 50))}), indent=2, default=str))]
            case "glpi_get_document":
                _req(a, "id"); return [TextContent(type="text", text=json.dumps(await g.get_document(a["id"]), indent=2, default=str))]

            # ── Stats ────────────────────────────────────────────────────────
            case "glpi_get_ticket_stats":
                counts: dict = {}
                for status_id, label in TICKET_STATUS.items():
                    try:
                        tickets = await g.get_tickets({"range": "0-0", "criteria[0][field]": 12,
                                                        "criteria[0][searchtype]": "equals",
                                                        "criteria[0][value]": status_id})
                        counts[label] = len(tickets) if isinstance(tickets, list) else 0
                    except Exception:
                        counts[label] = 0
                return [TextContent(type="text", text=json.dumps({"ticket_counts_by_status": counts}, indent=2))]

            case "glpi_get_asset_stats":
                async def _count(method_name: str) -> int:
                    try:
                        result = await getattr(g, method_name)({"range": "0-0"})
                        return len(result) if isinstance(result, list) else 0
                    except Exception:
                        return 0
                stats = {
                    "computers": await _count("get_computers"),
                    "monitors": await _count("get_monitors"),
                    "printers": await _count("get_printers"),
                    "phones": await _count("get_phones"),
                    "network_equipments": await _count("get_network_equipments"),
                    "softwares": await _count("get_softwares"),
                }
                return [TextContent(type="text", text=json.dumps({"asset_stats": stats}, indent=2))]

            case "glpi_get_session_info":
                session = await g.get_full_session()
                return [TextContent(type="text", text=json.dumps(session, indent=2, default=str))]

            # ── Search ───────────────────────────────────────────────────────
            case "glpi_search":
                _req(a, "itemtype", "field", "searchtype", "value")
                result = await g.search(a["itemtype"], a["field"], a["searchtype"], a["value"])
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            case _:
                raise ValueError(f"Unknown tool: {name}")

    except ValueError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": f"GLPI API error: {str(e)}"}))]


# ── Starlette / SSE app ──────────────────────────────────────────────────────

def create_starlette_app() -> Starlette:
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await app_server.run(streams[0], streams[1], app_server.create_initialization_options())

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(create_starlette_app(), host=host, port=port)
