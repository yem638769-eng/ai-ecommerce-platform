from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class RegisterIn(BaseModel):
    username: Optional[str] = Field(None, min_length=2, max_length=50)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, pattern=r"^\d{6,20}$")
    password: str = Field(..., min_length=6, max_length=64)

    @model_validator(mode="after")
    def check_identifier(self):
        if not any([self.username, self.email, self.phone]):
            raise ValueError("用户名/邮箱/手机号至少填写一项")
        return self


class LoginIn(BaseModel):
    account: str = Field(..., description="用户名/邮箱/手机号")
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    role: str
    status: int
    created_at: datetime


class UserUpdateIn(BaseModel):
    avatar: Optional[str] = Field(None, max_length=500)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut
