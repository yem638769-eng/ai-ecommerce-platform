from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AddressIn(BaseModel):
    receiver: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., pattern=r"^\d{6,20}$")
    province: str = Field(..., max_length=50)
    city: str = Field(..., max_length=50)
    district: str = Field(..., max_length=50)
    detail: str = Field(..., max_length=200)
    is_default: bool = False


class AddressUpdateIn(AddressIn):
    receiver: str = Field(..., min_length=1, max_length=50)


class AddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    receiver: str
    phone: str
    province: str
    city: str
    district: str
    detail: str
    is_default: bool
    created_at: datetime
