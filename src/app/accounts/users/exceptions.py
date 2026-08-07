class UserError(Exception):
    """Base error for user management use cases."""


class UserNotFound(UserError):
    pass


class UsernameTaken(UserError):
    pass


class AdminRequired(UserError):
    pass


class OwnAccountRequired(UserError):
    pass


class PrivilegedFieldsRequireAdmin(UserError):
    pass
