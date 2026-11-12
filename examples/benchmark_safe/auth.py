def can_delete_account(user):
    return user.get("role", "") == "admin"
