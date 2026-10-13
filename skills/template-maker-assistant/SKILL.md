---
name: template-maker-assistant
display_name: 办公模板助手
display_name_en: Office Template Assistant
description: 常用办公文书模板生成工具。用于申请、证明、协议、委托书、请假条等文书的框架生成与要素检查。
description_zh: 常用办公文书模板生成工具。用于申请、证明、协议、委托书、请假条等文书的框架生成与要素检查。
description_en: Office template assistant for applications, certificates, agreements and letters.
version: 1.0.0
author: WorkBuddy Studio
---

# 办公模板助手

## 概述

快速生成日常办公文书框架：申请、证明、协议、委托书、通知、请假条等，附要素检查。

## 使用场景

- 要写申请书/证明/请假条/委托书。
- 简易协议/合同框架。
- 文书要素是否齐全。

## 使用方式

```text
python3 scripts/template-gen.py [类型] [主题]
python3 scripts/template-check.py < 文书
```

## 执行流程

1. **选类型**：运行 `template-gen.py`，生成文书框架。
2. **填内容**：按框架填入真实信息。
3. **查要素**：运行 `template-check.py` 检查。
4. **定稿**：正式场合复核。

## 脚本

| 脚本 | 说明 | 用法 |
|---|---|---|
| `scripts/template-gen.py` | 文书框架生成 | `python3 scripts/template-gen.py [类型] [主题]` |
| `scripts/template-check.py` | 要素检查 | `python3 scripts/template-check.py < 文书` |

## 数据与事实边界

- 内容基于真实信息，不虚构。
- 正式办理以受理机关要求为准。

## 合规与安全

- 合同/协议类模板**不构成法律意见**，重大事项咨询律师。
- 证明/申请类以办理机关要求为准。
- 不代签、不伪造文书。
