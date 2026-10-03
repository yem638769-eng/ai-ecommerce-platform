"""种子数据：管理员 / 演示用户与商家 / 分类 / 商品 / 优惠券 / 平台 FAQ 知识库。

用法（docker compose 启动后，容器内执行）：
    docker compose exec api python scripts/seed.py

特性：
- 幂等：已存在的数据（按用户名/店铺名/商品名/券名/文档标题判断）自动跳过，可重复执行；
- Ollama 模型未就绪时向量化自动跳过并提示，模型拉取完成后重跑本脚本即可补齐。
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.crud import product as crud_product  # noqa: E402
from app.db.base import AsyncSessionLocal  # noqa: E402
from app.models import Category, Coupon, KBDocument, Merchant, Product, ProductEmbedding, User, UserAddress  # noqa: E402
from app.schemas.product import ProductCreateIn, ProductImageIn, SKUIn  # noqa: E402
from app.services.ai import indexing  # noqa: E402


def img_url(prompt: str, size: str = "square_hd") -> str:
    """商品演示图（AI 文生图）。"""
    return (
        "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt="
        + quote(prompt)
        + "&image_size="
        + size
    )


# ===== 分类树 =====
CATEGORIES = {
    "手机数码": ["手机通讯", "智能穿戴", "数码配件"],
    "家用电器": ["大家电", "厨房电器"],
    "服饰鞋包": ["运动鞋", "箱包"],
}

# ===== 商品（名称, 副标题, 分类, 描述, 图prompt, SKU列表[(specs, price, stock)]）=====
PRODUCTS = [
    (
        "星辰 Pro Max 旗舰智能手机",
        "2K 曲面屏 · 骁龙旗舰芯片 · 一亿像素",
        "手机通讯",
        "星辰 Pro Max 搭载新一代旗舰处理器，配备 2K 高刷新率曲面屏与一亿像素主摄，"
        "支持 100W 快充与 50W 无线充电，影像与性能俱佳，适合商务与游戏用户。",
        "旗舰智能手机产品图，曲面屏，深色背景，电商风格",
        [
            ({"颜色": "星夜黑", "存储": "256GB"}, 4999.00, 50),
            ({"颜色": "星迹银", "存储": "512GB"}, 5999.00, 30),
        ],
    ),
    (
        "云语 Air 真无线蓝牙耳机",
        "半入耳设计 · 30小时续航 · 蓝牙5.4",
        "数码配件",
        "云语 Air 采用半入耳人体工学设计，单次续航 6 小时，配合充电仓可达 30 小时，"
        "支持蓝牙 5.4 低延迟传输与通话降噪，是通勤与运动的理想伴侣。",
        "白色真无线蓝牙耳机产品图，简洁白色背景，电商风格",
        [({"颜色": "云朵白"}, 399.00, 200)],
    ),
    (
        "静界 H1 主动降噪头戴耳机",
        "旗舰级降噪 · Hi-Res 认证 · 空间音频",
        "数码配件",
        "静界 H1 头戴耳机拥有旗舰级主动降噪，最高降噪深度 45dB，通过 Hi-Res 金标认证，"
        "支持空间音频与多点连接，佩戴舒适，适合差旅与发烧友。",
        "黑色头戴式降噪耳机产品图，工作室灯光，电商风格",
        [({"颜色": "午夜黑"}, 1299.00, 80)],
    ),
    (
        "脉搏 S2 智能运动手表",
        "血氧心率监测 · 100+运动模式 · 14天续航",
        "智能穿戴",
        "脉搏 S2 智能手表支持血氧、心率与睡眠监测，内置 100 余种运动模式，"
        "50 米防水，14 天超长续航，支持蓝牙通话与消息提醒，运动健康好帮手。",
        "黑色智能运动手表产品图，表盘特写，电商风格",
        [
            ({"颜色": "曜石黑", "表带": "氟橡胶"}, 899.00, 120),
            ({"颜色": "玫瑰金", "表带": "真皮"}, 999.00, 60),
        ],
    ),
    (
        "清风变频空调 1.5匹",
        "新一级能效 · 智控温 · 静音眠",
        "大家电",
        "清风变频空调采用全直流变频技术，新一级能效，APF 高达 5.27，"
        "支持 0.5℃ 精准控温与自清洁，运行噪音低至 18 分贝，冷暖两用，适合 15-22㎡ 卧室。",
        "白色壁挂式变频空调产品图，客厅场景，电商风格",
        [({"匹数": "1.5匹", "能效": "新一级"}, 2899.00, 40)],
    ),
    (
        "洁净滚筒洗衣机 10kg",
        "变频电机 · 除菌洗 · 超薄嵌入",
        "大家电",
        "洁净滚筒洗衣机拥有 10 公斤大容量，BLDC 变频电机，支持除菌洗与空气洗，"
        "超薄机身可嵌入式安装，APP 远程操控，洗净比高达 1.08。",
        "银灰色滚筒洗衣机产品图，现代家居场景，电商风格",
        [({"容量": "10kg", "颜色": "银灰"}, 2399.00, 35)],
    ),
    (
        "疾风轻量跑步鞋",
        "回弹中底 · 透气网面 · 205g 轻量",
        "运动鞋",
        "疾风跑步鞋采用高回弹发泡中底与一体织透气网面，单只重量仅约 205 克，"
        "抓地耐磨大底适合路跑与日常训练，是马拉松入门与健身跑者的性价比之选。",
        "灰色轻量跑步鞋产品图，运动场景，电商风格",
        [
            ({"尺码": "42", "颜色": "标准灰"}, 499.00, 150),
            ({"尺码": "43", "颜色": "标准灰"}, 499.00, 150),
        ],
    ),
    (
        "城市通勤双肩包",
        "15.6英寸电脑仓 · 防泼水 · USB充电口",
        "箱包",
        "城市通勤双肩包采用防泼水面料，独立 15.6 英寸电脑仓与多层收纳格，"
        "人体工学背板减压透气，外置 USB 充电口，通勤出差两相宜。",
        "深灰色通勤双肩包产品图，办公场景，电商风格",
        [({"颜色": "深空灰", "容量": "20L"}, 329.00, 300)],
    ),
]

# ===== 平台优惠券（merchant_id=None）=====
COUPONS = [
    ("新人专享满减券", 1, 20.00, 100.00, 1000),
    ("全场九折券", 2, 0.90, 50.00, 500),
]

# ===== 平台 FAQ 知识库 =====
KB_DOCS = [
    (
        "退换货政策",
        "policy",
        "自收到商品之日起 7 天内，如商品未使用且不影响二次销售，可申请无理由退货。"
        "15 天内如商品出现质量问题，可申请换货或维修。"
        "退货运费规则：质量问题由商家承担运费，无理由退货由买家承担寄回运费。"
        "退款将在商家确认收到退货后 1-3 个工作日内原路退回支付账户。"
        "定制类商品、贴身衣物及食品等特殊品类不支持无理由退货，请谨慎下单。",
    ),
    (
        "配送与物流说明",
        "shipping",
        "下单后 48 小时内发货（预售及定制商品除外），发货后可在订单详情页查看物流单号。"
        "默认使用中通、圆通等快递，大件商品使用专业物流配送并送装到家。"
        "普通商品 3-5 天送达，偏远地区可能延长 2-3 天。"
        "单笔订单满 99 元包邮，未满 99 元收取 8 元运费。"
        "如物流信息超过 7 天未更新，请联系在线客服为您核查。",
    ),
    (
        "支付与发票",
        "faq",
        "平台目前支持模拟支付（演示环境）与主流支付方式。"
        "下单后订单将保留 15 分钟，超时未支付将自动取消并释放库存与优惠券。"
        "支付成功后可在订单详情申请开具电子发票，发票将在 24 小时内发送至您的邮箱。"
        "如遇支付失败但款项已扣除，请勿重复支付，系统将在 1 个工作日内自动退款，"
        "也可联系客服人工处理。",
    ),
]


async def get_or_create_user(db, username: str, password: str, role: str = "user") -> User:
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user:
        return user
    user = User(username=username, password_hash=hash_password(password), role=role, status=1)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    print(f"  [用户] {username} / {password}（role={role}）")
    return user


async def main() -> None:
    product_ids: list[int] = []
    embed_failed = 0
    async with AsyncSessionLocal() as db:
        # 1. 账号
        print("== 初始化账号 ==")
        admin = await get_or_create_user(db, "admin", "admin123", role="admin")
        demo = await get_or_create_user(db, "demo", "demo123")
        merchant_user = await get_or_create_user(db, "merchant", "merchant123", role="merchant")

        # 2. 演示收货地址
        if not (await db.execute(select(UserAddress).where(UserAddress.user_id == demo.id))).scalars().first():
            db.add(
                UserAddress(
                    user_id=demo.id, receiver="演示用户", phone="13800000000",
                    province="上海市", city="上海市", district="浦东新区",
                    detail="张江高科技园区博云路 2 号", is_default=True,
                )
            )
            await db.commit()
            print("  [地址] demo 的默认收货地址")

        # 3. 商家
        merchant = (await db.execute(select(Merchant).where(Merchant.user_id == merchant_user.id))).scalar_one_or_none()
        if merchant is None:
            merchant = Merchant(
                user_id=merchant_user.id, shop_name="星辰数码旗舰店",
                description="官方直营，正品保障，极速发货", status=1,
            )
            db.add(merchant)
            await db.commit()
            await db.refresh(merchant)
            print("  [商家] 星辰数码旗舰店")
        else:
            print("  [商家] 已存在，跳过")

        # 4. 分类树
        print("== 初始化分类 ==")
        cat_ids: dict[str, int] = {}
        for parent_name, children in CATEGORIES.items():
            parent = (await db.execute(select(Category).where(Category.name == parent_name, Category.parent_id.is_(None)))).scalar_one_or_none()
            if parent is None:
                parent = Category(name=parent_name, level=1, sort=len(cat_ids))
                db.add(parent)
                await db.commit()
                await db.refresh(parent)
                print(f"  [分类] {parent_name}")
            cat_ids[parent_name] = parent.id
            for i, child_name in enumerate(children):
                child = (await db.execute(select(Category).where(Category.name == child_name, Category.parent_id == parent.id))).scalar_one_or_none()
                if child is None:
                    child = Category(parent_id=parent.id, name=child_name, level=2, sort=i)
                    db.add(child)
                    await db.commit()
                    await db.refresh(child)
                    print(f"  [分类]   └ {child_name}")
                cat_ids[child_name] = child.id

        # 5. 商品 + 上架 + 向量化
        print("== 初始化商品 ==")
        for name, subtitle, cat_name, desc, img_prompt, skus in PRODUCTS:
            found = (await db.execute(select(Product).where(Product.name == name))).scalar_one_or_none()
            if found:
                print(f"  [商品] {name} 已存在，跳过")
                product_ids.append(found.id)
                continue
            data = ProductCreateIn(
                name=name, subtitle=subtitle, description=desc,
                main_image=img_url(img_prompt, "portrait_4_3"),
                category_id=cat_ids[cat_name],
                skus=[SKUIn(specs=s, price=p, stock=st, image=img_url(img_prompt)) for s, p, st in skus],
                images=[ProductImageIn(url=img_url(img_prompt, "landscape_4_3"))],
            )
            product = await crud_product.create_product(db, merchant.id, data)
            product = await crud_product.set_product_status(db, product, 1)
            product_ids.append(product.id)
            print(f"  [商品] {name}（{len(skus)} 个 SKU）")

        # 6. 优惠券
        print("== 初始化优惠券 ==")
        now = datetime.now(timezone.utc)
        for cname, ctype, value, min_amount, total in COUPONS:
            if (await db.execute(select(Coupon).where(Coupon.name == cname))).scalar_one_or_none():
                print(f"  [券] {cname} 已存在，跳过")
                continue
            db.add(
                Coupon(
                    merchant_id=None, name=cname, type=ctype, value=value,
                    min_amount=min_amount, total_count=total,
                    start_time=now - timedelta(days=1), end_time=now + timedelta(days=30),
                    status=1,
                )
            )
            await db.commit()
            print(f"  [券] {cname}")

        # 7. 平台 FAQ 知识库
        print("== 初始化 FAQ 知识库 ==")
        for title, source_type, content in KB_DOCS:
            doc = (await db.execute(select(KBDocument).where(KBDocument.title == title))).scalar_one_or_none()
            if doc:
                if doc.status == 1:
                    print(f"  [FAQ] {title} 已存在且已向量化，跳过")
                else:
                    # 首次向量化失败（status=2）或未处理（status=0）时补齐
                    ok = await indexing.index_kb_document(doc.id)
                    print(f"  [FAQ] {title}（补向量化{'成功' if ok else '失败'}）")
                    if not ok:
                        embed_failed += 1
                continue
            doc = KBDocument(merchant_id=None, title=title, source_type=source_type, content=content, status=0)
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            ok = await indexing.index_kb_document(doc.id)
            print(f"  [FAQ] {title}（向量化{'成功' if ok else '失败'}）")
            if not ok:
                embed_failed += 1

    # 8. 商品向量化（独立会话，幂等：已有向量的跳过，失败可重跑补齐）
    if product_ids:
        print("== 商品向量化 ==")
        async with AsyncSessionLocal() as db:
            done_ids = set(
                (await db.execute(
                    select(ProductEmbedding.product_id).where(ProductEmbedding.product_id.in_(product_ids))
                )).scalars()
            )
        for pid in product_ids:
            if pid in done_ids:
                continue
            ok = await indexing.rebuild_product_embedding(pid)
            print(f"  [向量] product_id={pid} {'成功' if ok else '失败'}")
            if not ok:
                embed_failed += 1
        print(f"  向量化完成（失败 {embed_failed} 项）")

    print("\n种子数据初始化完成。")
    print("  管理员：admin / admin123")
    print("  演示用户：demo / demo123")
    print("  商家账号：merchant / merchant123")
    if embed_failed:
        print("  提示：部分向量化失败（Ollama 模型可能仍在拉取中），稍后重跑本脚本即可补齐。")


if __name__ == "__main__":
    asyncio.run(main())
