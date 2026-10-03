"""商家端 - 店铺接口：开店申请、店铺信息。"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_merchant, get_current_user, get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.crud import merchant as crud_merchant
from app.models import Merchant, User
from app.schemas.merchant import MerchantOut, ShopRegisterIn

router = APIRouter(prefix="/merchant", tags=["商家端"])


@router.post("/register")
async def register_shop(
    data: ShopRegisterIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """开店申请：店名唯一；成功后创建店铺并把用户角色升级为 merchant。"""
    if await crud_merchant.get_by_user_id(db, user.id) is not None:
        raise BizError(5002, "您已开通店铺，无需重复申请", 409)
    if await crud_merchant.get_by_shop_name(db, data.shop_name) is not None:
        raise BizError(2001, "店铺名称已存在", 409)

    merchant = await crud_merchant.create_shop(db, user, data)
    return ok(MerchantOut.model_validate(merchant), message="开店成功")


@router.get("/profile")
async def shop_profile(auth: tuple[User, Merchant] = Depends(get_current_merchant)):
    """我的店铺信息。"""
    _, merchant = auth
    return ok(MerchantOut.model_validate(merchant))
