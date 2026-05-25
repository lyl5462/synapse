# 产品仓库信息查询脚本使用说明

## 概述

本脚本用于调用 SynapseService 的 `get_repo_info` 接口，根据产品名称查询该产品关联的所有代码仓库，并自动从 Git URL 中提取仓库名称。

## 脚本位置

- 调用脚本: `scripts/get_repo_info.py`

## 使用方法

### 基本语法

```bash
py scripts/get_repo_info.py --server-url=XXX --prod=YYY
```

> **Windows 提示**：若 `python` / `python3` 命令不可用，请使用 `py` 启动器。

### 参数说明

| 参数 | 说明 | 是否必填 |
|-----|------|---------|
| `--server-url` | 服务地址 | 是 |
| `--prod` | 产品名称 | 是 |

### 使用示例

```bash
py scripts/get_repo_info.py --server-url=192.168.1.100:8080 --prod=分布式内存数据库
```

```bash
py scripts/get_repo_info.py --server-url=localhost:5000 --prod=XXX营销
```

## 输出说明

成功调用后，脚本会输出该产品下所有仓库名称，格式为：

多个仓库时：
```
产品：XXX营销 一共有2个仓库：仓库A,仓库B
```

单个仓库时：
```
产品：分布式内存数据库 一共有1个仓库：仓库A
```

若未找到仓库信息，输出 `未找到仓库信息`。

## 返回数据格式

接口返回 JSON 格式数据，结构如下：

```json
{
    "code": 0,
    "message": "成功消息",
    "data": [
        {"url": "https://git.example.com/org/仓库A.git", ...},
        {"url": "https://git.example.com/org/仓库B.git", ...}
    ]
}
```

脚本自动从每个 `url` 字段末尾提取仓库名（去掉 `.git` 后缀和路径前缀）。

## 错误码说明

| 错误码 | 说明 |
|-------|------|
| 0 | 成功 |
| -1 | 网络或未知错误 |
| 其他 | 业务错误，请查看 message 字段 |

## 在 Skill 中使用

### Python 调用示例

```python
import subprocess

result = subprocess.run(
    ["py", "scripts/get_repo_info.py",
     "--server-url=192.168.1.100:8080",
     "--prod=分布式内存数据库"],
    capture_output=True, text=True
)
print(result.stdout)
# 输出: 产品：分布式内存数据库 一共有1个仓库：仓库A
```

### 返回结果解析

输出为单行文本，可直接按 `：` 和 `,` 分割提取仓库名列表。
