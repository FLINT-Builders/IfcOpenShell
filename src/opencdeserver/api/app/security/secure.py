from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from database.neo4j import db
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import OAuth2AuthorizationCodeBearer, SecurityScopes
from jose import JWTError, jwt
from models.other import TokenData
from models.request import User
from passlib.context import CryptContext
from security.secrets import get_secrets

secrets = get_secrets()

# password context
crypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="foundation/oauth2/auth",
    tokenUrl="foundation/oauth2/token",
    scopes={"test": "Full access, but only test data.", "user": "Normal user access.", "admin": "Full access to all."},
)


credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def create_access_token(data: dict, expires_delta: timedelta | None = None, token_type: str = ACCESS_TOKEN_TYPE):
    payload = data.copy()
    payload.pop("expires", None)
    expires_delta = expires_delta or timedelta(minutes=15)
    expire = datetime.now(timezone.utc) + expires_delta
    payload.update({"exp": int(expire.timestamp()), "type": token_type, "jti": str(uuid4())})
    encoded_jwt = jwt.encode(payload, secrets["security_secret_key"], algorithm=os.environ["SECURITY_ALGORITHM"])
    return encoded_jwt


def decode_token(token: str, token_type: str) -> dict:
    payload = jwt.decode(
        token,
        secrets["security_secret_key"],
        algorithms=[os.environ["SECURITY_ALGORITHM"]],
        options={"require_exp": True},
    )
    if payload.get("type") != token_type:
        raise JWTError("Unexpected token type.")
    return payload


def verify_password(plain_password, hashed_password):
    return crypt_context.verify(plain_password, hashed_password)


# see if given password matches password of username
def authenticate_user(username_to_authenticate: str, plain_password: str) -> dict or False:
    # maybe put an exception around this code below
    user = db.get_user(username_to_authenticate)
    if not user:
        return False
    if verify_password(plain_password, user.hashed_password):
        return user
    return False


def get_password_hash(plain_password):
    return crypt_context.hash(plain_password)


# get current user from token
async def get_current_user(security_scopes: SecurityScopes, token: str = Depends(oauth2_scheme)):

    print("\n\n\nGets current user.")

    if security_scopes.scopes:
        authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
    else:
        authenticate_value = f"Bearer"
    print(authenticate_value)

    try:
        print("Token: ", token)
        payload = decode_token(token, ACCESS_TOKEN_TYPE)
        username_from_token: str = payload.get("username")
        print("Token username: ", username_from_token)
        if username_from_token is None:
            raise credentials_exception
        token_scopes = payload.get("scopes", [])
        print("Token scopes: ", token_scopes)
        token_data = TokenData(scopes=token_scopes, username=username_from_token)

    except JWTError:
        print("JWTError")
        raise credentials_exception

    user = db.get_user(username=token_data.username)

    if user is None:
        raise credentials_exception

    # Tokens replaced by a later login or refresh must stop working before their expiry.
    if not db.is_current_access_token(token_data.username, token):
        raise credentials_exception

    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not enough permissions",
                headers={"WWW-Authenticate": authenticate_value},
            )

    return user


async def get_current_active_user(current_user: User = Security(get_current_user, scopes=["test"])):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
