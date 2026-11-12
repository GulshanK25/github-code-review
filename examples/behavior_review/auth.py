"""Example vulnerable authorization logic, for opt-in behavior probes only."""

def can_delete_account(user):
    return bool(user)
