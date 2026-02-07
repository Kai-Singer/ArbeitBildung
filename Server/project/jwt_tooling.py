import time
import jwt

JWT_SECRET = "Kai hat den richtigen Schlüssel"  #identischer Schlüssel
JWT_ALGORITHM = "HS256"
JWT_LIFETIME_SECONDS = 300  # 5 Minuten gültig

def create_jwt(user_id: int) -> str:
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "iat": now,
        "exp": now + JWT_LIFETIME_SECONDS,
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def decode_jwt(token: str) -> dict:
    daten = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    return daten
