# SDK 方法与配置

## 使用入口

| 入口 | 适用场景 |
| --- | --- |
| Python `Sandbox` | 同步创建或连接单个沙箱 |
| Python `AsyncSandbox` | 异步程序，网络方法使用 `await` |
| Python / JS `DevBox` | 复用客户端，查询模板、管理多个沙箱 |
| JS `Sandbox` | 网络方法返回 Promise，使用 `await` |

`DevBox` 负责管理入口，`Sandbox` 代表具体沙箱。关闭 `DevBox` 不会代替关闭已获取的 Sandbox 对象。

## 方法速查

下表列出常用公开方法；Python 使用蛇形命名，JS 使用驼峰命名。

| 对象 | Python | JavaScript / TypeScript |
| --- | --- | --- |
| `client.templates` | `list()` | `list()` |
| `client.sandboxes` | `create()`、`connect()`、`get()`、`list()` | 同名 |
| `Sandbox` | `create()`、`connect()` | 同名静态方法 |
| `sandbox` | `get_info()`、`is_running()` | `getInfo()`、`isRunning()` |
| `sandbox` | `set_timeout()`、`refresh()` | `setTimeout()`、`refresh()` |
| `sandbox` | `pause()`、`resume()`、`kill()`、`close()` | 同名 |
| `sandbox.commands` | `run()`、`connect()`、`list()` | 同名 |
| `sandbox.commands` | `send_stdin()`、`close_stdin()`、`send_signal()` | `sendStdin()`、`closeStdin()`、`sendSignal()` |
| 命令 / PTY 句柄 | `wait()`、`disconnect()`、`send_stdin()`、`close_stdin()`、`send_signal()` | `wait()`、`disconnect()`、`sendStdin()`、`closeStdin()`、`sendSignal()` |
| `sandbox.files` | `read()`、`write()`、`list()`、`stat()`、`move()`、`remove()` | 同名 |
| `sandbox.files` | `make_dir()`、`upload()`、`download()`、`watch()` | `makeDir()`、`upload()`、`download()`、`watch()` |
| `sandbox.pty` | `start()`、`connect()`、`resize()` | 同名 |
| `sandbox.git` | `clone()`、`status()`、`checkout()`、`add()`、`commit()`、`pull()`、`push()`、`set_config()` | 同名，配置方法为 `setConfig()` |

参数类型以已安装 SDK 的类型提示为准。异步 Python 的方法结构与同步接口一致。

## 创建参数

| Python / JS 参数 | 用途 |
| --- | --- |
| `template` | 模板 ID 或别名，默认 `default` |
| `timeout` | 存活时间，默认 300 秒 |
| `build_id` / `buildId` | 固定模板构建版本 |
| `envs` | 沙箱环境变量，字符串键值 |
| `metadata` | 沙箱业务标签，字符串键值 |
| `lifecycle` | 到期销毁或暂停，是否允许自动恢复 |

## 配置

| 环境变量 | 用途 |
| --- | --- |
| `DEVBOX_API_KEY` | API Key，必填 |
| `DEVBOX_API_URL` | 服务地址，默认 `https://devbox.developer.myhuaweicloud.com` |
| `DEVBOX_GATEWAY_URL` | 可选的沙箱访问地址覆盖，通常不需要设置 |

Python 也可用 `api_key`、`api_url` 构造参数；JS 对应 `apiKey`、`apiUrl`。显式参数优先于环境变量。通常只需配置 API Key 与服务地址，沙箱连接凭证由 SDK 管理。

使用 HTTPS 并保留证书校验。不要把 API Key 或沙箱连接凭证写入日志、浏览器地址栏或公开仓库。

## 时间单位

| 配置 | Python | JavaScript / TypeScript |
| --- | --- | --- |
| 沙箱存活时间 | 秒 | 秒 |
| `refresh` 保证的剩余时间 | 秒 | 秒 |
| 命令等待 | `timeout`，秒，默认 60 | `timeoutMs`，毫秒，默认 60000 |
| Git clone / pull / push 等待 | 秒，默认 300 | 毫秒，默认 300000 |
| 网络请求等待 | `request_timeout`，秒 | `requestTimeoutMs`，毫秒 |

默认管理请求等待 150 秒，普通沙箱请求等待 30 秒。PTY 和目录监听允许持续读取，但连接建立仍受网络超时限制。调整请求超时不会延长沙箱存活时间，也不能覆盖服务入口的超时限制。

## 返回与异常

命令返回 stdout、stderr 和退出码；普通文本不由 SDK 自动打印。实时输出使用回调。

异常统一继承 `DevBoxError`，包含错误码、HTTP 状态码、请求 ID 与可读信息：

::: code-group
```python [Python]
from devbox import DevBoxError, Sandbox

try:
    sandbox = Sandbox.connect("<sandbox-id>")
except DevBoxError as error:
    print(error.code, error.status_code, error.request_id, error.message)
else:
    sandbox.close()
```

```js [JavaScript / TypeScript]
import { DevBoxError, Sandbox } from "devbox-js-sdk";

try {
  const sandbox = await Sandbox.connect("<sandbox-id>");
  await sandbox.close();
} catch (error) {
  if (!(error instanceof DevBoxError)) throw error;
  console.log(error.code, error.statusCode, error.requestId, error.message);
}
```
:::
