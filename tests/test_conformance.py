from __future__ import annotations

import unittest

from balance_paypal.conformance import run_mutation_suite
from balance_paypal.fault_matrix import FAULTS, run_fault_matrix


class ConformanceTests(unittest.TestCase):
    def test_reference_passes_and_each_broken_variant_is_killed(self):
        result = run_mutation_suite()
        self.assertTrue(result["reference_passes"])
        self.assertEqual(4, result["mutations_killed"])
        self.assertTrue(all(item["killed"] for item in result["mutations"]))

    def test_same_four_faults_compare_naive_and_governed(self):
        result = run_fault_matrix(5)
        self.assertEqual(20, result["totals"]["trials"])
        self.assertEqual(20, result["totals"]["naive_replacement_order_cases"])
        self.assertEqual(0, result["totals"]["governed_replacement_order_cases"])
        self.assertEqual(set(FAULTS), {item["fault"] for item in result["faults"]})


if __name__ == "__main__":
    unittest.main()
