# 实现计划（Implementation Plan）

> 配套 [design-doc.md](design-doc.md)。本文件面向「云部署 Web 应用、家庭自用、首发一位初一男生（词汇量 ~3600）」这一已确认形态，把技术栈收敛为可执行的工程计划。

| 项 | 结论 |
| --- | --- |
| 形态 | 单台国内云服务器跑 Web 应用（PWA），孩子用手机/平板/电脑浏览器访问 |
| 用户 | 家长 1 人（管理员/查看报告）+ 孩子 1 人（主用户），先不做多租户 |
| 后端 | FastAPI（Python 3.11+） |
| 前端 | uni-app（Vue 3 + TypeScript）一套代码 → H5 + 微信小程序 |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存/队列 | Redis + Celery（含 beat 定时） |
| 对象存储 | 阿里云 OSS（TTS 音频、素材缓存） |
| LLM | 主生成 DeepSeek（备 Qwen）；Embedding bge-m3 |
| TTS | 分阶段：浏览器 TTS 起步 → 讯飞（小程序/逐词高亮时） |
| 内容安全 | 自建敏感词库 + 审核 LLM 提示词（自用起步，云审核 API 可选） |

---

## 1. 仓库结构（monorepo）

```text
english/
├── apps/
│   ├── app/                  # uni-app 前端（Vue 3）
│   │   ├── pages/            # 页面：评测 / 阅读 / 生词本 / 复习 / 推荐 / 报告
│   │   ├── components/       # 阅读器（逐行对照）、卡片、TTS 播放器
│   │   └── static/           # 静态资源
│   └── api/                  # FastAPI 后端
│       ├── app/
│       │   ├── routers/      # auth / vocab / reading / review / recommend / tts
│       │   ├── models/       # SQLAlchemy 模型
│       │   └── services/     # 评测、分级、FSRS、推荐等业务
│       └── alembic/          # 数据库迁移
├── services/
│   └── content/              # 内容管线（Celery worker）
│       ├── crawler/          # 抓取（可选，后置）
│       ├── generator/        # AI 生成分级短文
│       ├── grader/           # 难度分级 + 生词标注
│       └── audit/            # 安全审核
├── packages/
│   └── shared/               # 共享类型与词表工具（Python/TS）
├── data/
│   ├── wordlists/            # 高考3500 / 四级4500 / COCA 频率表
│   └── sensitive-words/      # 敏感词库
├── infra/
│   ├── docker-compose.yml
│   └── deploy/               # nginx、systemd、备份、HTTPS（certbot）
└── docs/                     # design-doc.md / implementation-plan.md
```

**工具链**：pnpm（前端）+ uv（Python 依赖）+ Docker Compose（本地开发与生产同一套）。

> **Web 与小程序同源**：前端用 uni-app（Vue 3）一套代码编译 H5 + 微信小程序；后端 FastAPI 提供无状态 REST API（token 鉴权），双端共用。

---

## 2. 数据库 Schema（核心表）

| 表 | 关键字段 |
| --- | --- |
| `users` | id, role(家长/孩子), 昵称 |
| `vocab_tests` | id, user_id, 结果词汇量, 分带正确率(jsonb), created_at |
| `words` | id, lemma, 音标, 词性, 频段, 常用中文释义 |
| `known_words` | user_id, word_id, 已知概率, updated_at（联合主键） |
| `readings` | id, title, body, topic, 难度等级, 生词率, 来源, audit_status |
| `annotations` | id, reading_id, 词/短语, 词形, 中文注释, 起始偏移, 是否生词 |
| `reading_records` | id, user_id, reading_id, 读完率, 用时, 反馈 |
| `vocab_entries` | id, user_id, word_id, 出处例句, 状态(新/学习中/已掌握) |
| `review_cards` | id, user_id, vocab_entry_id, 算法状态(D/S/R jsonb), 下次复习时间 |
| `interests` | user_id, 主题权重(jsonb), updated_at |

> 单用户自用阶段，`known_words` / `vocab_entries` 等均以 `user_id` 区分，但**不加**多租户/组织层，保持简单。

---

## 3. API 设计（REST 端点）

| 模块 | 端点 | 说明 |
| --- | --- | --- |
| 认证 | `POST /auth/login` | 家长/孩子登录，返回 JWT（MVP 可退化为服务端 Basic Auth） |
| 评测 | `POST /vocab/test/start` | 开始自适应评测，返回首题 |
| | `POST /vocab/test/answer` | 提交答案，返回下一题 |
| | `GET /vocab/test/result` | 词汇量 + 分带分布 |
| 阅读 | `GET /readings?level=&topic=` | 阅读列表 |
| | `GET /readings/{id}` | 正文 + 逐行注释 |
| | `POST /readings/{id}/record` | 上报读完率/反馈 |
| TTS | `GET /tts?word=` | 单词发音（音频 URL） |
| | `GET /tts/sentence?text=` | 句级朗读（含时间戳） |
| 生词本 | `GET/POST /vocab` `PATCH/DELETE /vocab/{id}` | 生词本 CRUD |
| 复习 | `GET /review/queue` | 今日复习队列 |
| | `POST /review/{card_id}/grade` | 评分（重来/困难/良好/轻松） |
| 推荐 | `GET /recommendations/feed` | 为你推荐 feed |
| 兴趣 | `GET/PUT /profile/interests` | 兴趣画像 |

---

## 4. 核心算法落地

- **词汇量评测**：词表按频率分带（1k/2k/3k/5k/10k+），阶梯抽样，`词汇量 ≈ Σ(分带正确率 × 带宽)`。以 3600 为先验，结果覆盖更新 `known_words` 概率。
- **已知词概率模型**：`known_words` 存每词概率；阅读「不查注释即理解」→ 升，点击注释/加生词本 → 降，复习通过 → 升。生词率 = `1 − Σ概率/总词数`。
- **分级**：目标生词率 2%–5%；辅以句子长度/词长。
- **FSRS**：用现成库 **`py-fsrs`**（开源、含调度与参数拟合），不自行实现算法。
- **推荐**：`score = α·主题相似度(bge-m3) + β·难度匹配 + γ·新颖度`。
- **TTS 时间戳**：讯飞返回音素/字级时间戳，前端据此做逐词高亮。

---

## 5. 分阶段任务

### P1 — 核心闭环（可先用，4–6 周）

1. **词表准备**：采集/整理 高考 3500、四级 4500 词表 + 音标 + 中文释义；叠加 COCA 频率频段。★ 这是评测与分级的地基。
2. **评测**：先做固定题目版（每频段 N 题）验证估算，再上自适应。
3. **阅读器**：逐行对照渲染（英文一行 + 生词中文注释一行）、生词高亮/点击发音/加生词本。
4. **生词本 + 复习**：`vocab_entries` + `py-fsrs` 队列 + 多题型卡片。
5. **TTS（浏览器起步）**：先用 Web Speech API 做词级 + 句级朗读（零成本）；逐词高亮留到接讯飞后再做。
6. **种子素材**：先用 AI 手动生成 10–20 篇 3800–5000 词难度、四大兴趣主题的分级短文，人工校对后入库。
7. **验收**：能完成「评测 → 读一篇 → 点生词 → 加生词本 → 次日复习」全流程。

### P2 — 内容管线自动化（4–6 周）

1. **AI 生成 worker**（Celery）：按「主题 + 目标生词率 + 词汇频段」批量生成。
2. **分级 + 标注 worker**：spaCy 分词/词形还原 → 短语识别 → 生词判定 → 语境化中文释义 → 逐行注释。
3. **安全审核**：敏感词库 + 审核 LLM 全文分类，命中拦截，留痕。
4. **抓取（可选后置）**：Simple English Wikipedia / Project Gutenberg，清洗 + 改写降难。
5. **验收**：一键生成「给定主题/难度」的合规分级短文并入库。

### P3 — 推荐与体验（3–4 周）

1. 兴趣画像 + 推荐 feed（bge-m3 向量检索）。
2. 打卡激励 + 学习报告（家长视图：阅读量、生词、掌握曲线）。
3. **验收**：首页能按兴趣与难度推荐，家长能看到孩子的学习报告。

### P4 — 部署上线（1–2 周）

1. 域名 + **ICP 备案**（国内云必需，提前启动，周期 1–2 周起）。
2. HTTPS（certbot）+ Nginx + Docker Compose + 定时备份。
3. 监控与日志（基础即可）。
4. **验收**：手机/平板/电脑通过域名访问，家庭自用稳定运行。

---

## 6. 关键技术风险与对策

| 风险 | 对策 |
| --- | --- |
| 词表版权/准确性 | 优先用公开可考证词表 + 人工校对高频段；音标用权威词典数据 |
| 评测误差 | 用固定题验证估算，再用真实做题记录回归校准 |
| AI 生成内容不可控 | 生成/审核分离 + 敏感词库 + 人审兜底（自用阶段家长可快速人工抽检） |
| FSRS 冷启动参数不准 | 用 py-fsrs 默认参数起步，积累数据后离线重拟合 |
| TTS/AI 成本 | TTS 音频缓存到 OSS；AI 生成批量离线跑，错峰 |
| 讯飞/DeepSeek 实名与费用 | 提前完成开发者实名认证，评估用量后选计费档 |

---

## 7. 启动前需准备的账号与资源

- [ ] 云服务器（阿里云/腾讯云 ECS，2C4G 起步）
- [ ] 已备案域名（国内云部署硬性要求）
- [ ] DeepSeek 开放平台 API Key（或 Qwen/百炼）
- [ ] 讯飞开放平台账号（TTS）——P1 可先用浏览器 TTS，此项后置到小程序/逐词高亮阶段
- [ ] 阿里云 OSS（音频/素材缓存）

---

## 8. 建议的第一步（本周可做）

1. 初始化 monorepo 骨架 + Docker Compose（web/api/db/redis 跑通）。
2. **优先整理词表**（P1 第 1 条）：这是评测、分级、生词标注三件事共同的地基，且不依赖任何 API，可立即开始。
