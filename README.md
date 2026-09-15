# 英语学习软件（English Learning App）

面向中国中小学生的英语学习工具：**词汇量评测 → 分级阅读 → 生词复习**。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | uni-app（Vue 3 + TypeScript），一套代码出 H5 + 微信小程序 |
| 后端 | FastAPI（Python 3.11+，uv 管理） |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存 | Redis |
| 词表 | `data/wordlists/`（ECDICT，MIT） |

## 目录结构

```text
english/
├── apps/
│   ├── app/              # uni-app 前端（Vue3 + TS）
│   │   └── src/pages/    # 页面：评测 / 阅读 / 生词本 / 复习 / 推荐 / 报告
│   └── api/              # FastAPI 后端
│       └── app/          # main.py / config.py / db.py
├── data/wordlists/       # 词表数据（主词表 wordlist.csv + surface_lemma.json）
├── data/readings/        # 分级阅读素材（readings.json）
├── docs/                 # 设计文档 + 实现计划
├── docker-compose.yml    # PostgreSQL(pgvector) + Redis
└── .gitignore
```

## 快速开始

### 1. 启动数据库（PostgreSQL + Redis）

```bash
docker compose up -d
```

### 2. 初始化词表数据（可选，后台需多词识别时）

已提交 `wordlist.csv` + `surface_lemma.json`，评测/分级阅读主流程无需额外操作。
后台「多词表达式/术语识别」运行时依赖 `data/wordlists/raw/stardict.db`（约 811MB，不入库）：

```bash
uv run data/wordlists/download_raw.py
```

重新生成全部词表见 [data/wordlists/README.md](data/wordlists/README.md)。

### 3. 启动后端

```bash
uv sync --directory apps/api
uv run --directory apps/api uvicorn app.main:app --reload
```

验证：打开 http://127.0.0.1:8000/health （返回 `{"status":"ok",...}`）

### 4. 启动前端（H5）

```bash
npm install --prefix apps/app
npm --prefix apps/app run dev:h5
```

微信小程序：`npm --prefix apps/app run dev:mp-weixin`

## 测试

```bash
uv run --directory apps/api pytest -q
```

## 文档

- 设计文档：[design-doc.md](design-doc.md)
- 实现计划：[implementation-plan.md](implementation-plan.md)
- 词汇量评测算法：[docs/vocab-assessment.md](docs/vocab-assessment.md)
- 分级阅读算法：[docs/graded-reading.md](docs/graded-reading.md)
- 词表说明：[data/wordlists/README.md](data/wordlists/README.md)
