import bcrypt


class BcryptPasswordVerifier:
    def __init__(self, *, rounds: int = 12) -> None:
        self._rounds = rounds

    def verify(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    def hash(self, password: str) -> str:
        return bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=self._rounds),
        ).decode("utf-8")
