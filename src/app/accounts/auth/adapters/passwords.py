import bcrypt


class BcryptPasswordVerifier:
    def __init__(self, *, rounds: int = 12) -> None:
        self._rounds = rounds

    def verify(self, password: str, password_hash: str) -> bool:
        return bool(
            bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        )

    def hash(self, password: str) -> str:
        hashed = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt(rounds=self._rounds)
        )
        return bytes(hashed).decode("utf-8")
