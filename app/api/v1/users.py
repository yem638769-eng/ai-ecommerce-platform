"""用户资料与收货地址接口。"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.crud import user as crud_user
from app.models import User
from app.schemas.auth import UserOut, UserUpdateIn
from app.schemas.user import AddressIn, AddressOut

router = APIRouter(prefix="/users", tags=["用户"])


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return ok(UserOut.model_validate(user))


@router.put("/me")
async def update_me(
    data: UserUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await crud_user.update_user(db, user, data.model_dump())
    return ok(UserOut.model_validate(user))


# ===== 收货地址 =====


@router.get("/me/addresses")
async def list_my_addresses(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    addresses = await crud_user.list_addresses(db, user.id)
    return ok([AddressOut.model_validate(a) for a in addresses])


@router.post("/me/addresses")
async def create_address(
    data: AddressIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    address = await crud_user.create_address(db, user.id, data)
    return ok(AddressOut.model_validate(address))


@router.put("/me/addresses/{address_id}")
async def update_address(
    address_id: int,
    data: AddressIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    address = await crud_user.get_address(db, user.id, address_id)
    if address is None:
        raise BizError(1005, "地址不存在", 404)
    address = await crud_user.update_address(db, address, data)
    return ok(AddressOut.model_validate(address))


@router.delete("/me/addresses/{address_id}")
async def delete_address(
    address_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    address = await crud_user.get_address(db, user.id, address_id)
    if address is None:
        raise BizError(1005, "地址不存在", 404)
    await crud_user.delete_address(db, address)
    return ok(message="已删除")
