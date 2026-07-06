"""Causality unit test for the Stage D HMM forward filter: appending future
bars must never change the filtered state probability of an earlier bar.
This is the mandatory self-test called out in the Stage D task spec."""
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.og_hmm_gate import forward_filter, fit_session_hmm


def test_forward_filter_is_causal():
    rng = np.random.default_rng(0)
    n_states, d = 3, 3
    X = rng.normal(size=(200, d))
    startprob, transmat, means, covars = fit_session_hmm(X, n_states, random_state=42)

    n_prefix = 50
    alpha_full = forward_filter(X, startprob, transmat, means, covars)
    alpha_prefix = forward_filter(X[:n_prefix], startprob, transmat, means, covars)

    assert np.allclose(alpha_full[:n_prefix], alpha_prefix, atol=1e-10), (
        "Forward filter is not causal: appending future observations changed "
        "the filtered probabilities of earlier bars.")

    # Also check incrementally appending one bar at a time never perturbs history.
    alpha_running = forward_filter(X[:10], startprob, transmat, means, covars)
    for extra in range(11, 40):
        alpha_extended = forward_filter(X[:extra], startprob, transmat, means, covars)
        assert np.allclose(alpha_extended[:10], alpha_running, atol=1e-10)


if __name__ == "__main__":
    test_forward_filter_is_causal()
    print("PASS: forward filter is causal")
