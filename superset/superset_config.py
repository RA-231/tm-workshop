# Workshop Superset config — no auth hardening, no async workers. Keep it boring.
SECRET_KEY = "space-summit-2026-workshop-not-a-secret"

# Let attendees hammer SQL Lab without hitting limits.
SQLLAB_TIMEOUT = 120
SUPERSET_WEBSERVER_TIMEOUT = 120
ROW_LIMIT = 10_000

FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
}
