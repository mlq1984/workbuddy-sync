# Mac 端接入 Guide（Mac 上的 WorkBuddy 照着做即可）

远程仓库：`git@github.com:mlq1984/workbuddy-sync.git`（私有）
Windows 端已完成首次推送（150 技能 + 5 文档 + 4 配置结构）。

## 1. SSH 密钥
如果 Mac 上已有能访问 GitHub 的密钥，跳到第 2 步。否则：

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_wb_mac -C "workbuddy-mac" -N ""
cat ~/.ssh/id_ed25519_wb_mac.pub
```

把公钥内容添加到 GitHub 仓库 workbuddy-sync 的
**Settings → Deploy keys → Add deploy key**（勾选 *Allow write access*）。

然后在 `~/.ssh/config` 追加同样的 Host 段（路径换成 Mac 的密钥文件名）：

```
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_wb_mac
  IdentitiesOnly yes
```

验证：`ssh -T git@github.com` 出现 "You've successfully authenticated" 即可。

## 2. 拉取并铺开到 ~/.workbuddy/

```bash
mkdir -p ~/.workbuddy
git clone git@github.com:mlq1984/workbuddy-sync.git ~/.workbuddy/.sync_repo
cd ~/.workbuddy/.sync_repo
cp -R skills/ ~/.workbuddy/skills/
cp docs/*.md ~/.workbuddy/
```

> 注意：configs/ 目录里是脱敏后的结构（token 已剔除），**不要**直接覆盖本地 mcp.json/plugins，
> 需要参考结构自己在 Mac 上重新授权一次连接器。

## 3. 定时同步（可选，和 Windows 端对称）

macOS 上把 wb_sync.py 从 Windows clone 后拷贝到 `~/.workbuddy/wb_sync.py`
（下次 Windows 同步它就自动进仓库了，clone 一下就有）。

添加 crontab（每天 9 点）：

```bash
crontab -e
# 加入这行：
0 9 * * * /usr/bin/python3 $HOME/.workbuddy/wb_sync.py git@github.com:mlq1984/workbuddy-sync.git >> $HOME/.workbuddy/sync.log 2>&1
```

## 日常机制速览
- **范围**：skills/ 全部目录、~/.workbuddy/*.md（跳过 BOOTSTRAP）、4 个配置 JSON（脱敏）
- **触发**：每天 09:00 两端定时器；或对 WorkBuddy 说"同步一下"手动触发
- **冲突**：LWW 最新修改优先（git pull -X theirs + 文件 mtime 比较），git log 可回滚
- **反馈**：每次运行输出摘要（扫描多少个/更新几个/推送成败），日志在 ~/.workbuddy/sync.log
- **限制**：不传播删除与重命名（防误删）；configs 只同步结构不回写本地
