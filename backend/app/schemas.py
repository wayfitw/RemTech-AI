"""Pydantic-схемы запросов (issue #18 — вынесено из main.py)."""
from pydantic import BaseModel


class LoginReq(BaseModel):
    username: str
    password: str


class RegisterReq(BaseModel):
    username: str
    password: str
    full_name: str | None = ""


class NewConversationReq(BaseModel):
    title: str | None = None


class AdminCreateUserReq(BaseModel):
    username: str
    password: str
    full_name: str | None = ""
    role: str = "user"


class PasswordReq(BaseModel):
    password: str


class ModelConfigReq(BaseModel):
    alias: str
    provider: str
    endpoint: str | None = ""
    fallback_to: str | None = None


class AgentReq(BaseModel):
    name: str
    system_prompt: str | None = ""
    tools: list[str] | None = None
    default_model: int | None = None
    allowed_roles: str | None = ""
