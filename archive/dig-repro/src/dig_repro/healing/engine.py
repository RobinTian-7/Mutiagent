"""DIG-based structure-driven healing."""

from __future__ import annotations

from dig_repro.runtime.models import InterventionRecord


def propose_interventions(*, state, detections: list, logical_time: int) -> list[InterventionRecord]:
    interventions: list[InterventionRecord] = []
    by_kind = {}
    for detection in detections:
        by_kind.setdefault(detection.kind, detection)
    root_coverages = [set(event.coverage_ids) for event in state.events.values() if event.parent_event_ids == []]
    root_coverage = max(root_coverages, key=len) if root_coverages else set()
    solution_coverages = [
        set(event.payload.get("covered_ids", []))
        for event in state.events.values()
        if event.event_type.value == "solution"
    ]
    union_solution_coverage = set().union(*solution_coverages) if solution_coverages else set()
    pending_non_solution = [
        delivery.event_id
        for delivery in state.deliveries.values()
        if delivery.status.value == "pending"
        and state.events[delivery.event_id].event_type.value != "solution"
    ]
    if (
        root_coverage
        and union_solution_coverage == root_coverage
        and not any(event.final_answer for event in state.events.values())
    ):
        interventions.append(
            InterventionRecord(
                intervention_id=f"int:{logical_time}:{len(interventions)}",
                logical_time=logical_time,
                source="dig",
                kind="create_system_event",
                recipient_ids=state.all_agent_ids[:2],
                message="Coverage is complete. Merge current partial solutions and submit.",
                detector_kinds=["MC"],
            )
        )
    detection = by_kind.get("ER")
    if detection and detection.event_ids:
        interventions.append(
            InterventionRecord(
                intervention_id=f"int:{logical_time}:{len(interventions)}",
                logical_time=logical_time,
                source="dig",
                kind="inject_and_reroute",
                target_event_ids=detection.event_ids[:1],
                recipient_ids=state.all_agent_ids[:2],
                message="Stop forwarding this item indefinitely. Fetch raw data or aggregate existing evidence.",
                detector_kinds=[detection.kind],
            )
        )
    detection = by_kind.get("DL")
    if detection:
        pending = [
            delivery.event_id
            for delivery in state.deliveries.values()
            if delivery.status.value == "pending"
        ]
        if pending:
            interventions.append(
                InterventionRecord(
                    intervention_id=f"int:{logical_time}:{len(interventions)}",
                    logical_time=logical_time,
                    source="dig",
                    kind="inject_and_reroute",
                    target_event_ids=pending[:1],
                    recipient_ids=state.all_agent_ids[:2],
                    message="Progress has stalled. Prioritize this event now instead of waiting.",
                    detector_kinds=[detection.kind],
                )
            )
    detection = by_kind.get("RSP")
    if detection and pending_non_solution:
        interventions.append(
            InterventionRecord(
                intervention_id=f"int:{logical_time}:{len(interventions)}",
                logical_time=logical_time,
                source="dig",
                kind="inject_and_reroute",
                target_event_ids=pending_non_solution[:1],
                recipient_ids=state.all_agent_ids[:2],
                message="Stop recomputing overlapping work. Finish unresolved problem shards first.",
                detector_kinds=[detection.kind],
            )
        )
    detection = by_kind.get("MC")
    if detection:
        interventions.append(
            InterventionRecord(
                intervention_id=f"int:{logical_time}:{len(interventions)}",
                logical_time=logical_time,
                source="dig",
                kind="create_system_event",
                recipient_ids=state.all_agent_ids[:2],
                message="All reachable work appears consumed. Produce and submit the best available merged solution now.",
                detector_kinds=[detection.kind],
            )
        )
    return interventions
