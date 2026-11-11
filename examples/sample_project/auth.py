
"""Example authorization module for AI code review testing."""


def can_delete_account(user):
    """
    Check whether a user is allowed to delete an account.

    Only users with the 'admin' role are authorized.

    Args:
        user (dict): Dictionary containing user information.

    Returns:
        bool: True if the user is an admin, otherwise False.
    """

    return user.get("role") == "admin"
