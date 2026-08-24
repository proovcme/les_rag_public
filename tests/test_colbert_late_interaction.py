from backend.colbert_late_interaction import CircuitBreaker, maxsim_score, rerank_token_vectors


def test_maxsim_rewards_matching_different_query_tokens():
    query = [[1, 0], [0, 1]]
    exact = [[1, 0], [0, 1]]
    partial = [[1, 0], [1, 0]]
    assert maxsim_score(query, exact) == 2.0
    assert maxsim_score(query, partial) == 1.0
    assert rerank_token_vectors(query, [("partial", partial), ("exact", exact)], top_k=2)[0][0] == "exact"


def test_circuit_breaker_opens_and_self_recovers():
    breaker = CircuitBreaker(failure_limit=2, cooldown_sec=10)
    breaker.failure(now=100)
    assert breaker.allow(now=101)
    breaker.failure(now=102)
    assert not breaker.allow(now=105)
    assert breaker.allow(now=113)
