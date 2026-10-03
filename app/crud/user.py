from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserAddress
from app.schemas.auth import RegisterIn
from app.schemas.user import AddressIn
from app.core.security import hash_password


async def get_by_id(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def get_by_account(db: AsyncSession, account: str) -> User | None:
    stmt = select(User).where(
        or_(User.username == account, User.email == account, User.phone == account)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_by_username(db: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_by_phone(db: AsyncSession, phone: str) -> User | None:
    stmt = select(User).where(User.phone == phone)
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_user(db: AsyncSession, data: RegisterIn) -> User:
    user = User(
        username=data.username,
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user: User, data: dict) -> User:
    for key, value in data.items():
        if value is not None:
            setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


# ===== 收货地址 =====


async def list_addresses(db: AsyncSession, user_id: int) -> list[UserAddress]:
    stmt = (
        select(UserAddress)
        .where(UserAddress.user_id == user_id)
        .order_by(UserAddress.is_default.desc(), UserAddress.id.desc())
    )
    return list((await db.execute(stmt)).scalars())


async def get_address(db: AsyncSession, user_id: int, address_id: int) -> UserAddress | None:
    stmt = select(UserAddress).where(
        UserAddress.id == address_id, UserAddress.user_id == user_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _unset_default(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(UserAddress).where(UserAddress.user_id == user_id).values(is_default=False)
    )


async def create_address(db: AsyncSession, user_id: int, data: AddressIn) -> UserAddress:
    if data.is_default:
        await _unset_default(db, user_id)
    address = UserAddress(user_id=user_id, **data.model_dump())
    db.add(address)
    await db.commit()
    await db.refresh(address)
    return address


async def update_address(
    db: AsyncSession, address: UserAddress, data: AddressIn
) -> UserAddress:
    if data.is_default and not address.is_default:
        await _unset_default(db, address.user_id)
    for key, value in data.model_dump().items():
        setattr(address, key, value)
    await db.commit()
    await db.refresh(address)
    return address


async def delete_address(db: AsyncSession, address: UserAddress) -> None:
    await db.delete(address)
    await db.commit()
