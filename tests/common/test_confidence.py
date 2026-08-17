"""Tests for common/stats_model/confidence.py. See docs/plans/10 Phase 1 calibration."""
from common.stats_model.confidence import confidence_for


def test_toss_up_is_low():
    assert confidence_for(0.5) == "LOW"
    assert confidence_for(0.48) == "LOW"


def test_moderate_distance_is_medium():
    assert confidence_for(0.56) == "MEDIUM"
    assert confidence_for(0.44) == "MEDIUM"


def test_large_distance_is_high():
    assert confidence_for(0.65) == "HIGH"
    assert confidence_for(0.30) == "HIGH"


def test_symmetric_around_toss_up():
    for p in (0.51, 0.58, 0.7, 0.85):
        assert confidence_for(p) == confidence_for(1 - p)
