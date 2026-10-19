# DevBox SDK

[![License](https://img.shields.io/badge/License-Apache-2.0-blue.svg)](LICENSE)

DevBox 为云端隔离沙箱提供 Python 和 JavaScript/TypeScript SDK。两套 SDK 使用一致的对象模型，覆盖沙箱管理、命令与进程、文件系统、PTY 和 Git 操作。

## 项目结构

```text
./
├── python-sdk/   Python SDK
└── js-sdk/       JavaScript / TypeScript SDK
```

每个 SDK 独立维护依赖、测试、构建配置和使用文档：

- [Python SDK](python-sdk/README.md)
- [JavaScript SDK](js-sdk/README.md)

## 用户文档

[快速入门](docs/index.md) · [模板](docs/guide/templates.md) · [命令与进程](docs/guide/commands.md) · [文件](docs/guide/files.md) · [终端与 Git](docs/guide/terminal-and-git.md) · [生命周期](docs/guide/lifecycle.md) · [SDK 参考](docs/reference/sdk.md) · [问题排查](docs/reference/troubleshooting.md)

文档与 SDK 同仓维护，`docs/` 独立管理文档工具链。预览和构建：

```bash
cd docs
npm ci
npm run dev
npm run build
```

仓库启用 GitHub Pages（Source 选择 GitHub Actions）后，文档工作流可从 `dev` 发布至
`https://huaweicloud.github.io/devspace-devbox/`。启用前以上地址不代表已上线。

## 安装

从仓库检出代码后安装：

```bash
python -m pip install ./python-sdk
npm install ./js-sdk
```

发布到语言包仓库后安装：

```bash
python -m pip install devbox-sdk
npm install devbox-js-sdk
```

## 快速开始

Python：

```python
from devbox import Sandbox

with Sandbox.create("default") as sandbox:
    result = sandbox.commands.run("printf 'hello from DevBox'")
    print(result.stdout)
```

JavaScript / TypeScript：

```typescript
import { Sandbox } from "devbox-js-sdk";

const sandbox = await Sandbox.create("default");
try {
  const result = await sandbox.commands.run("printf 'hello from DevBox'");
  console.log(result.stdout);
} finally {
  await sandbox.kill();
  await sandbox.close();
}
```

## 开发验证

```bash
cd python-sdk && python -m pip install -e ".[dev]" && ruff check . && mypy && pytest
cd js-sdk && npm ci && npm run check
```

## 贡献

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

仓库治理文件使用 Apache-2.0 许可证。各 SDK 的许可证以对应包目录中的 `LICENSE` 为准。
