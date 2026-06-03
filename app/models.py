"""
app/models.py
pydantic models partilhados pela api metric4 rtls
"""

from pydantic import BaseModel


class MapaCreate(BaseModel):
    nome: str
    limite_x: float
    limite_y: float
    ficheiro_img: str | None = None
    tenant_id: str


class MapaUpdate(BaseModel):
    nome: str
    limite_x: float
    limite_y: float
    ficheiro_img: str | None = None


class TagAliasUpdate(BaseModel):
    tag_id: str
    friendly_name: str


class TagAliasesUpdate(BaseModel):
    tags: list[TagAliasUpdate]


class TenantCreate(BaseModel):
    nome: str
    password: str | None = None


class TenantUpdate(BaseModel):
    nome: str
    password: str | None = None


class UserCreate(BaseModel):
    username: str
    password: str
    tenant_id: str


class UserUpdate(BaseModel):
    new_username: str | None = None
    password: str | None = None


class TagCreate(BaseModel):
    tag_id: str
    nome: str
    tenant_id: str


class TenantProfileUpdate(BaseModel):
    nome: str | None = None
    new_password: str | None = None
    current_password: str


class SelfCredentialsUpdate(BaseModel):
    new_username: str | None = None
    new_password: str | None = None
    current_password: str
