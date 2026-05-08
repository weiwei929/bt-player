# libmpv 配置说明 (第三阶段)

Windows 下需准备 mpv 开发包供 `libmpv-sys` 链接。**构建前必须完成此步骤**。

## 方式一：自动下载（推荐）

```powershell
.\scripts\fetch-mpv.ps1
```

需要安装 [7-Zip](https://www.7-zip.org/)。脚本会将 `mpv-1.dll`、`mpv.lib` 等解压到 `src-tauri/mpv/`。

## 方式二：手动配置

1. 从 [shinchiro/mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake/releases) 下载 `mpv-dev-x86_64-*.7z`
2. 解压后，将 `64/` 目录下的 `mpv-1.dll`、`mpv.lib` 等放入 `src-tauri/mpv/`（或 `src-tauri/mpv/64/`）
3. 或设置环境变量：`$env:MPV_LIB_DIR = "C:\path\to\mpv\64"`

## 运行时

`mpv-1.dll` 需在可执行文件同目录或 `PATH` 中。开发时 `cargo run` 会从 `target/debug/` 运行，可将 dll 复制到该目录，或使用 `tauri dev`（Tauri 会处理）。

## 验证

```powershell
cd src-tauri
cargo build
```

若链接成功，则配置正确。
