# 跨设备用户身份设计

> 目标：不同的人在不同的设备登录后，能看到自己的学习记录。
> 开发阶段不要求保密，但需要避免「输入别人的用户名就进到别人的记录」。
>
> 本文是需求问题卡定稿后的设计方案，尚未开始实现。

---

## 0. 需求定稿

| 维度 | 结论 |
| --- | --- |
| 登录方式 | 用户名 + 密码 |
| 用户名 | 即展示昵称；唯一；允许中文；2–20 字符 |
| 密码 | 至少 6 位 |
| 账号模型 | 一人一号，不做家长/多孩子档案 |
| 登录凭证 | `Authorization: Bearer <token>`，长期有效，退出才失效 |
| 匿名使用 | 允许；首次启动可跳过，设置页可随时登录 |
| 登录入口 | 首次启动引导 + 设置页「登录 / 切换账号」 |
| 同步范围 | 词汇量 + 测试记录、阅读进度 + 记录、写作 + 批改、生词本 + 设置 |
| 语言设置 | 不同步，按设备保存 |
| 旧匿名数据 | 只导入到新注册账号；已有账号登录时不导入 |
| 退出登录 | 清空本机账号缓存，回到新的匿名身份 |
| 账号操作 | 注册 / 登录 / 退出 / 修改密码 / 找回密码 / 删除账号 |
| 找回密码 | 管理员在后台重置，生成临时密码 |
| 管理后台 | 用户列表 + 重置密码 |
| 历史页 | 一个「学习记录」页，三个 tab：词汇测试 / 阅读进度 / 生词本 |
| 阅读进度 | 阅读列表显示「继续阅读」 |
| 删除账号 | 硬删除该账号的全部服务端数据 |

---

## 1. 现状

- 前端在 `utils/user.ts` 生成一个匿名设备 UUID，存在 `user_id`，每个请求带
  `X-User-Id`。
- 服务端已有按 `user_id` 隔离的数据：
  - `data/users/users.json`：主题偏好、词汇量；
  - `data/writings/writings.json`：作文与批改；
  - `data/logs/reading_records.jsonl`：阅读记录（含 `user_id`，但目前没有读回接口）。
- 生词本只存在本机 `uni.getStorageSync("notebook")`，没有服务端存储。
- 词汇测试没有按用户保存历史，只有当前 `vocab_size`。
- 没有登录页、账号、密码、token 等概念。

这次改造的核心是：**把匿名 `user_id` 升级为账号 `user_id`，同时保留匿名模式**。

---

## 2. 总体方案

```text
                    ┌─────────────────────────────┐
                    │  H5 / App                   │
                    │  token 存在本地             │
                    │  请求带 Bearer + X-User-Id  │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  FastAPI 身份解析            │
                    │  1. Bearer 有效 → 账号 id   │
                    │  2. 否则 X-User-Id → 匿名 id│
                    │  3. 否则 "anonymous"        │
                    └──────────────┬──────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
  accounts.json              sessions.json              users.json
  用户名/密码哈希              token 哈希 → 账号           档案（现有）
        │
        ├── writings.json（现有）
        ├── reading_records.jsonl（现有）
        ├── notebooks.json（新增）
        └── vocab_tests.json（新增）
```

- **账号 id 直接复用现有 `user_id`**：注册时生成一个 UUID 作为账号的
  `user_id`，所有现有按 `user_id` 存储的数据无需改表结构。
- **匿名模式保留**：没有 token 时继续用 `X-User-Id`。这保证「先随便看看」
  和现有用户不受影响。
- **Bearer 优先**：只要 token 有效，服务端忽略 `X-User-Id`，避免同一浏览器
  登录后仍读到匿名数据。
- **token 长期有效**：不设过期时间；退出登录、修改密码、管理员重置密码、
  删除账号会使 token 失效。

---

## 3. 数据模型

### 3.1 `data/users/accounts.json`（新增）

```json
{
  "<user_id>": {
    "user_id": "8f3c...",
    "username": "小明",
    "username_key": "小明",
    "password_hash": "pbkdf2_sha256$120000$<salt>$<hash>",
    "created_at": 1794448000.0,
    "updated_at": 1794448000.0,
    "last_login_at": 1794448000.0
  }
}
```

- `username_key = username.strip().casefold()`，用于唯一性判断。
- 用户名允许中文；长度按 `len(username)` 计，2–20。
- 密码用 PBKDF2-HMAC-SHA256（120,000 次迭代）+ 16 字节随机盐；
  校验用 `secrets.compare_digest`。
- 不存明文密码，也不存 token 原文。

### 3.2 `data/users/sessions.json`（新增）

```json
{
  "<sha256(token)>": {
    "user_id": "8f3c...",
    "created_at": 1794448000.0,
    "last_used_at": 1794448000.0
  }
}
```

- token 用 `secrets.token_urlsafe(32)` 生成。
- 只存 token 的 SHA-256，服务端不保存原文。
- `last_used_at` 可节流到每 5 分钟更新一次，避免每个请求都写盘。

### 3.3 其他存储

| 文件 | 结构 | 变化 |
| --- | --- | --- |
| `data/users/users.json` | `{user_id: {topic_preferences, vocab_size}}` | 不变，账号 id 直接作为 key |
| `data/writings/writings.json` | `{user_id: {essay_id: essay}}` | 不变 |
| `data/logs/reading_records.jsonl` | 每行含 `user_id` | 新增读回接口 |
| `data/notebooks/notebooks.json` | `{user_id: [{word, gloss, phonetic, reading_id, ts}]}` | 新增 |
| `data/vocab_tests/vocab_tests.json` | `{user_id: [{ts, algo, score, vocab_size, total, correct, wrong, unknown}]}` | 新增 |

生词本和词汇测试历史都用「每个用户一个列表」的结构，方便整体迁移和硬删除。

---

## 4. 认证流程

### 4.1 身份解析

新增 `services/auth.py`：

```python
def resolve_user_id(authorization: str | None, x_user_id: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        session = auth.resolve_session(token)
        if session:
            return session["user_id"]
    return x_user_id or "anonymous"
```

- 所有现有路由把 `X-User-Id` 的读取换成 `resolve_user_id(...)`。
- 建议封装成 FastAPI dependency `current_user_id(authorization, x_user_id)`，
  路由只声明依赖，避免每个接口重复解析。
- 需要登录的接口（改密码、删除账号、`/auth/me`）额外要求 token 有效，
  无效返回 401。

### 4.2 注册

```http
POST /auth/register
Content-Type: application/json

{
  "username": "小明",
  "password": "secret1",
  "device_user_id": "<当前匿名设备 id>"
}
```

流程：

1. 校验用户名（2–20 字符、非空、无控制字符）和密码（≥ 6 位）。
2. `username_key` 已存在 → 409。
3. 生成新的 `user_id`（UUID），写入账号与密码哈希。
4. 如果 `device_user_id` 存在且不是 `anonymous`，把该匿名身份的数据迁移到
   新账号（见 §5）。
5. 创建 session，返回 token 和用户信息。

```json
{
  "token": "...",
  "user": {"user_id": "8f3c...", "username": "小明"},
  "imported": {"writings": 2, "reading_records": 5, "notebook": 3, "vocab_tests": 0}
}
```

### 4.3 登录

```http
POST /auth/login
{"username": "小明", "password": "secret1"}
```

- 用户名按 `username_key` 查找；密码错误统一返回 401「用户名或密码错误」，
  不区分「用户不存在」和「密码错误」。
- 登录**不导入**当前设备的匿名数据（已有账号以账号数据为准）。
- 返回新的 token。

### 4.4 退出

```http
POST /auth/logout
Authorization: Bearer <token>
```

- 删除该 token 对应的 session。
- 前端清空 token、账号缓存和本机 `user_id`；下次 `getUserId()` 生成新的匿名 id。
- 服务端账号数据不受影响。
- 「切换账号」= 退出当前账号 → 登录另一个账号；退出即清空本机缓存，避免
  下一个人看到上一个人的数据。

### 4.5 修改密码

```http
PUT /auth/password
Authorization: Bearer <token>

{"old_password": "secret1", "new_password": "secret2"}
```

- 校验旧密码；新密码 ≥ 6 位且不能与旧密码相同。
- 更新哈希；**删除该账号除当前 token 外的所有 session**，其它设备需重新登录。
- 返回 `{"ok": true}`。

### 4.6 管理员重置密码

```http
POST /api/users/{user_id}/reset-password
```

- 仅 admin app（8001，HTTP Basic）可调用。
- 生成 10 位临时密码（大小写字母 + 数字），更新哈希，删除该账号全部 session。
- 返回 `{"username": "小明", "temp_password": "Ab3xK9pQ2z"}`。
- 后台界面把临时密码展示一次，由管理员转告用户。
- 不做「首次登录强制改密」（开发阶段从简，后续可加 `must_change_password`）。

### 4.7 删除账号

```http
DELETE /auth/account
Authorization: Bearer <token>

{"password": "secret1"}
```

- 校验密码。
- 硬删除：账号、全部 session、档案、作文、阅读记录、生词本、词汇测试历史。
- 阅读记录是 JSONL：读入后过滤掉该 `user_id` 的行，再原子写回。
- 全局答题日志 `vocab_sessions.jsonl` 不含 `user_id`，无法按账号删除；
  其中也不含用户名/密码，保留作为匿名运行日志。
- 用户名释放，可被重新注册。

---

## 5. 匿名数据迁移

只在**注册新账号**时执行；已有账号登录不执行。

```python
def migrate_user_data(src: str, dst: str) -> dict:
    """把 src 的匿名学习数据整体搬到 dst。src 的数据搬完后删除。"""
```

| 数据 | 迁移方式 |
| --- | --- |
| `users.json` 档案 | `users[dst] = users.pop(src)` |
| `writings.json` | `writings[dst] = writings.pop(src)` |
| `notebooks.json` | `notebooks[dst] = notebooks.pop(src)` |
| `vocab_tests.json` | `vocab_tests[dst] = vocab_tests.pop(src)` |
| `reading_records.jsonl` | 逐行改 `user_id`：`src` → `dst`，原子写回 |
| 本机生词本 | 阅读器始终调 `POST /notebook`；请求失败时才写本地 `notebook` 兜底。注册成功后再把本地兜底数据推到服务端并清空 |
| 语言设置 | **不迁移**（按设备保存） |
| 词汇测试历史 | 本次改造之前的历史没有 `user_id`，无法归属；历史从改造后开始记录 |

注册响应里的 `imported` 字段返回各类记录数量，前端可提示「已导入 N 条记录」。

---

## 6. API 设计

### 6.1 新增认证接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/register` | 注册并登录 |
| POST | `/auth/login` | 登录 |
| POST | `/auth/logout` | 退出当前 token |
| GET | `/auth/me` | 当前账号信息 |
| PUT | `/auth/password` | 修改密码 |
| DELETE | `/auth/account` | 删除账号 |

### 6.2 学习记录接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/vocab/tests` | 当前用户的词汇测试历史 |
| GET | `/readings/progress` | 当前用户的阅读进度（按 reading_id 取最新一条） |
| GET | `/notebook` | 生词本列表 |
| POST | `/notebook` | 加入生词本 |
| DELETE | `/notebook/{word}` | 移出生词本 |

`/vocab/tests` 响应示例：

```json
{
  "items": [
    {"ts": 1794448000.0, "algo": "eudic", "score": 8066, "vocab_size": 8070,
     "total": 50, "correct": 30, "wrong": 15, "unknown": 5}
  ]
}
```

`/readings/progress` 响应示例：

```json
{
  "items": [
    {"reading_id": "r007", "collection_id": "c001", "completed_ratio": 1.0,
     "last_ts": 1794448000.0, "seconds": 420}
  ]
}
```

### 6.3 现有接口改造

- 所有路由的 `X-User-Id` 读取改为 `resolve_user_id(authorization, x_user_id)`。
- `POST /vocab/test/start` 把解析出的 `user_id` 传给两套算法，测试结束时写入
  `vocab_tests.json`。
- `finish_test` 可能被重复调用（用户点结束 + 自动结束），写入历史要幂等：
  在 session 上记一个 `recorded` 标志，只写一次。
- 阅读记录接口继续写 JSONL，新增读回聚合。
- 写作、档案接口不变，只是身份来源多了一个 Bearer。

### 6.4 管理后台接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/users` | 用户列表（账号、注册时间、最后登录、词汇量、作文数、阅读记录数） |
| POST | `/api/users/{user_id}/reset-password` | 重置密码，返回临时密码 |

---

## 7. 前端改造

### 7.1 请求封装

`api/request.ts`：

- 有 token 时加 `Authorization: Bearer <token>`。
- 继续带 `X-User-Id`（匿名回退 / 注册时迁移用）。
- 收到 401 时清除本地 token，跳转登录页（登录接口本身的 401 除外）。

### 7.2 身份工具

`utils/user.ts` 新增：

```ts
const TOKEN_KEY = "auth_token";
const ONBOARDED_KEY = "onboarded";

export function getToken(): string | null;
export function setToken(token: string): void;
export function clearAuth(): void; // 清 token + user_id，下次生成新匿名 id
export function isLoggedIn(): boolean;
```

### 7.3 页面

| 页面 | 内容 |
| --- | --- |
| `pages/auth/login.vue` | 用户名/密码登录；去注册；「先匿名使用」 |
| `pages/auth/register.vue` | 用户名/密码/确认密码；注册成功后导入本机匿名数据 |
| `pages/history/history.vue` | 三个 tab：词汇测试历史 / 阅读进度 / 生词本 |
| `pages/settings/settings.vue` | 顶部账号卡：已登录显示用户名、学习记录、修改密码、退出、删除账号；未登录显示登录/注册 |
| `pages/reading/list.vue` | 有进度时显示进度条和「继续阅读」 |
| `pages/reading/reader.vue` | 「加入生词本」改调 `/notebook`，失败时回退本地 |

### 7.4 首次启动

`App.vue` 的 `onLaunch`：

```text
if 没有 token 且没有 onboarded:
    跳转 pages/auth/login?first=1
else:
    正常进入首页
```

- 登录页的「先匿名使用」设置 `onboarded = 1`，之后不再拦截。
- 设置页始终可以进入登录/注册。

### 7.5 阅读列表「继续阅读」

- 进入列表时并行请求 `listReadings` 和 `/readings/progress`。
- 单篇文章：显示进度条；有进度时卡片上显示「继续阅读」。
- 作品集：按章节 `reading_id` 聚合出最后读到的章节，显示「上次读到第 N 章」，
  点击直接进入该章。

---

## 8. 后台管理

在 `app/static/admin/index.html` 增加「用户」tab：

- 表格列：用户名、注册时间、最后登录、词汇量、作文数、阅读记录数。
- 每行「重置密码」按钮，调用 `POST /api/users/{user_id}/reset-password`。
- 重置成功后弹窗展示临时密码，并提供复制按钮。
- 不做删除/禁用（本期需求只要求列表 + 重置密码）。

---

## 9. 实施顺序

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| 1 | `services/auth.py`：密码哈希、token、accounts/sessions 存储 | 单元测试 |
| 2 | 身份解析接入所有路由；`/auth/*` 接口 | 注册/登录/退出/改密/删号测试 |
| 3 | 数据迁移 `migrate_user_data` | 新账号导入匿名数据测试 |
| 4 | 生词本、词汇测试历史、阅读进度接口 | 接口测试 |
| 5 | 前端 token/请求封装、登录/注册/引导页、设置账号卡 | 类型检查 + 手动流程 |
| 6 | 学习记录页、阅读列表继续阅读、生词本同步 | 手动流程 |
| 7 | Admin 用户列表 + 重置密码 | 后台手动测试 |
| 8 | 跨设备端到端验证 | 两个浏览器/无痕窗口 |

---

## 10. 边界与取舍

- **开发阶段不做限流/验证码**：登录接口可被暴力尝试；正式上线前需要加。
- **没有邮箱/手机号**：找回密码只能靠管理员重置；这是本次需求明确选择。
- **token 长期有效**：方便跨设备；泄露后只能通过退出/改密/管理员重置失效。
- **语言不同步**：语言属于设备偏好，账号只同步学习数据。
- **旧测试历史无法归属**：改造前的答题日志没有 `user_id`，历史从改造后开始。
- **已有账号登录不导入本机匿名数据**：避免把共用设备上别人的数据混进账号；
  这些匿名数据会留在服务端，暂不清理。
- **JSON 文件存储**：沿用现有 `atomic_write_json` + 线程锁；家庭/小规模够用，
  并发再高应换 SQLite/PostgreSQL。
- **删除账号是硬删除**：不可恢复；前端需要二次确认并校验密码。

---

## 11. 测试计划

### 后端

- 密码哈希/校验、错误密码、用户名重复、用户名大小写/中文。
- 注册：新账号 + 匿名数据迁移；已有账号登录不迁移。
- token：有效/无效/退出后失效/改密后其它 session 失效/管理员重置后全部失效。
- 删除账号：各存储中的该用户数据全部消失，用户名可重新注册。
- 身份解析：Bearer 优先于 `X-User-Id`；无 token 时匿名回退。
- 历史接口：只返回当前用户的数据。

### 前端

- `vue-tsc --noEmit`。
- 手动流程：
  1. 匿名做一次词汇测试、加几个生词、读一篇文章；
  2. 注册新账号 → 提示导入数量 → 数据仍在；
  3. 无痕窗口登录同一账号 → 看到同样的词汇量/历史/生词本；
  4. 退出 → 回到匿名身份，看不到账号数据；
  5. 修改密码 → 另一台设备被踢下线；
  6. 管理员重置密码 → 用临时密码登录；
  7. 删除账号 → 再登录失败，用户名可重新注册。

---

## 12. 一句话总结

**在现有匿名 `user_id` 之上加一层「账号 + Bearer token」：注册时把设备匿名数据
迁到新账号，登录时以账号数据为准；所有现有按 `user_id` 存储的数据结构不变，
只是身份来源从「设备 UUID」升级为「账号 UUID 或设备 UUID」。**
