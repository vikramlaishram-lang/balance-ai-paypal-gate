from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Variant:
    name: str
    barrier_before_post: bool = True
    agent_has_secret: bool = False
    approval_bound_to_digest: bool = True
    reconcile_is_read_only: bool = True


REFERENCE = Variant("reference")
MUTATIONS = (
    Variant("barrier_after_post", barrier_before_post=False),
    Variant("agent_holds_secret", agent_has_secret=True),
    Variant("approval_not_bound", approval_bound_to_digest=False),
    Variant("reconcile_retries", reconcile_is_read_only=False),
)


def _barrier_scenario(variant: Variant) -> bool:
    # Both workers arrive before either POST. A pre-POST CAS admits one; a post-POST
    # barrier admits both provider effects.
    provider_posts = 1 if variant.barrier_before_post else 2
    return provider_posts == 1


def _credential_scenario(variant: Variant) -> bool:
    return not variant.agent_has_secret


def _approval_scenario(variant: Variant) -> bool:
    original_digest = "a" * 64
    changed_digest = "b" * 64
    approved = original_digest == changed_digest if variant.approval_bound_to_digest else True
    return not approved


def _reconcile_scenario(variant: Variant) -> bool:
    provider_posts_before = 1
    provider_posts_after = provider_posts_before if variant.reconcile_is_read_only else 2
    return provider_posts_after == provider_posts_before


SCENARIOS: tuple[tuple[str, Callable[[Variant], bool]], ...] = (
    ("barrier_precedes_post", _barrier_scenario),
    ("agent_has_no_secret", _credential_scenario),
    ("approval_binds_digest", _approval_scenario),
    ("reconcile_never_posts", _reconcile_scenario),
)


def run_mutation_suite() -> dict[str, object]:
    reference = {name: scenario(REFERENCE) for name, scenario in SCENARIOS}
    mutations = []
    for variant in MUTATIONS:
        results = {name: scenario(variant) for name, scenario in SCENARIOS}
        broken_scenarios = [name for name, passed in results.items() if not passed]
        mutations.append(
            {
                "variant": variant.name,
                "results": results,
                "killed": bool(broken_scenarios),
                "broken_scenarios": broken_scenarios,
            }
        )
    return {
        "classification": "DETERMINISTIC_ARCHITECTURE_MUTATION_SUITE_NOT_T5",
        "reference_passes": all(reference.values()),
        "reference": reference,
        "mutations": mutations,
        "mutations_killed": sum(1 for item in mutations if item["killed"]),
    }
