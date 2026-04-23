"""GLPI REST API async client."""

import os
from typing import Any, Optional
import httpx


class GlpiClient:
    def __init__(
        self,
        url: str,
        app_token: Optional[str] = None,
        user_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.base_url = url.rstrip("/")
        self.app_token = app_token
        self.user_token = user_token
        self.username = username
        self.password = password
        self.session_token: Optional[str] = None
        self._client = httpx.AsyncClient(timeout=30.0)

    def _headers(self, extra: Optional[dict] = None) -> dict:
        h = {"Content-Type": "application/json"}
        if self.app_token:
            h["App-Token"] = self.app_token
        if self.session_token:
            h["Session-Token"] = self.session_token
        if extra:
            h.update(extra)
        return h

    async def init_session(self) -> None:
        url = f"{self.base_url}/apirest.php/initSession"
        if self.user_token:
            resp = await self._client.get(
                url,
                headers={**self._headers(), "Authorization": f"user_token {self.user_token}"},
            )
        elif self.username and self.password:
            resp = await self._client.get(
                url,
                headers=self._headers(),
                auth=(self.username, self.password),
            )
        else:
            raise ValueError("Either user_token or username+password required")

        resp.raise_for_status()
        data = resp.json()
        self.session_token = data["session_token"]

    async def kill_session(self) -> None:
        if not self.session_token:
            return
        await self._client.get(
            f"{self.base_url}/apirest.php/killSession",
            headers=self._headers(),
        )
        self.session_token = None

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        if not self.session_token:
            await self.init_session()
        resp = await self._client.get(
            f"{self.base_url}/apirest.php/{path}",
            headers=self._headers(),
            params={k: v for k, v in (params or {}).items() if v is not None},
        )
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, data: dict) -> Any:
        if not self.session_token:
            await self.init_session()
        resp = await self._client.post(
            f"{self.base_url}/apirest.php/{path}",
            headers=self._headers(),
            json={"input": data},
        )
        resp.raise_for_status()
        return resp.json()

    async def _put(self, path: str, data: dict) -> Any:
        if not self.session_token:
            await self.init_session()
        resp = await self._client.put(
            f"{self.base_url}/apirest.php/{path}",
            headers=self._headers(),
            json={"input": data},
        )
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str, force: bool = False) -> Any:
        if not self.session_token:
            await self.init_session()
        resp = await self._client.delete(
            f"{self.base_url}/apirest.php/{path}",
            headers=self._headers(),
            params={"force_purge": 1 if force else 0},
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ── Generic list/get helpers ─────────────────────────────────────────────

    async def _list(self, itemtype: str, params: Optional[dict] = None) -> list:
        result = await self._get(itemtype, params)
        if isinstance(result, list):
            return result
        return []

    async def _item(self, itemtype: str, item_id: int, params: Optional[dict] = None) -> dict:
        return await self._get(f"{itemtype}/{item_id}", params)

    # ── Tickets ──────────────────────────────────────────────────────────────

    async def get_tickets(self, params: Optional[dict] = None) -> list:
        return await self._list("Ticket", params)

    async def get_ticket(self, ticket_id: int) -> dict:
        return await self._item("Ticket", ticket_id)

    async def create_ticket(self, data: dict) -> dict:
        return await self._post("Ticket", data)

    async def update_ticket(self, ticket_id: int, data: dict) -> dict:
        return await self._put(f"Ticket/{ticket_id}", data)

    async def delete_ticket(self, ticket_id: int, force: bool = False) -> dict:
        return await self._delete(f"Ticket/{ticket_id}", force)

    async def get_ticket_followups(self, ticket_id: int) -> list:
        result = await self._get(f"Ticket/{ticket_id}/ITILFollowup")
        return result if isinstance(result, list) else []

    async def add_ticket_followup(self, ticket_id: int, content: str, is_private: bool = False) -> dict:
        return await self._post(
            "ITILFollowup",
            {"items_id": ticket_id, "itemtype": "Ticket", "content": content, "is_private": int(is_private)},
        )

    async def get_ticket_tasks(self, ticket_id: int) -> list:
        result = await self._get(f"Ticket/{ticket_id}/TicketTask")
        return result if isinstance(result, list) else []

    async def add_ticket_task(self, ticket_id: int, content: str, extra: Optional[dict] = None) -> dict:
        data = {"tickets_id": ticket_id, "content": content}
        if extra:
            data.update({k: v for k, v in extra.items() if v is not None})
        return await self._post("TicketTask", data)

    async def add_ticket_solution(self, ticket_id: int, content: str, solutiontypes_id: Optional[int] = None) -> dict:
        data: dict = {"items_id": ticket_id, "itemtype": "Ticket", "content": content}
        if solutiontypes_id:
            data["solutiontypes_id"] = solutiontypes_id
        return await self._post("ITILSolution", data)

    async def assign_ticket(self, ticket_id: int, data: dict) -> dict:
        return await self._post("Ticket_User", {"tickets_id": ticket_id, **data})

    # ── Problems ─────────────────────────────────────────────────────────────

    async def get_problems(self, params: Optional[dict] = None) -> list:
        return await self._list("Problem", params)

    async def get_problem(self, problem_id: int) -> dict:
        return await self._item("Problem", problem_id)

    async def create_problem(self, data: dict) -> dict:
        return await self._post("Problem", data)

    async def update_problem(self, problem_id: int, data: dict) -> dict:
        return await self._put(f"Problem/{problem_id}", data)

    # ── Changes ──────────────────────────────────────────────────────────────

    async def get_changes(self, params: Optional[dict] = None) -> list:
        return await self._list("Change", params)

    async def get_change(self, change_id: int) -> dict:
        return await self._item("Change", change_id)

    async def create_change(self, data: dict) -> dict:
        return await self._post("Change", data)

    async def update_change(self, change_id: int, data: dict) -> dict:
        return await self._put(f"Change/{change_id}", data)

    # ── Computers ────────────────────────────────────────────────────────────

    async def get_computers(self, params: Optional[dict] = None) -> list:
        return await self._list("Computer", params)

    async def get_computer(self, computer_id: int, params: Optional[dict] = None) -> dict:
        return await self._item("Computer", computer_id, params)

    async def create_computer(self, data: dict) -> dict:
        return await self._post("Computer", data)

    async def update_computer(self, computer_id: int, data: dict) -> dict:
        return await self._put(f"Computer/{computer_id}", data)

    async def delete_computer(self, computer_id: int, force: bool = False) -> dict:
        return await self._delete(f"Computer/{computer_id}", force)

    # ── Software ─────────────────────────────────────────────────────────────

    async def get_softwares(self, params: Optional[dict] = None) -> list:
        return await self._list("Software", params)

    async def get_software(self, software_id: int) -> dict:
        return await self._item("Software", software_id)

    async def create_software(self, data: dict) -> dict:
        return await self._post("Software", data)

    # ── Network equipment ────────────────────────────────────────────────────

    async def get_network_equipments(self, params: Optional[dict] = None) -> list:
        return await self._list("NetworkEquipment", params)

    async def get_network_equipment(self, eq_id: int, params: Optional[dict] = None) -> dict:
        return await self._item("NetworkEquipment", eq_id, params)

    # ── Printers ─────────────────────────────────────────────────────────────

    async def get_printers(self, params: Optional[dict] = None) -> list:
        return await self._list("Printer", params)

    async def get_printer(self, printer_id: int) -> dict:
        return await self._item("Printer", printer_id)

    # ── Monitors ─────────────────────────────────────────────────────────────

    async def get_monitors(self, params: Optional[dict] = None) -> list:
        return await self._list("Monitor", params)

    async def get_monitor(self, monitor_id: int) -> dict:
        return await self._item("Monitor", monitor_id)

    # ── Phones ───────────────────────────────────────────────────────────────

    async def get_phones(self, params: Optional[dict] = None) -> list:
        return await self._list("Phone", params)

    async def get_phone(self, phone_id: int) -> dict:
        return await self._item("Phone", phone_id)

    # ── Knowledge base ───────────────────────────────────────────────────────

    async def get_knowbase_items(self, params: Optional[dict] = None) -> list:
        return await self._list("KnowbaseItem", params)

    async def get_knowbase_item(self, item_id: int) -> dict:
        return await self._item("KnowbaseItem", item_id)

    async def search_knowbase(self, query: str) -> list:
        return await self._list("KnowbaseItem", {"searchText[name]": query})

    async def create_knowbase_item(self, data: dict) -> dict:
        return await self._post("KnowbaseItem", data)

    # ── Contracts ────────────────────────────────────────────────────────────

    async def get_contracts(self, params: Optional[dict] = None) -> list:
        return await self._list("Contract", params)

    async def get_contract(self, contract_id: int) -> dict:
        return await self._item("Contract", contract_id)

    async def create_contract(self, data: dict) -> dict:
        return await self._post("Contract", data)

    # ── Suppliers ────────────────────────────────────────────────────────────

    async def get_suppliers(self, params: Optional[dict] = None) -> list:
        return await self._list("Supplier", params)

    async def get_supplier(self, supplier_id: int) -> dict:
        return await self._item("Supplier", supplier_id)

    async def create_supplier(self, data: dict) -> dict:
        return await self._post("Supplier", data)

    # ── Locations ────────────────────────────────────────────────────────────

    async def get_locations(self, params: Optional[dict] = None) -> list:
        return await self._list("Location", params)

    async def get_location(self, location_id: int) -> dict:
        return await self._item("Location", location_id)

    async def create_location(self, data: dict) -> dict:
        return await self._post("Location", data)

    # ── Projects ─────────────────────────────────────────────────────────────

    async def get_projects(self, params: Optional[dict] = None) -> list:
        return await self._list("Project", params)

    async def get_project(self, project_id: int) -> dict:
        return await self._item("Project", project_id)

    async def create_project(self, data: dict) -> dict:
        return await self._post("Project", data)

    async def update_project(self, project_id: int, data: dict) -> dict:
        return await self._put(f"Project/{project_id}", data)

    # ── Users ────────────────────────────────────────────────────────────────

    async def get_users(self, params: Optional[dict] = None) -> list:
        return await self._list("User", params)

    async def get_user(self, user_id: int) -> dict:
        return await self._item("User", user_id)

    async def search_user(self, name: str) -> list:
        return await self._list("User", {"searchText[name]": name})

    async def create_user(self, data: dict) -> dict:
        return await self._post("User", data)

    # ── Groups ───────────────────────────────────────────────────────────────

    async def get_groups(self, params: Optional[dict] = None) -> list:
        return await self._list("Group", params)

    async def get_group(self, group_id: int) -> dict:
        return await self._item("Group", group_id)

    async def create_group(self, data: dict) -> dict:
        return await self._post("Group", data)

    async def add_user_to_group(self, user_id: int, group_id: int, is_manager: bool = False) -> dict:
        return await self._post(
            "Group_User",
            {"users_id": user_id, "groups_id": group_id, "is_manager": int(is_manager)},
        )

    # ── Categories ───────────────────────────────────────────────────────────

    async def get_categories(self, params: Optional[dict] = None) -> list:
        return await self._list("ITILCategory", params)

    # ── Entities ─────────────────────────────────────────────────────────────

    async def get_entities(self, params: Optional[dict] = None) -> list:
        return await self._list("Entity", params)

    async def get_entity(self, entity_id: int) -> dict:
        return await self._item("Entity", entity_id)

    # ── Documents ────────────────────────────────────────────────────────────

    async def get_documents(self, params: Optional[dict] = None) -> list:
        return await self._list("Document", params)

    async def get_document(self, document_id: int) -> dict:
        return await self._item("Document", document_id)

    # ── Session info ─────────────────────────────────────────────────────────

    async def get_full_session(self) -> dict:
        return await self._get("getFullSession")

    # ── Search ───────────────────────────────────────────────────────────────

    async def search(
        self,
        itemtype: str,
        field: int,
        searchtype: str,
        value: str,
    ) -> dict:
        params = {
            "criteria[0][field]": field,
            "criteria[0][searchtype]": searchtype,
            "criteria[0][value]": value,
        }
        return await self._get(f"search/{itemtype}", params)

    async def close(self) -> None:
        await self.kill_session()
        await self._client.aclose()


def client_from_env() -> GlpiClient:
    url = os.environ.get("GLPI_URL")
    if not url:
        raise ValueError("GLPI_URL environment variable is required")
    return GlpiClient(
        url=url,
        app_token=os.environ.get("GLPI_APP_TOKEN"),
        user_token=os.environ.get("GLPI_USER_TOKEN"),
        username=os.environ.get("GLPI_USERNAME"),
        password=os.environ.get("GLPI_PASSWORD"),
    )
