# 语义文件搜索应用

## 项目简介

这是一个桌面应用程序，旨在提供强大的语义文件搜索功能。它结合了后端 FastAPI 服务和前端 Electron 界面，允许用户管理文件空间、索引文件内容，并进行高效的全文搜索。

## 主要功能

*   **文件空间管理**：创建、编辑、删除和重新排序文件搜索空间。
*   **目录路径管理**：为每个文件空间添加或删除要索引的目录路径。
*   **文件内容索引**：自动扫描指定目录下的文件，提取文本内容并建立索引，支持多种文件类型（PDF, DOCX, XLSX, TXT, MD, Python, JS, HTML, CSS, JSON, XML, CSV）。
*   **语义搜索**：利用 SentenceTransformer 模型进行语义搜索，提供与查询内容高度相关的结果。
*   **文件名搜索**：支持按文件名进行模糊搜索。
*   **索引状态监控**：实时显示索引进度和状态。
*   **工厂重置**：提供重置应用程序数据和配置的选项。

## 技术栈

*   **后端**：
    *   Python 3
    *   FastAPI (Web 框架)
    *   Uvicorn (ASGI 服务器)
    *   SQLite (数据库)
    *   jieba (中文分词)
    *   sentence-transformers (语义嵌入)
    *   pypdf, docx, openpyxl (文件内容提取)
*   **前端**：
    *   Electron (桌面应用框架)
    *   Node.js
    *   HTML/CSS/JavaScript
*   **构建/脚本**：
    *   Bash 脚本 (`.sh`)
    *   npm (包管理)
    *   pip (Python 包管理)

## 安装与运行

### 环境准备

确保您的系统已安装以下软件：

*   Python 3.8+
*   Node.js (推荐 LTS 版本)
*   npm (Node.js 安装时会包含)

### 安装依赖

1.  **克隆仓库**：
    ```bash
    git clone <your-repository-url>
    cd semantic-file-search
    ```
2.  **重建缓存和安装依赖**：
    运行 `rebuild_cache.sh` 脚本将创建 Python 虚拟环境，安装所有 Python 依赖，并安装 Electron 应用的 Node.js 依赖。

    ```bash
    ./rebuild_cache.sh
    ```
    **注意**：如果在 `pip install` 过程中遇到 SSL 证书错误，请确保 `rebuild_cache.sh` 脚本中的 `pip install` 命令包含 `--trusted-host pypi.org --trusted-host files.pythonhosted.org` 参数。

### 运行应用

1.  **启动后端服务**：
    后端服务通常由 Electron 应用自动启动。如果您需要单独启动后端进行开发或调试，可以运行：

    ```bash
    ./start_backend.sh
    ```
    后端服务将运行在 `http://127.0.0.1:8233`。

2.  **运行 Electron 应用**：
    进入 `electron_app` 目录并启动应用：

    ```bash
    cd electron_app
    npm start
    ```
    这将启动桌面应用程序界面。

### 构建桌面应用

要构建可分发的桌面应用程序包，请运行：

```bash
./build.sh
```
这将生成适用于您操作系统的安装包。

## 项目结构

```
.
├── .git/
├── .gitignore
├── .venv/                 # Python 虚拟环境
├── backend/               # FastAPI 后端服务代码
│   ├── config.py          # 配置加载
│   ├── database.py        # SQLite 数据库初始化和表结构
│   ├── db_manager.py      # 数据库操作管理器 (单例，线程安全)
│   ├── indexer.py         # 文件索引逻辑 (文本提取, 分词, 写入FTS)
│   ├── scanner.py         # 文件系统扫描和变更检测
│   ├── search.py          # 搜索逻辑 (FTS查询, 语义重排)
│   └── state.py           # 索引器状态管理
├── electron_app/          # Electron 前端应用代码
│   ├── .npmrc
│   ├── main.js            # Electron 主进程 (启动后端, IPC通信)
│   ├── package.json       # Electron 应用配置和依赖
│   ├── preload.js         # 预加载脚本 (安全地暴露 Node.js API 给渲染进程)
│   └── public/            # 静态资源 (HTML, CSS, JS, 图片)
│       └── index.html
├── build.sh               # 构建 Electron 应用的脚本
├── clean_cache.sh         # 清理构建产物、缓存和虚拟环境的脚本
├── main.py                # FastAPI 应用主入口，定义 API 路由
├── rebuild_cache.sh       # 重建虚拟环境和安装所有依赖的脚本
├── requirements.txt       # Python 依赖列表
├── sa_config.cfg          # 应用程序配置文件
└── start_backend.sh       # 启动后端 FastAPI 服务的脚本
```

## 配置

应用程序的主要配置通过 `sa_config.cfg` 文件管理：

```ini
[general]
VERS = 0.0.3.250713_Dev

[server]
LISTEN_IP = 127.0.0.1
LISTEN_PORT = 8233
DEBUG_MODE = true

[database]
DB_PATH = ~/.search_app/chroma.sqlite3 # 数据库文件路径

[models]
HF_ENDPOINT = https://hf-mirror.com # Hugging Face 模型下载镜像，可根据需要修改

[logging]
LOG_DIR = ~/.search_app/logs # 日志文件存储路径
```
您可以根据需要修改这些配置，例如更改后端监听端口、数据库路径或 Hugging Face 镜像。

## 脚本说明

*   `build.sh`：用于构建 Electron 桌面应用程序的可分发包。它会安装 Python 和 Node.js 依赖，然后使用 `electron-builder` 进行打包。
*   `clean_cache.sh`：清理项目中的各种缓存文件、虚拟环境、Node.js 模块和构建产物，用于保持项目目录的整洁。
*   `rebuild_cache.sh`：重建 Python 虚拟环境并重新安装所有 Python 和 Node.js 依赖。当依赖发生变化或环境损坏时使用。
*   `start_backend.sh`：单独启动后端 FastAPI 服务的脚本。它会激活 Python 虚拟环境，设置 Hugging Face 镜像，并启动 Uvicorn 服务器。

## 注意事项

*   **文件路径**：在添加文件空间路径时，请确保路径是有效的目录。
*   **索引过程**：首次索引大量文件可能需要一些时间，具体取决于文件数量和大小。
*   **模型下载**：语义搜索功能依赖于 Hugging Face 上的 `BAAI/bge-small-zh-v1.5` 模型。首次运行时会自动下载，请确保网络连接畅通。如果下载缓慢，可以尝试修改 `sa_config.cfg` 中的 `HF_ENDPOINT` 为其他镜像。
*   **pkg_resources 警告**：您可能会在控制台看到 `UserWarning: pkg_resources is deprecated` 的警告。这是一个来自 `jieba` 库的警告，表示其使用了即将弃用的 Python 包。目前这不影响程序功能，但未来版本可能会解决。