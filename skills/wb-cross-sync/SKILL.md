---
name: wb-cross-sync
description: WorkBuddy 跨设备（Windows/Mac）技能与文档同步。当用户说"同步一下"、"同步技能和文档"、"把改动推到 Mac/Windows"、"手动同步"，或提到 wb_sync / workbuddy-sync 仓库时使用
---

# WorkBuddy 跨端手动同步

远程仓库：`git@github.com:mlq1984/workbuddy-sync.git`（GitHub 私有，Deploy Key 认证）

## 手动同步（用户说"同步一下"时执行）

```bash
C:/Users/king/.workbuddy/binaries/python/versions/3.13.12/python.exe ~/.workbuddy/wb_sync.py git@github.com:mlq1984/workbuddy-sync.git
```

Mac/Linux 上对应：`python3 ~/.workbuddy/wb_sync.py git@github.com:mlq1984/workbuddy-sync.git`

脚本行为：pull 远端 → 增量采集本地 skills/、*.md、脱敏 configs → commit → push → 把远端更新写回 ~/.workbuddy/。

## 机制约定（勿破坏）
- **范围**：`~/.workbuddy/skills/` 全部技能目录、`~/.workbuddy/*.md`（BOOTSTRAP 除外）、4 个配置 JSON（token/secret/password/api_key 字段自动脱敏为占位符）
- **不删除**：脚本永不删除文件；删除与重命名不跨端传播（防误删，v1 有意设计）
- **冲突**：LWW（mtime 新者优先）+ `git pull -X theirs`；历史在 `.sync_repo` 的 git log 中可回滚
- **configs 不回写本地**：避免占位符覆盖本地真实 token
- **定时**：Windows 自动化任务每天 09:00 自动跑（automation id f56e1d27-ef43-4dc4-8d6a-9172f3ad629b？）

## 结果反馈
把脚本输出原样摘要给用户（扫描数/更新文件数/推送成败）。失败常见原因：
- `Permission denied (publickey)` → `~/.ssh/config` 需含 `IdentityFile ~/.ssh/id_ed25519_wb` + `IdentitiesOnly yes`（Windows）；Mac 用 id_ed25519_wb_mac 并加为 Deploy Key
- 首次 commit 慢 → 首次全量约 1 分钟，之后增量秒级

## 排障注意（Windows 托管环境）
- 托管 Python 有 safe-delete shim，**禁止**在同步逻辑里用 shutil.rmtree（会被拦截进回收站且极慢）；只做 copy2 增量覆盖
- subprocess 调 git 必须用列表参数（shell=True 走 cmd.exe 不认单引号，>NN 字符的 commit 信息会失败）

## Mac 端首次接入
详见仓库内 `docs/SYNC_MAC_SETUP.md`（生成于 2026-10-03）。
