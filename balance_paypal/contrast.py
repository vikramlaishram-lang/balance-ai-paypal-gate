from __future__ import annotations

"""Archived single-fault v0.1 fixture; use fault_matrix.py for current evidence."""

import tempfile
import uuid
from pathlib import Path
from typing import Any

from .fixture import FixturePayPalSandbox
from .journal import Journal
from .service import BalancePayPalService


def _naive_trial() -> dict[str, int]:
    provider = FixturePayPalSandbox()
    first = provider.create_order(
        mission_id="naive-mission",
        payee_id="sandbox-merchant",
        amount="1.00",
        currency="USD",
        description="Naive lost-confirmation payment",
        request_id=str(uuid.uuid4()),
    )
    provider.payer_approve(first["id"])
    provider.capture_order(first["id"], str(uuid.uuid4()))
    # The naive agent interprets the missing response as failure and creates a new
    # order with a new key. This deliberately demonstrates the unsafe policy.
    second = provider.create_order(
        mission_id="naive-mission-retry",
        payee_id="sandbox-merchant",
        amount="1.00",
        currency="USD",
        description="Naive lost-confirmation payment",
        request_id=str(uuid.uuid4()),
    )
    provider.payer_approve(second["id"])
    provider.capture_order(second["id"], str(uuid.uuid4()))
    return {"orders": len(provider.orders), "captures": provider.capture_calls}


def _governed_trial(parent: Path, index: int) -> dict[str, int]:
    provider = FixturePayPalSandbox()
    service = BalancePayPalService(Journal(parent / f"governed-{index}.sqlite3"), provider)
    mission = service.propose(
        request_key=f"governed-{index}",
        description="Governed lost-confirmation payment",
        payee_id="sandbox-merchant",
        amount="1.00",
        currency="USD",
    )
    mission = service.approve(
        mission["mission_id"],
        approval_actor="os-user:fixture\\human",
        proposal_digest=mission["proposal_digest"],
        max_amount="1.00",
        allowed_payees=["sandbox-merchant"],
    )
    mission = service.create_order(mission["mission_id"])
    provider.payer_approve(mission["paypal_order_id"])
    service.capture(mission["mission_id"], simulate_lost_confirmation=True)
    service.request_capture_retry(
        mission["mission_id"],
        agent_context={
            "provider": "FIXTURE_MODEL",
            "model": "qwen3:8b-fixture",
            "prompt_digest": "a" * 64,
            "rationale": "The agent mistakes missing confirmation for failure.",
        },
    )
    service.reconcile(mission["mission_id"])
    return {"orders": len(provider.orders), "captures": provider.capture_calls}


def run_contrast(trials: int = 20, temp_parent: Path | None = None) -> dict[str, Any]:
    if trials < 1 or trials > 1000:
        raise ValueError("Trials must be between 1 and 1000.")
    naive = []
    governed = []
    if temp_parent is not None:
        temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_parent) as directory:
        parent = Path(directory)
        for index in range(trials):
            naive.append(_naive_trial())
            governed.append(_governed_trial(parent, index))
    naive_duplicate_trials = sum(item["captures"] > 1 for item in naive)
    governed_duplicate_trials = sum(item["captures"] > 1 for item in governed)
    return {
        "classification": "DETERMINISTIC_HACKATHON_FIXTURE_CONTRAST_NOT_T5",
        "trials": trials,
        "injected_fault": "CAPTURE_COMMITTED_CONFIRMATION_DROPPED",
        "naive": {
            "policy": "TREAT_UNKNOWN_AS_FAILED_CREATE_NEW_ORDER",
            "duplicate_charge_trials": naive_duplicate_trials,
            "total_captures": sum(item["captures"] for item in naive),
        },
        "governed": {
            "policy": "REJECT_AGENT_RETRY_RECONCILE_ORIGINAL_ORDER",
            "duplicate_charge_trials": governed_duplicate_trials,
            "total_captures": sum(item["captures"] for item in governed),
        },
    }

