# AI 电商平台

基于 FastAPI + PostgreSQL(pgvector) + Redis + Ollama 的全栈异步电商平台，含用户端、商家端与 AI 中台（AI 客服 / AI 导购 / 个性化推荐 / RAG / Agent 工具）。

完整设计见 [docs/AI电商平台设计文档.md](docs/AI电商平台设计文档.md)。

## 架构

```
AI电商平台
     │
     ├─────────────────┼─────────────────┐
     │                 │                 │
  用户端             商家端            AI中台
     │                 │                 │
  商品浏览          商品管理          AI客服(SSE)
  语义搜索          库存管理          AI导购
  购物车            订单管理          AI推荐
  订单/模拟支付     数据统计          RAG知识库
  优惠券            营销              Agent工具
     │                 │                 │
     └─────────────────┼─────────────────┘
                       │
                   FastAPI(全异步)
                       │
            ┌──────────┼──────────┐
            │          │          │
        PostgreSQL   Redis      AI Model
        (pgvector)   (缓存/锁)  Ollama / OpenAI兼容API
            │
         Docker Compose
```

## 快速开始

### 1. 启动

```bash
docker compose up -d --build
```

包含 4 个服务：`api`(8000)、`db`(pgvector:pg16)、`redis`、`ollama`。

> **首次启动提示**：Ollama 容器会在后台拉取 `qwen2.5:7b`（约 4.7GB）与 `nomic-embed-text` 模型，期间 `/health` 中 `llm: false`，AI 功能自动降级（语义搜索回退关键词、AI 客服返回降级话术），不影响其他功能。拉取可能需要较长时间，可用 `docker compose logs -f ollama` 或 `docker compose exec ollama ollama list` 查看进度。

### 2. 健康检查

```bash
curl http://localhost:8000/health
# {"code":0,"data":{"database":true,"redis":true,"llm":false}}
```

### 3. 初始化种子数据

```bash
docker compose exec api python scripts/seed.py
```

幂等可重复执行；Ollama 模型未就绪时商品/FAQ 向量化会跳过，模型拉取完成后重跑即可补齐。

种子账号：

| 角色 | 账号 | 密码 |
|------|------|------|
| 管理员 | admin | admin123 |
| 演示用户（含默认收货地址） | demo | demo123 |
| 商家（星辰数码旗舰店，含 8 个上架商品） | merchant | merchant123 |

交互式文档：http://localhost:8000/docs

## 接口示例

统一响应包裹 `{"code": 0, "message": "ok", "data": ...}`；业务错误返回对应错误码（见设计文档附录 A）。

### 登录与认证

```bash
# 登录（任一演示账号）
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"account":"demo","password":"demo123"}'
# 取 data.access_token，后续请求携带 Authorization: Bearer <token>
```

### 用户端：浏览 / 搜索 / 下单 / 支付

```bash
TOKEN=xxx

# 商品列表（分类/关键词/价格区间/排序/分页）
curl -s "http://localhost:8000/api/v1/products?category_id=4&sort=sales&page=1&page_size=10"

# 语义搜索（AI："适合跑步的轻便装备"）
curl -s "http://localhost:8000/api/v1/search?q=适合跑步的轻便装备"

# 加购（product_id=1 详情里有 sku 列表）
curl -s -X POST http://localhost:8000/api/v1/cart/items \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"sku_id":1,"quantity":2}'

# 下单（Redis 锁 + SQL 条件扣减防超卖；15 分钟未支付自动取消）
curl -s -X POST http://localhost:8000/api/v1/orders \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"address_id":1,"from":"buy_now","sku_items":[{"sku_id":1,"quantity":2}]}'
# 也可 "from":"cart" 直接结算购物车勾选商品

# 模拟支付（两步）：创建支付单 → 用返回的 transaction_id 幂等确认
curl -s -X POST http://localhost:8000/api/v1/payments \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"order_no":"...","pay_method":"mock"}'
curl -s -X POST http://localhost:8000/api/v1/payments/mock/confirm \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"transaction_id":"<上一步 data.payment.transaction_id>"}'

# 领券
curl -s -X POST http://localhost:8000/api/v1/coupons/1/receive -H "Authorization: Bearer $TOKEN"
```

### 商家端

```bash
MTOKEN=xxx  # merchant 登录

# 发货
curl -s -X POST http://localhost:8000/api/v1/merchant/orders/{order_no}/ship \
  -H "Authorization: Bearer $MTOKEN" -H "Content-Type: application/json" \
  -d '{"tracking_no":"SF123456789"}'

# 数据看板 / 销量排行 / 趋势
curl -s http://localhost:8000/api/v1/merchant/stats/dashboard -H "Authorization: Bearer $MTOKEN"
curl -s "http://localhost:8000/api/v1/merchant/stats/trend?days=7" -H "Authorization: Bearer $MTOKEN"

# 知识库（RAG）：上传 FAQ 后自动分块向量化，供 AI 客服检索
curl -s -X POST http://localhost:8000/api/v1/merchant/kb/documents \
  -H "Authorization: Bearer $MTOKEN" -H "Content-Type: application/json" \
  -d '{"title":"尺码说明","source_type":"faq","content":"..."}'
```

### AI 中台

```bash
# AI 客服（SSE 流式，事件：meta / tool / delta / done，15s 心跳）
curl -N -X POST http://localhost:8000/api/v1/ai/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"退货运费谁出？"}'

# AI 导购（LLM 提取需求 + 语义召回 + 推荐话术）
curl -s -X POST http://localhost:8000/api/v1/ai/guide \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"预算1000以内，想买副运动时戴的耳机"}'

# 个性化推荐（行为加权向量召回；未登录返回热销）
curl -s http://localhost:8000/api/v1/ai/recommendations -H "Authorization: Bearer $TOKEN"
```

AI 客服内置 Agent 工具：查订单 / 搜商品 / 查优惠券 / 商品详情（只读），取消订单 / 发起售后（需用户在对话中二次确认后执行）。

## 配置

复制 `.env.example` 为 `.env` 后按需修改（Docker Compose 已内置容器内连接串，无需修改即可启动）：

| 变量 | 说明 | 默认 |
|------|------|------|
| `LLM_PROVIDER` | `ollama` 或 `openai`（OpenAI 兼容端点） | ollama |
| `OLLAMA_CHAT_MODEL` / `OLLAMA_EMBED_MODEL` | 模型名 | qwen2.5:7b / nomic-embed-text |
| `EMBED_DIM` | 向量维度，须与嵌入模型匹配 | 768 |
| `ORDER_TIMEOUT_MINUTES` | 待支付订单超时取消 | 15 |
| `AUTO_CREATE_TABLES` | 启动时自动建表（含 vector 扩展） | true |

## 项目结构

```
app/
├── main.py              # 入口：lifespan 建表 / 定时任务 / 异常处理 / /health
├── core/                # 配置、JWT、统一响应/异常、Redis、依赖注入
├── db/                  # AsyncSessionLocal / Base
├── models/              # 21 张表：用户/商家/商品/购物车/订单/优惠券/行为/AI
├── schemas/             # Pydantic 入参出参
├── crud/                # 数据访问层
├── services/
│   ├── stock_service.py / order_service.py / payment_service.py
│   └── ai/              # llm / embedding / search / indexing / rag / chat / guide / recommend / agent
├── api/v1/              # auth / users / products / search / cart / orders / payments / coupons
│   ├── merchant/        # 商家端：开店 / 商品 / 订单 / 统计 / 营销
│   ├── ai.py / ai_kb.py # AI 接口 / 商家知识库
└── tasks/scheduler.py   # 60s 循环：超时订单取消 / 优惠券过期
scripts/seed.py          # 幂等种子数据
docs/AI电商平台设计文档.md
```

## 实现说明（与设计文档的偏差）

- **数据库迁移**：设计文档 §8.2 规划 Alembic，当前实现采用 `AUTO_CREATE_TABLES`（启动时 `CREATE EXTENSION vector` + `Base.metadata.create_all`），适合开发与演示；生产环境建议关闭并引入 Alembic。
- 个别端点方法（如取消订单/发货/上下架）用 POST 替代文档中的 PUT；商品图片使用演示用生成图 URL。
