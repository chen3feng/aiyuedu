# 部署（rn3 / aiyuedu.ch3oh.top）

生产环境部署在 `rn3`（Ubuntu 24.04），域名 `aiyuedu.ch3oh.top` 托管在 Cloudflare。
本文记录当前拓扑、配置与更新步骤。

## 拓扑

```text
浏览器
  │ HTTPS（Cloudflare 边缘证书）
  ▼
Cloudflare（proxied）
  │ HTTP :80（Flexible 模式；见下方说明）
  ▼
rn3 nginx :80
  ├── /            → /opt/aiyuedu/web         H5 静态文件（uni-app build:h5）
  └── /api/        → 127.0.0.1:8002           systemd: aiyuedu-api
```

- 服务器上另有 s-ui 占用 `443/8443/2095/2096`，因此 nginx 只监听 `80`；
- Cloudflare SSL/TLS 模式为 **Flexible**：边缘 HTTPS，回源 HTTP；
- 不需要在服务器上申请证书。若改用 Cloudflare Tunnel，可恢复 Full (strict)
  并避免明文回源。

## 目录

| 路径 | 内容 |
| --- | --- |
| `/opt/aiyuedu/apps/api` | 后端代码 + `.env` 工作目录 |
| `/opt/aiyuedu/venv` | 后端 Python 虚拟环境 |
| `/opt/aiyuedu/web` | H5 构建产物 |
| `/opt/aiyuedu/data` | 词表、阅读、合集、用户与日志（生产数据） |
| `/opt/aiyuedu/aiyuedu.env` | `ADMIN_PASSWORD`、`VOCAB_ALGO` 等环境变量 |
| `/etc/systemd/system/aiyuedu-api.service` | 后端服务 |
| `/etc/nginx/sites-available/aiyuedu` | nginx 站点 |

后端 `config.py` 的 `PROJECT_ROOT` 由文件位置推导，`/opt/aiyuedu/apps/api/app/`
上溯三级即 `/opt/aiyuedu`，所以 `data/` 等路径无需额外配置。

## GitHub Flow 与自动部署

分支模型采用 GitHub Flow：

```text
main ──●────────●────────●────────●──→  始终可部署
        \      / \      /
         ●────●   ●────●              短分支 + PR（auto-merge 标签）
```

- `main` 是唯一长期分支，所有改动走短分支 + PR，PR 打 `auto-merge` 标签，
  `backend` / `frontend` 检查通过后由 auto-merge workflow squash 合入；
- 合并到 `main` **只跑 CI，不部署**。正式发布通过 **tag**：

  ```bash
  git checkout main && git pull
  git tag -a v2026.11.19 -m "release 2026-11-19"
  git push origin v2026.11.19
  ```

  推送 `v*` 标签会触发 `Deploy`；部署前会校验该 commit 的
  `backend` / `frontend` 检查确实成功，避免从未通过 CI 的提交发布；
- 需要重发或回滚旧版本时，在 Actions → Deploy → Run workflow 填入已有 tag
  （如 `v2026.11.18`）；不要在 `main` 上直接改完就发；
- `main` 已开启分支保护：必须走 PR、必须通过 `backend` / `frontend` 检查，
  禁止直推、强推和删除（仓库设置只允许 squash merge）；
- `Deploy` 使用 GitHub Environment `production`，部署记录会关联到对应的 tag，
  环境 URL 指向 `https://aiyuedu.ch3oh.top`。

部署所需的仓库 Secrets：

| Secret | 说明 |
| --- | --- |
| `DEPLOY_HOST` | rn3 地址 |
| `DEPLOY_USER` | SSH 用户（root） |
| `DEPLOY_SSH_KEY` | 专用 ed25519 私钥（只授权 rn3） |
| `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan` 得到的 rn3 主机指纹 |

Secrets 未配置时，`Deploy` 的 preflight 会直接跳过，不会产生一次失败部署；
配置好后再合并 / 手动触发即可。

首次配置（仓库管理员）：

```bash
# 1. 生成只用于部署的密钥，公钥追加到 rn3 的 /root/.ssh/authorized_keys
ssh-keygen -t ed25519 -f /tmp/aiyuedu_deploy_key -N '' -C github-actions-deploy
ssh rn3 'cat >> /root/.ssh/authorized_keys' < /tmp/aiyuedu_deploy_key.pub

# 2. 写入仓库 Secrets
gh secret set DEPLOY_SSH_KEY -R chen3feng/aiyuedu < /tmp/aiyuedu_deploy_key
gh secret set DEPLOY_HOST -R chen3feng/aiyuedu --body '23.94.255.173'
gh secret set DEPLOY_USER -R chen3feng/aiyuedu --body 'root'
ssh-keyscan -t ed25519 23.94.255.173 | gh secret set DEPLOY_KNOWN_HOSTS -R chen3feng/aiyuedu
rm -f /tmp/aiyuedu_deploy_key

# 3. main 分支保护：必须 PR + backend/frontend 检查，禁止直推/强推/删除
gh api -X PUT repos/chen3feng/aiyuedu/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": {"strict": false, "contexts": ["backend", "frontend"]},
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

部署流程（`.github/workflows/deploy.yml`）：runner 上构建 H5（`VITE_API_BASE=/api`）
→ 打包代码、静态资源和只读数据 → scp 到 rn3 → 备份当前 `apps/api` 与 `web` →
解包、更新依赖、重启 `aiyuedu-api`、reload nginx → `/api/health` 健康检查。
健康检查失败会自动回滚到本次部署前的代码。

**回滚**：优先在 Actions → Deploy → Run workflow 重新部署上一个正常 tag
（如 `v2026.11.18`），线上立即恢复；同时在 `main` 上 revert 有问题的 PR，
修复后再打新 tag。服务器上的 `/opt/aiyuedu/backups/code-<时间戳>` 保留每次
部署前的代码副本，用于紧急手工回滚。

## 服务管理

```bash
systemctl status aiyuedu-api
systemctl restart aiyuedu-api
journalctl -u aiyuedu-api -f

nginx -t && systemctl reload nginx
```

两个服务均已 `systemctl enable`，开机自启。

## 首次部署 / 更新

在仓库根目录构建前端（**必须带 `VITE_API_BASE=/api`**，否则 H5 会请求
`http://<host>:8000`）：

```bash
npm --prefix apps/app run build:h5
```

打包并上传后端代码、静态资源和只读数据（排除本地 `data/wordlists/raw`
约 1.1GB、本地用户数据与日志）：

```bash
tar -C <staging> -czf - apps data web | ssh rn3 'tar -C /opt/aiyuedu -xzf -'
```

部署目录里需要保留的生产数据目录：

```bash
ssh rn3 'mkdir -p /opt/aiyuedu/data/{logs,users,writings,notebooks,vocab_tests,config}'
```

后端依赖（venv 已存在时只需更新代码后重启）：

```bash
ssh rn3 '/opt/aiyuedu/venv/bin/pip install -q \
  "fastapi>=0.115" "uvicorn[standard]>=0.30" \
  "pydantic-settings>=2.4" "edge-tts>=6.1" "httpx>=0.27"'
ssh rn3 'systemctl restart aiyuedu-api'
```

## nginx

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name aiyuedu.ch3oh.top;

    root /opt/aiyuedu/web;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8002/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        client_max_body_size 20m;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

## 数据与备份

- 生产数据在 `/opt/aiyuedu/data`，本地开发数据**不会**自动同步；
- 备份：

```bash
ssh rn3 'tar -C /opt/aiyuedu -czf - data' > aiyuedu-data-$(date +%F).tgz
```

- `data/config/ai.json`（AI 写作服务的 provider 配置）不在仓库中，需要时手动放到
  服务器，否则依赖它的功能不可用。

## 排查

```bash
curl -s https://aiyuedu.ch3oh.top/api/health
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: aiyuedu.ch3oh.top' http://127.0.0.1/
tail -50 /opt/aiyuedu/data/logs/*.log
```

Cloudflare 侧常见错误：`521` 表示回源端口不可达，`525` 表示 Full 模式下
TLS 握手失败（本机 443 是 s-ui）。Flexible 模式下应看不到 525。
