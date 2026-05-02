# Risk band boundaries and confidence parameters.
# These mirror the constants in risk_scoring_service.py until P4-A migrates them.
RISK_BANDS = {
    "default": {"low_max": 40, "medium_max": 70, "high_max": 85},
}
CONFIDENCE_PARAMS = {
    "base": 0.9,
    "decay": 0.1,
    "min": 0.4,
    "max": 0.95,
}
