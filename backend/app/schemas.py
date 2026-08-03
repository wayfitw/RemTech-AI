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


class TenderSubscriptionReq(BaseModel):
    name: str
    keywords: str
    region: str | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    customer: str | None = None
    recipient_roles: str = "закупки"


class ContentChannelReq(BaseModel):
    """TASK-0905 (#47) — отслеживаемый ТГ-канал для контент-дайджеста."""
    ref: str                       # @username или id канала
    title: str | None = None


class PartQueryReq(BaseModel):
    """TASK-0606 (#46) — запрос мониторинга объявлений о запчастях."""
    query: str                     # ключевые слова или артикул
    source: str | None = None      # avito | drom | all (по умолчанию all)
    region: str | None = None
