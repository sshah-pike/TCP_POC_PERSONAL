"""Registers every assistant tool with its permission, determinism, mutation and external-call attributes."""


def register_all(c):
    """Tools are added phase by phase; each module exposes register(container)."""
    import importlib
    for mod in ("review_tools", "conversations", "versions", "decisions", "decision_tools", "proposals", "pipeline_controller", "version_tools", "exception_tools",
                "geometry_tools", "object_tools", "interpret_tools", "clarify_forms", "assistant_state"):
        try:
            m = importlib.import_module(f"tcp_planner.review.assistant.services.{mod}")
        except ModuleNotFoundError as e:
            if e.name == f"tcp_planner.review.assistant.services.{mod}": continue
            raise
        m.register(c)
