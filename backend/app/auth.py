import os
from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from .db import session
from .models import User

passwords = PasswordHash.recommended()
SECRET = os.getenv("JWT_SECRET", "local-demo-only-replace-before-deployment-32chars")
oauth = OAuth2PasswordBearer(tokenUrl="/auth/token")


def token(user):
    return jwt.encode(
        {
            "sub": user.id,
            "exp": datetime.now(timezone.utc) + timedelta(hours=8),
            "iss": "dataguard",
            "aud": "dataguard-ui",
        },
        SECRET,
        algorithm="HS256",
    )


def current_user(value=Depends(oauth), db=Depends(session)):
    try:
        data = jwt.decode(
            value,
            SECRET,
            algorithms=["HS256"],
            issuer="dataguard",
            audience="dataguard-ui",
        )
        user = db.get(User, data["sub"])
        if not user:
            raise ValueError()
        return user
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            401, "Sign in again", headers={"WWW-Authenticate": "Bearer"}
        )
