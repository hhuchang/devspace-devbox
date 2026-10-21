# 模板 API

请求发送到 `DEVBOX_API_URL`，使用 `X-API-Key`。模板列表用于选择初始软件环境、资源规格与 Build。

## 列出模板 {#list}

`GET /templates`

无请求参数。

```bash
curl --fail-with-body "$DEVBOX_API_URL/templates" \
  -H "X-API-Key: $DEVBOX_API_KEY"
```

成功返回 HTTP 200，JSON 为数组，空列表为 `[]`：

```json
[
  {
    "templateID": "<template-id>",
    "name": "devbox-base",
    "aliases": ["default"],
    "buildID": "<build-id>",
    "cpuCount": 2,
    "memoryMB": 1024,
    "diskSizeMB": 2040
  }
]
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `templateID` | string | 创建时传入的模板 ID |
| `name` | string | 展示名称 |
| `aliases` | string[] | 可用于创建的别名 |
| `buildID` | string | 该模板当前最新可用 Build |
| `cpuCount` | integer | CPU 核数 |
| `memoryMB` | integer | 内存规格，单位 MiB |
| `diskSizeMB` | integer | 磁盘规格，单位 MiB |

列表展示当前可用的公共模板，每个模板包含一个可供创建的 Build。将返回的 `templateID` 或别名传入[创建沙箱](./sandboxes.md#create)；需要固定环境时，同时传入 `buildID`。

鉴权错误返回 401，API Key 的 scope 不是 devbox 时返回 403。公共错误约定见[通用约定](./index.md#errors)。
