"""支付接口（模拟）：创建支付单、模拟支付回调确认。"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.response import ok
from app.models import User
from app.schemas.order import MockConfirmIn, PaymentCreateIn, PaymentOut
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["支付"])


@router.post("")
async def create_payment(
    data: PaymentCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    payment, pay_url = await payment_service.create_payment(db, user, data)
    return ok(
        {"payment": PaymentOut.model_validate(payment), "pay_url": pay_url},
        message="支付单已创建",
    )


@router.post("/mock/confirm")
async def mock_confirm(
    data: MockConfirmIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    payment = await payment_service.mock_confirm(db, user, data.transaction_id)
    return ok(PaymentOut.model_validate(payment), message="支付成功")
