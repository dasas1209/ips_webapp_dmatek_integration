"""
app/models.py
pydantic models partilhados pela api metric4 rtls
"""

from typing import List, Optional

from pydantic import BaseModel


class MapaCreate(BaseModel):
    nome: str
    limite_x: float
    limite_y: float
    ficheiro_img: Optional[str] = None
    tenant_id: str


class MapaUpdate(BaseModel):
    nome: str
    limite_x: float
    limite_y: float
    ficheiro_img: Optional[str] = None


class TagAliasUpdate(BaseModel):
    tag_id: str
    friendly_name: str


class TagAliasesUpdate(BaseModel):
    tags: List[TagAliasUpdate]


class TenantCreate(BaseModel):
    nome: str
    password: Optional[str] = None


class TenantUpdate(BaseModel):
    nome: str
    password: Optional[str] = None


class UserCreate(BaseModel):
    username: str
    password: str
    tenant_id: str


class UserUpdate(BaseModel):
    new_username: Optional[str] = None
    password: Optional[str] = None


class TagCreate(BaseModel):
    tag_id: str
    nome: str
    tenant_id: str


class TenantProfileUpdate(BaseModel):
    nome: Optional[str] = None
    new_password: Optional[str] = None
    current_password: str


class SelfCredentialsUpdate(BaseModel):
    new_username: Optional[str] = None
    new_password: Optional[str] = None
    current_password: str
