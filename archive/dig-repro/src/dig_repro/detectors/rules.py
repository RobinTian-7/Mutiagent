"""Rule-based structural detectors for DIG."""

from __future__ import annotations

from collections import Counter, defaultdict

from dig_repro.detectors.models import DetectionRecord
from dig_repro.events.models import EventType
from dig_repro.runtime.models import DeliveryStatus, ExperimentConfig


def detect_errors(*, state, config: ExperimentConfig) -> list[DetectionRecord]:
    detections: list[DetectionRecord] = []
    detections.extend(_detect_early_termination(state))
    detections.extend(_detect_missing_termination(state, config))
    detections.extend(_detect_orphaned_events(state))
    detections.extend(_detect_deadlock(state, config))
    detections.extend(_detect_excessive_rerouting(state, config))
    detections.extend(_detect_cross_lineage_aggregation(state))
    detections.extend(_detect_repeated_subproblem_solving(state))
    return detections


def _detect_early_termination(state) -> list[DetectionRecord]:
    submitted = [event for event in state.events.values() if event.final_answer]
    if not submitted:
        return []
    pending_work = [
        delivery
        for delivery in state.deliveries.values()
        if delivery.status == DeliveryStatus.PENDING
        and state.events[delivery.event_id].event_type != EventType.SOLUTION
    ]
    if pending_work:
        return [
            DetectionRecord(
                kind="ET",
                severity="critical",
                message="A final submission exists while reachable work is still pending.",
                event_ids=[delivery.event_id for delivery in pending_work[:5]],
            )
        ]
    return []


def _detect_missing_termination(state, config: ExperimentConfig) -> list[DetectionRecord]:
    if any(event.final_answer for event in state.events.values()):
        return []
    pending = [delivery for delivery in state.deliveries.values() if delivery.status == DeliveryStatus.PENDING]
    if pending:
        return []
    if state.logical_time >= config.missing_termination_window:
        return [
            DetectionRecord(
                kind="MC",
                severity="high",
                message="No final submission was generated after work was exhausted.",
            )
        ]
    return []


def _detect_orphaned_events(state) -> list[DetectionRecord]:
    detections = []
    by_event = defaultdict(list)
    for delivery in state.deliveries.values():
        by_event[delivery.event_id].append(delivery)
    for event_id, deliveries in by_event.items():
        if any(delivery.status == DeliveryStatus.CONSUMED for delivery in deliveries):
            continue
        if not deliveries or all(delivery.status in {DeliveryStatus.DISCARDED, DeliveryStatus.REROUTED} for delivery in deliveries):
            detections.append(
                DetectionRecord(
                    kind="OE",
                    severity="high",
                    message="Event became unreachable before being consumed.",
                    event_ids=[event_id],
                )
            )
    return detections


def _detect_deadlock(state, config: ExperimentConfig) -> list[DetectionRecord]:
    if len(state.activations) < config.deadlock_window:
        return []
    recent = state.activations[-config.deadlock_window :]
    if not recent:
        return []
    if all(
        activation.waited_event_ids
        and not activation.processed_event_ids
        and not activation.produced_event_ids
        for activation in recent
    ):
        pending = [delivery.event_id for delivery in state.deliveries.values() if delivery.status == DeliveryStatus.PENDING]
        if pending:
            return [
                DetectionRecord(
                    kind="DL",
                    severity="critical",
                    message="Agents waited repeatedly while pending work remained.",
                    event_ids=pending[:5],
                    activation_ids=[activation.activation_id for activation in recent],
                )
            ]
    return []


def _detect_excessive_rerouting(state, config: ExperimentConfig) -> list[DetectionRecord]:
    detections = []
    for event in state.events.values():
        if event.reroute_count > config.reroute_threshold and not event.consumed_by_activation_ids:
            detections.append(
                DetectionRecord(
                    kind="ER",
                    severity="medium",
                    message="Event has been rerouted repeatedly without productive consumption.",
                    event_ids=[event.event_id],
                )
            )
    return detections


def _detect_cross_lineage_aggregation(state) -> list[DetectionRecord]:
    detections = []
    for activation in state.activations:
        lineages = {
            state.events[event_id].lineage_id
            for event_id in activation.processed_event_ids
            if event_id in state.events and state.events[event_id].event_type.value == "solution"
        }
        if len(lineages) > 1:
            detections.append(
                DetectionRecord(
                    kind="CLA",
                    severity="low",
                    message="One activation aggregated solutions from different lineages.",
                    event_ids=activation.processed_event_ids,
                    activation_ids=[activation.activation_id],
                )
            )
    return detections


def _detect_repeated_subproblem_solving(state) -> list[DetectionRecord]:
    detections = []
    solution_events = [event for event in state.events.values() if event.event_type.value == "solution"]
    for index, event in enumerate(solution_events):
        coverage = set(event.coverage_ids)
        for other in solution_events[index + 1 :]:
            if event.root_problem_id != other.root_problem_id:
                continue
            overlap = coverage.intersection(other.coverage_ids)
            if overlap and event.created_by_activation_id != other.created_by_activation_id:
                detections.append(
                    DetectionRecord(
                        kind="RSP",
                        severity="low",
                        message="Multiple activations produced overlapping solutions.",
                        event_ids=[event.event_id, other.event_id],
                    )
                )
    counts = Counter(record.kind for record in detections)
    if counts["RSP"] > 5:
        detections.append(
            DetectionRecord(
                kind="RSP",
                severity="medium",
                message="Repeated subproblem solving is widespread.",
            )
        )
    return detections
