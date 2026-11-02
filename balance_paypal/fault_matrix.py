from __future__ import annotations


FAULTS = (
    "DROPPED_CAPTURE_RESPONSE_AFTER_EFFECT",
    "HTTP_5XX_AFTER_PROVIDER_EFFECT",
    "PROCESS_KILLED_AFTER_BARRIER_AND_EFFECT",
    "CONCURRENT_EXECUTE",
)


def run_fault_matrix(trials_per_fault: int = 5) -> dict[str, object]:
    if trials_per_fault < 1:
        raise ValueError("trials_per_fault must be positive")
    rows = []
    for fault in FAULTS:
        # The naive policy treats uncertainty as failure and issues a new request/order.
        # The governed policy retains its barrier and resolves through the original order.
        naive_completed_order_captures = 2 * trials_per_fault
        governed_completed_order_captures = trials_per_fault
        rows.append(
            {
                "fault": fault,
                "trials": trials_per_fault,
                "naive_replacement_order_cases": trials_per_fault,
                "governed_replacement_order_cases": 0,
                "naive_completed_order_captures": naive_completed_order_captures,
                "governed_completed_order_captures": governed_completed_order_captures,
            }
        )
    return {
        "classification": (
            "DETERMINISTIC_REPLACEMENT_ORDER_CONTROL_MODEL_"
            "NOT_PAYPAL_EVIDENCE_NOT_T5"
        ),
        "faults": rows,
        "totals": {
            "trials": trials_per_fault * len(FAULTS),
            "naive_replacement_order_cases": trials_per_fault * len(FAULTS),
            "governed_replacement_order_cases": 0,
            "naive_completed_order_captures": trials_per_fault * len(FAULTS) * 2,
            "governed_completed_order_captures": trials_per_fault * len(FAULTS),
        },
    }
