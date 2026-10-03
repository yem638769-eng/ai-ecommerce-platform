"""商品 / 分类 / SKU / 评价 / 收藏 / 搜索相关的出入参模型。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ===== 分类 =====


class CategoryOut(BaseModel):
    """分类树节点（children 递归）。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: Optional[int] = None
    name: str
    level: int
    sort: int
    icon: Optional[str] = None
    children: list["CategoryOut"] = []


# ===== SKU 与图集 =====


class SKUIn(BaseModel):
    """商家端 SKU 入参；sku_code 未传则自动生成。"""
    sku_code: Optional[str] = Field(None, max_length=64)
    specs: dict
    price: float = Field(..., gt=0, le=99999999)
    stock: int = Field(0, ge=0)
    image: Optional[str] = Field(None, max_length=500)
    status: int = 1


class SKUOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_code: str
    specs: dict
    price: float
    stock: int
    image: Optional[str] = None
    status: int


class ProductImageIn(BaseModel):
    url: str = Field(..., max_length=500)
    sort: int = 0


class ProductImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    sort: int


# ===== 商品创建 / 编辑（商家端 §5.7 复用）=====


class ProductCreateIn(BaseModel):
    """创建商品：SPU + SKU 列表 + 图集。"""
    name: str = Field(..., min_length=1, max_length=200)
    subtitle: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = None
    main_image: str = Field(..., max_length=500)
    category_id: int
    skus: list[SKUIn] = Field(..., min_length=1)
    images: list[ProductImageIn] = []


class ProductUpdateIn(BaseModel):
    """编辑商品：未设置的字段不更新；skus / images 传入则整体替换。"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    subtitle: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = None
    main_image: Optional[str] = Field(None, max_length=500)
    category_id: Optional[int] = None
    skus: Optional[list[SKUIn]] = Field(None, min_length=1)
    images: Optional[list[ProductImageIn]] = None


# ===== 商品输出 =====


class MerchantBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_name: str
    logo: Optional[str] = None
    rating: float


class CategoryBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    level: int


class ProductOut(BaseModel):
    """商品列表 / 详情通用输出（含 SKU 列表与图片列表）。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subtitle: Optional[str] = None
    description: Optional[str] = None
    main_image: str
    price_min: float
    price_max: float
    sales_count: int
    rating_avg: float
    status: int
    category_id: int
    merchant_id: int
    created_at: datetime
    skus: list[SKUOut] = []
    images: list[ProductImageOut] = []


class ProductDetailOut(ProductOut):
    """商品详情：附商家与分类信息。"""
    merchant: Optional[MerchantBriefOut] = None
    category: Optional[CategoryBriefOut] = None


# ===== 评价 =====


class ReviewIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    content: Optional[str] = Field(None, max_length=2000)
    images: Optional[list[str]] = None


class ReviewUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    avatar: Optional[str] = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    product_id: int
    order_id: Optional[int] = None
    rating: int
    content: Optional[str] = None
    images: Optional[list] = None
    created_at: datetime
    user: Optional[ReviewUserOut] = None


# ===== 收藏 =====


class FavoriteIn(BaseModel):
    product_id: int


class FavoriteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    created_at: datetime
    product: Optional[ProductOut] = None


# ===== 搜索 =====


class SearchItemOut(BaseModel):
    """语义搜索结果项。"""
    id: int
    name: str
    subtitle: Optional[str] = None
    price_min: float
    main_image: str
    sales_count: int
    similarity: Optional[float] = None
    highlight: Optional[str] = None
