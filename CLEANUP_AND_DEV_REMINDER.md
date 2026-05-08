# BT-Player 清理记录与开发建议

> 本文档记录 2026-03-09 进行的项目清理，以及后续开发/测试时的空间管理建议。
> **统一管理副本**：`D:\workspace\docs\system\CLEANUP_AND_DEV_REMINDER.md`

---

## 一、2026-03-09 清理记录

### 1.1 AppData 运行时数据（约 4.5 GB）

| 路径 | 内容 | 状态 |
|------|------|------|
| `C:\Users\<用户>\AppData\Local\com.btplayer.app` | 运行时数据、下载文件、数据库、EBWebView 等 | ✅ 已删除 |

**说明**：Tauri 应用首次运行后会在该路径创建数据目录。若曾通过 BT-Player 下载文件（如 Ubuntu ISO），会存储于此。

### 1.2 项目构建产物（约 22 GB）

| 路径 | 内容 | 状态 |
|------|------|------|
| `src-tauri/target/` | Rust 编译产物（debug/release） | ✅ 已删除 |
| `target/` | 根目录 Cargo 工作区编译产物 | ✅ 已删除 |
| `node_modules/` | npm 依赖 | ✅ 已删除 |
| `dist/` | 前端 Vite 构建输出 | ✅ 已删除 |
| `bt_cache/` | BT 缓存（若存在） | ✅ 已删除 |

### 1.3 保留内容

- 源码：`src/`、`src-tauri/src/`
- 配置文件：`package.json`、`tauri.conf.json`、`Cargo.toml` 等
- 文档与脚本
- `.git/` 版本历史

---

## 二、将来启动测试时的建议

### 2.1 将构建产物放到其他盘（推荐）

为避免占用 C 盘，建议在 **D 盘**（或其它非系统盘）进行临时构建：

#### 方式一：环境变量（推荐）

在启动开发/构建前，于**当前终端**设置：

```powershell
# PowerShell
$env:CARGO_TARGET_DIR = "D:\workspace\media\bt-player-build\target"
npm run tauri dev
```

或创建 `scripts/dev-on-d.ps1`：

```powershell
# 在 D 盘构建，不占用 C 盘
$env:CARGO_TARGET_DIR = "D:\workspace\media\bt-player-build\target"
npm run tauri dev
```

#### 方式二：Cargo 配置

在项目根目录或 `~/.cargo/config.toml` 中配置：

```toml
# .cargo/config.toml（项目内）
[build]
target-dir = "D:/workspace/media/bt-player-build/target"
```

#### 方式三：npm 缓存迁移

```powershell
npm config set cache "D:\workspace\media\bt-player-build\.npm-cache"
```

### 2.2 运行时数据（AppData）说明

- **位置**：`%LocalAppData%\com.btplayer.app`
- **内容**：下载文件、数据库、WebView 缓存等
- **说明**：Tauri 默认使用系统 AppData，路径由框架决定。若需减少 C 盘占用，可考虑：
  1. 在应用内将**下载目录**配置到 D 盘（若已实现该功能）
  2. 定期清理上述 AppData 目录中的大文件
  3. 测试完成后手动删除 `com.btplayer.app` 文件夹

### 2.3 恢复开发环境

清理后重新开发时：

```bash
npm install          # 恢复 node_modules
npm run tauri dev    # 开发模式（会重新编译 Rust，首次较慢）
```

若已设置 `CARGO_TARGET_DIR` 到 D 盘，则 Rust 编译产物会生成在 D 盘。

---

## 三、Rust 环境迁移至 D 盘（系统级）

为减少 C 盘占用，已将 Rust 相关目录通过符号链接迁移至 `D:\UserData\`：

| 目录 | C 盘路径 | D 盘实际位置 | 状态 |
|------|----------|--------------|------|
| `.rustup` | `C:\Users\Admin\.rustup` | `D:\UserData\.rustup` | ✅ 符号链接 |
| `.cargo` | `C:\Users\Admin\.cargo` | `D:\UserData\.cargo` | ✅ 符号链接 |

### 3.1 `.cargo` 迁移步骤（2026-03-09 已执行）

在**管理员 PowerShell** 中执行：

```powershell
# 1. 复制到 D 盘
Copy-Item -Path "C:\Users\Admin\.cargo" -Destination "D:\UserData\.cargo" -Recurse

# 2. 删除原目录
Remove-Item "C:\Users\Admin\.cargo" -Recurse -Force

# 3. 创建符号链接
cmd /c mklink /D "C:\Users\Admin\.cargo" "D:\UserData\.cargo"
```

执行结果：`为 C:\Users\Admin\.cargo <<===>> D:\UserData\.cargo 创建的符号链接`

**注意**：执行前需关闭所有使用 Rust/Cargo 的程序（终端、IDE 等）。

---

## 四、C 盘精简验证（2026-03-09 复查）

### 4.1 精简效果

| 指标 | 清理前 | 清理后 | 变化 |
|------|--------|--------|------|
| C 盘已用 | ~114 GB | **100.8 GB** | 释放约 13 GB |
| C 盘可用 | ~36 GB | **48.7 GB** | +12.7 GB |
| Users 目录 | ~57 GB | **44.6 GB** | -12.4 GB |

### 4.2 迁移/清理项验证

| 项目 | 状态 |
|------|------|
| `com.btplayer.app` | ✅ 已删除 |
| `.cargo` | ✅ 符号链接 → D:\UserData\.cargo |
| `.rustup` | ✅ 符号链接 → D:\UserData\.rustup |

### 4.3 当日其他操作（关联记录）

- **Go 卸载**：同日于 sub2api 项目中执行了 Go 完全卸载，详见 `D:\workspace\ai-tools\sub2api\LOCAL_OPERATION_LOG_CN.md`。

---

## 五、可参照迁移的 C 盘项目（建议）

以下项目可参照 Rust 的符号链接或环境变量方式迁移至 D 盘，进一步释放 C 盘空间：

### 5.1 推荐迁移（操作简单、风险低）

| 项目 | 当前路径 | 大小 | 迁移方式 |
|------|----------|------|----------|
| **npm 缓存** | `%LocalAppData%\npm-cache` | ~1 GB | `npm config set cache "D:\UserData\npm-cache"` |
| **Go 构建缓存** | `%LocalAppData%\go-build` | ~0.8 GB | 用户环境变量 `GOCACHE=D:\UserData\go-build`（*注：Go 已于 2026-03-09 卸载，若重装可参考*） |
| **Go 工作区** | `C:\Users\Admin\go` | ~0.7 GB | 用户环境变量 `GOPATH=D:\UserData\go`，然后迁移目录+建链接（*同上*） |
| **Bun** | `C:\Users\Admin\.bun` | ~0.4 GB | 复制→删除→符号链接（同 .cargo 步骤） |

### 5.2 可选迁移（需评估影响）

| 项目 | 当前路径 | 大小 | 说明 |
|------|----------|------|------|
| **Chrome 用户数据** | `%LocalAppData%\Google\Chrome` | ~5.6 GB | 需用 `--user-data-dir` 启动或整体迁移，操作复杂 |
| **VS Code 扩展** | `%AppData%\Code` | ~6.2 GB | 可迁移部分扩展缓存，或改用 `--extensions-dir` |
| **Edge 缓存** | `%LocalAppData%\Microsoft\Edge` | ~1.2 GB | 类似 Chrome，可定期清理缓存 |
| **ProgramData 包缓存** | `C:\ProgramData\Package Cache` | ~0.6 GB | Visual Studio 相关，删除可能影响修复/卸载 |

### 5.3 迁移步骤参考（以 npm 缓存为例）

```powershell
# 设置 npm 缓存到 D 盘（立即生效，无需迁移已有文件）
npm config set cache "D:\UserData\npm-cache"
```

### 5.4 迁移步骤参考（以 Go 为例，若将来重装可参考）

> **说明**：Go 已于 2026-03-09 卸载（见 `D:\workspace\ai-tools\sub2api\LOCAL_OPERATION_LOG_CN.md`）。以下步骤供将来重装 Go 后迁移使用。

```powershell
# 1. 设置环境变量（系统属性 → 环境变量 → 用户变量）
GOPATH = D:\UserData\go
GOCACHE = D:\UserData\go-build

# 2. 迁移 go 目录（若已有内容）
Copy-Item "C:\Users\Admin\go" "D:\UserData\go" -Recurse
Remove-Item "C:\Users\Admin\go" -Recurse -Force
cmd /c mklink /D "C:\Users\Admin\go" "D:\UserData\go"

# 3. go-build 为缓存，可直接设置 GOCACHE，旧缓存可删除
Remove-Item "$env:LOCALAPPDATA\go-build" -Recurse -Force -ErrorAction SilentlyContinue
```

---

## 六、Chrome / Edge / VS Code 清理与迁移（2026-03-09）

### 6.1 第一步：缓存清理（已完成）

| 应用 | 清理前 | 清理后 | 释放 |
|------|--------|--------|------|
| Chrome | ~5.6 GB | ~0.94 GB | ~4.7 GB |
| Edge | ~1.2 GB | ~0.84 GB | ~0.4 GB |
| **合计** | | | **~5 GB** |

**执行方式**：运行 `scripts/cleanup-browser-cache.ps1`（需先关闭 Chrome 和 Edge）

```powershell
powershell -ExecutionPolicy Bypass -File "D:\workspace\media\BT-player\scripts\cleanup-browser-cache.ps1"
```

**VS Code**：需在扩展面板中手动卸载不常用扩展。

### 6.2 第二步：迁移至 D 盘（已完成）

| 应用 | 源路径 | D 盘位置 | 状态 |
|------|--------|----------|------|
| Chrome | `%LocalAppData%\Google\Chrome` | `D:\UserData\Chrome` | ✅ 已迁移 |
| Edge | `%LocalAppData%\Microsoft\Edge` | `D:\UserData\Edge` | ✅ 已迁移 |
| VS Code | `%AppData%\Code` | `D:\UserData\Code` | ✅ 已迁移 |
| Cursor | `%AppData%\Cursor` | `D:\UserData\Cursor` | ✅ 已迁移 |

**执行方式**（供将来参考）：以**管理员身份**运行 `scripts/migrate-to-d.ps1`。Chrome、Edge、VS Code、Cursor 均已迁移完成。

**扩展迁移**（Notion、adspower、PikPak、GitHubDesktop、SquirrelMachineInstalls）：

```powershell
# 迁移全部（需先关闭对应应用）
.\scripts\migrate-to-d.ps1 -Target AppDataExtras

# 或单独迁移
.\scripts\migrate-to-d.ps1 -Target Notion
.\scripts\migrate-to-d.ps1 -Target adspower_global
.\scripts\migrate-to-d.ps1 -Target PikPak
.\scripts\migrate-to-d.ps1 -Target GitHubDesktop
.\scripts\migrate-to-d.ps1 -Target SquirrelMachineInstalls
```

### 6.3 已卸载应用残留清理（2026-03-09）

**脚本**：`scripts/cleanup-orphaned-appdata.ps1`

```powershell
# 仅删除空文件夹
.\scripts\cleanup-orphaned-appdata.ps1

# 同时删除已知残留（Rufus、RealVNC、AmneziaVPN、AnyDesk 等）
.\scripts\cleanup-orphaned-appdata.ps1 -IncludeOrphans

# 预览模式
.\scripts\cleanup-orphaned-appdata.ps1 -IncludeOrphans -WhatIf
```

已清理：空文件夹 20 个 + 已知残留 33 个（约 1.9 MB）。

---

## 七、快速参考

| 项目 | 建议 |
|------|------|
| Rust 工具链 (.rustup/.cargo) | 已迁移至 D:\UserData\（符号链接） |
| Rust 编译产物 (target) | 使用 `CARGO_TARGET_DIR` 指向 D 盘 |
| npm 缓存 | `npm config set cache "D:\UserData\npm-cache"` |
| Go (GOPATH/GOCACHE) | 已卸载（2026-03-09）；若重装可参考第五节 |
| Bun (.bun) | 可符号链接至 D:\UserData\.bun |
| **Chrome / Edge** | 缓存已清理；已迁移至 D:\UserData\Chrome、D:\UserData\Edge |
| **VS Code / Cursor** | 已迁移至 D:\UserData\Code、D:\UserData\Cursor |
| **已卸载应用残留** | `cleanup-orphaned-appdata.ps1 -IncludeOrphans` |
| 下载文件 | 在应用内配置到 D 盘（若支持） |
| 测试后清理 | 可删除 `%LocalAppData%\com.btplayer.app` |

---

*文档创建：2026-03-09 | 更新：Rust 迁移、C 盘验证、可迁移项、Go 卸载、Chrome/Edge/VS Code 清理与迁移*
