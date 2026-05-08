# C 盘完整扫描报告

> 扫描时间：2026-03-09 | 数据更新：2026-03-12  
> **统一管理副本**：`D:\workspace\docs\system\C_DRIVE_SCAN_REPORT.md`

---

## 一、总体状态

| 项目 | 数值 |
|------|------|
| **已用** | 67.7 GB |
| **可用** | 81.8 GB |
| **总容量** | 149.5 GB |

---

## 二、主要目录占用

| 路径 | 大小 | 说明 |
|------|------|------|
| C:\Windows | 33.52 GB | 系统文件 |
| C:\Program Files | 7.08 GB | 64 位程序 |
| C:\Program Files (x86) | 9.95 GB | 32 位程序 |
| C:\Users | 30.44 GB | 用户数据（含符号链接目标大小） |
| C:\ProgramData | 3.75 GB | 程序共享数据 |

---

## 三、Windows 子目录（>500 MB）

| 目录 | 大小 | 说明 |
|------|------|------|
| WinSxS | 17.98 GB | 组件存储，**勿手动删除** |
| System32 | 7.25 GB | 系统核心 |
| assembly | 2.90 GB | .NET 程序集 |
| SystemApps | 1.15 GB | 系统应用 |
| SysWOW64 | 1.06 GB | 32 位兼容 |
| Microsoft.NET | 0.60 GB | .NET 运行时 |
| servicing | 0.57 GB | 系统维护 |
| Installer | 0.55 GB | MSI 安装缓存 |

---

## 四、用户数据明细

### 4.1 AppData\Local（>100 MB）

| 目录 | 大小 | 清理建议 |
|------|------|----------|
| **Programs** | 4.01 GB | 含 Antigravity、anytype、Python、VS Code、Termius、waveterm、Notion 等；若已卸载对应应用，其子目录可删 |
| GitHubDesktop | 1.14 GB | 若已卸载可删 |
| Microsoft | 1.14 GB | Edge(857MB)、Olk(967MB) 等；Edge 已迁移至 D |
| **npm-cache** | 0.96 GB | 可迁移：`npm config set cache "D:\UserData\npm-cache"` |
| Packages | 0.84 GB | UWP 应用数据 |
| **go-build** | 0.79 GB | **Go 已卸载，可安全删除** |
| Logseq | 0.74 GB | 若已卸载可删 |
| Discord | 0.50 GB | 若已卸载可删 |
| waveterm-updater | 0.30 GB | 更新器缓存 |
| cherrystudio-updater | 0.22 GB | 更新器缓存 |
| anytype-updater | 0.19 GB | 更新器缓存 |
| notion-updater | 0.18 GB | 更新器缓存 |
| UniGetUI | 0.15 GB | 包管理器 |
| pikpak-updater | 0.10 GB | 更新器缓存 |

### 4.2 AppData\Roaming（>100 MB，部分已迁移至 D）

| 目录 | 大小 | 说明 |
|------|------|------|
| Code | 6.24 GB | 已迁移至 D:\UserData\Code |
| Cursor | 4.77 GB | 已迁移至 D:\UserData\Cursor |
| Trae | 2.62 GB | 应用数据 |
| Notion | 2.33 GB | 应用数据 |
| adspower_global | 2.24 GB | 指纹浏览器 |
| PikPak | 1.14 GB | 网盘 |
| Tencent | 1.00 GB | 腾讯系 |
| anytype | 0.62 GB | 应用数据 |
| Antigravity | 0.54 GB | 应用数据 |
| obsidian | 0.39 GB | 笔记应用 |
| Qoder | 0.28 GB | 应用数据 |
| Typora | 0.13 GB | Markdown 编辑器 |
| discord | 0.11 GB | 应用数据 |

### 4.3 用户目录下点开头文件夹（>50 MB）

| 目录 | 大小 | 说明 |
|------|------|------|
| .vscode | 1.35 GB | VS Code 工作区/扩展 |
| .rustup | 1.14 GB | 已迁移至 D |
| .cargo | 0.96 GB | 已迁移至 D |
| .gemini | 0.69 GB | Gemini 相关 |
| .local | 0.66 GB | 本地数据 |
| .cursor | 0.41 GB | Cursor 相关 |
| .bun | 0.41 GB | Bun 包管理器 |
| .antigravity | 0.39 GB | 应用数据 |
| .cherrystudio | 0.38 GB | 应用数据 |
| .codegeex | 0.31 GB | 应用数据 |

### 4.4 ProgramData（>100 MB）

| 目录 | 大小 | 说明 |
|------|------|------|
| Microsoft | 2.18 GB | 微软相关 |
| Package Cache | 0.63 GB | Visual Studio 安装缓存 |
| NVIDIA Corporation | 0.54 GB | 显卡驱动 |
| NVIDIA | 0.12 GB | 显卡相关 |
| SquirrelMachineInstalls | 0.12 GB | Squirrel 更新器 |

---

## 五、清理建议（按优先级）

### 5.1 立即可删（安全）

| 项目 | 路径 | 预计释放 |
|------|------|----------|
| **go-build 缓存** | `%LocalAppData%\go-build` | ~0.8 GB |
| **Programs 中已卸载应用** | `%LocalAppData%\Programs\Termius` 等 | 视具体应用 |
| **空文件夹** | AppData 中 | 少量 |

### 5.2 可迁移至 D 盘

| 项目 | 操作 |
|------|------|
| **npm 缓存** | `npm config set cache "D:\UserData\npm-cache"` |
| **Bun** | 符号链接至 D:\UserData\.bun（同 .cargo 步骤） |
| **.gemini** | 若不用可删；若用可迁移 |

### 5.3 需确认后处理

| 项目 | 说明 |
|------|------|
| **Programs** | 检查 Antigravity、anytype、Termius、waveterm、Notion 等是否仍在使用；未用可删对应子目录 |
| **Package Cache** | VS 安装缓存，删除可能影响修复/卸载 |
| **SquirrelMachineInstalls** | Squirrel 应用更新缓存，可清理 |

### 5.4 不建议动

| 项目 | 说明 |
|------|------|
| WinSxS | 系统组件，用 `DISM` 清理，勿手动删 |
| Windows\Temp | 已空 |
| SoftwareDistribution\Download | 已空 |

---

## 六、推荐执行顺序

1. **删除 go-build**（Go 已卸载）
2. **迁移 npm 缓存**到 D 盘
3. **检查 Programs**：确认 Termius、AnythingLLM 等是否已卸载，删除对应残留
4. **运行** `cleanup-orphaned-appdata.ps1 -IncludeOrphans` 清理空文件夹和已知残留
5. **可选**：Bun、.gemini 迁移或删除

---

## 七、执行记录

### 2026-03-09 执行结果

| 步骤 | 状态 | 说明 |
|------|------|------|
| 1. 删除 go-build | ✅ 已完成 | Go 已卸载，已删除 |
| 2. 迁移 npm 缓存 | ✅ 已完成 | `npm config set cache "D:\UserData\npm-cache"` |
| 3. 检查 Programs | ✅ 已完成 | 删除 AnythingLLM（空文件夹）、Termius（约 391 MB）残留 |
| 4. 运行 cleanup-orphaned-appdata.ps1 | ✅ 已完成 | 已执行 `-IncludeOrphans`，无新增可清理项 |
| 5. 可选迁移 | 待定 | Bun、.gemini 可按需处理 |

**当前 C 盘状态**（执行后）：约 75.6 GB 已用，约 73.9 GB 可用。

### 2026-03-12 执行结果

| 项目 | 状态 | 说明 |
|------|------|------|
| 卸载 Termius | ✅ 已完成 | 释放约 390 MB |
| 卸载 NVIDIA FrameView SDK | ✅ 已完成 | 释放约 51 MB |
| 卸载 Visual Studio 生成工具 2022 | ✅ 已完成 | 释放约 3.36 GB |
| 卸载 Microsoft Visual Studio Installer | ✅ 已完成 | 释放约 100 MB |
| 删除 VS 残留空目录 | ✅ 可选 | `C:\Program Files (x86)\Microsoft Visual Studio\Shared` |
| Anaconda/conda 彻底卸载 | ✅ 已完成 | 用户 PATH 已清理；开始菜单残留已删；系统 PATH 需管理员执行 `remove-conda-from-path.ps1` |

**当前 C 盘状态**（2026-03-12 后）：约 67.7 GB 已用，约 81.8 GB 可用（累计释放约 8 GB）。

---

*报告生成：2026-03-09 | 最后更新：2026-03-12*
