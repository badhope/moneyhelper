"""认证请求/响应模型（/api/login、/api/register 的入参与令牌响应）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class LoginReq(BaseModel):
    username: str
    password: str


class RegisterReq(BaseModel):
    username: str
    password: str
    display_name: str = ""


class TokenResp(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]
