"""TCP SME Review Assistant (common assistant backend; only the SME Review profile is implemented).

Everything here is behind TCP_SME_ASSISTANT_ENABLED (default false). The pipeline (tcp_planner) never imports this
package; the assistant reads pipeline outputs and launches revision runs through tcp_ui.relations.
"""
