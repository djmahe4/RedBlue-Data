"""
benchmarks/utils.py - Shared utilities for RedBlue benchmark tasks.
"""
from __future__ import annotations

from typing import List


def lcs_length(a: List[str], b: List[str]) -> int:
    """Compute the length of the Longest Common Subsequence of two token lists."""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    # Space-optimised O(m*n) DP
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(curr[j - 1], prev[j])
        prev, curr = curr, [0] * (n + 1)
    return prev[n]


def rouge_l(reference: str, hypothesis: str) -> float:
    """
    Compute ROUGE-L F1 score between *reference* and *hypothesis* strings.

    Returns a float in [0, 1].
    """
    ref_tokens = reference.lower().split()
    hyp_tokens = hypothesis.lower().split()
    if not ref_tokens or not hyp_tokens:
        return 0.0
    lcs = lcs_length(ref_tokens, hyp_tokens)
    precision = lcs / len(hyp_tokens)
    recall = lcs / len(ref_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
