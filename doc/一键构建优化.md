# 一键构建优化

目标：在当前 Docker Desktop 网络环境下，首次构建尽量稳定地控制在 30 分钟内，并避免把时间浪费在运行到一半才发现的镜像源、PyPI、npm、Playwright 下载问题上。

## 推荐入口

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python build_once.py
```

强清理验证：

```powershell
python build_once.py --clean --clean-volumes
```

只验证预拉镜像和服务健康：

```powershell
python build_once.py --skip-build
```

## 脚本做了什么

1. 检查 Docker daemon。
2. 预拉外部基础镜像，并在 Docker Hub 网络不稳定时通过镜像源拉取后 tag 回标准镜像名。
3. 按依赖顺序构建：
   - `hermes-base:latest`
   - `nanobot-hermes-agent:latest`
   - compose 服务镜像
4. 启动 `docker-compose.yml`。
5. 验证 gateway `/api/ping` 和前端端口。

## 已固化的构建修复

- `postgres:16-alpine` 等 Docker Hub 镜像先预拉，避免 `docker compose up` 末尾卡住。
- 构建路径不再依赖 `ghcr.io/astral-sh/uv` 基础镜像；改为基于可镜像的 Debian/Python 镜像并从 PyPI 安装 `uv`，避免 GHCR 拉取超时。
- Hermes 基础镜像不再为 `gosu` 单独拉取 `tianon/gosu` 镜像；改为通过 Debian apt 安装 `gosu`。
- npm 安装统一使用 `registry.npmmirror.com`、重试参数和 BuildKit cache。
- PyPI 安装使用官方源，避开当前环境下清华 PyPI wheel 403。
- Hermes 基础镜像安装系统 `chromium`，并设置 `AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium`，避免 Playwright 镜像源 404，同时保留浏览器能力。
- Hermes bridge 不再重复 apt 安装基础镜像已经包含的浏览器/系统依赖。

## 强验证记录

2026-05-25 强清理验证：

- 清理范围：项目容器、项目卷、项目镜像、已用基础镜像、未使用网络、BuildKit 构建缓存。
- 命令：`python build_once.py --clean --clean-volumes`
- 结果：成功。
- 总耗时：`1031s`，约 `17 分 11 秒`。
- 启动验证：
  - `http://localhost:8080/api/ping`
  - `http://localhost:3080`
  - `http://localhost:3081/login`
  - `http://localhost:3082`
  - `http://localhost:3083`

## 仍需配置

服务可启动不代表模型可调用。首次真实使用前需要创建 `.env` 并配置至少一个 LLM API Key，例如：

```env
DASHSCOPE_API_KEY=...
DEFAULT_MODEL=dashscope/qwen3-coder-plus
JWT_SECRET=change-this-in-real-deployments
```
