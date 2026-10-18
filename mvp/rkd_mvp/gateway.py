from __future__ import annotations

from typing import Any, Callable

from .models import CommandEnvelope
from .store import AccessDenied, ConflictError, InMemoryStore


class CommandGateway:
    HUMAN_GATES = {"SelectConceptOption", "ApproveDesignIntent", "SelectOption"}

    def __init__(self, store: InMemoryStore) -> None:
        self.store = store
        self.handlers: dict[str, Callable[[CommandEnvelope], dict[str, Any]]] = {}

    def register(self, name: str, handler: Callable[[CommandEnvelope], dict[str, Any]]) -> None:
        self.handlers[name] = handler

    def submit(self, command: CommandEnvelope) -> dict[str, Any]:
        with self.store.transaction():
            self.store.require_project(command.context)
            cached = self.store.command_result(command)
            if cached:
                return cached
            if command.context.actor_type in {"agent", "executor"} and command.command_name in self.HUMAN_GATES:
                raise AccessDenied("human approval required")
            handler = self.handlers.get(command.command_name)
            if not handler:
                raise ConflictError(f"unsupported command: {command.command_name}")
            result = dict(handler(command))
            result["command_name"] = command.command_name
            self.store.record_command(command, result)
            self.store.append_audit(
                command.context,
                "command.accepted",
                "Command",
                command.command_id,
                "succeeded",
                {"command_name": command.command_name, "aggregate_id": command.aggregate_id},
            )
            return result
