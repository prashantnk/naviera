from app.core.config import settings
from fastapi import HTTPException, status
from jose import JWTError, jwt
from pydantic import ValidationError
from sqlmodel import SQLModel


class TokenPayload(SQLModel):
    """
    Pydantic model for the expected payload within the JWT.
    'sub' is the standard claim for the subject (user ID).
    """

    sub: str
    email: str
    aud: str


def decode_access_token(token: str) -> TokenPayload:
    """
    Decodes a JWT access token and validates its payload.
    """
    try:
        # Decode the JWT using the secret key and algorithm from settings
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience="authenticated",
            issuer=settings.JWT_ISSUER,
        )
        # Validate the payload against our TokenPayload schema
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError) as e:
        # If decoding or validation fails, raise an unauthorized exception
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token_data
