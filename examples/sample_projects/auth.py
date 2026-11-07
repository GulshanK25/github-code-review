"""Deliberately vulnerable example for test generation demonstrations."""


def can_delete_account(user):
    """Only users with the admin role should be allowed to delete accounts."""

    return bool(user)  # BUG: non-empty user dictionaries are allowed!