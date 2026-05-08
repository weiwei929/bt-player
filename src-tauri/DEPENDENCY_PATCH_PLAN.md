# BT-Player 依赖补丁治理方案（本地可复现）

## 目标

在不依赖远端 Git 仓库的前提下，把 Rust 依赖固化到项目本地，彻底摆脱“手改 cargo 缓存”。

## 当前做法

- 已在 `src-tauri/vendor/` 生成完整依赖快照（含 `librqbit`）。
- 已新增 `src-tauri/.cargo/config.toml`，强制 Cargo 优先从本地 `vendor` 读取依赖。
- 已新增 `src-tauri/local-patches/librqbit/` 保存本地补丁版 `librqbit`。
- 已在 `src-tauri/Cargo.toml` 通过 `[patch.crates-io]` 覆盖 `librqbit` 为本地路径。

配置如下：

```toml
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
```

```toml
[patch.crates-io]
librqbit = { path = "local-patches/librqbit" }
```

## 使用方式

在 `src-tauri` 目录执行：

- 构建检查：`cargo check`
- 正常构建：`cargo build`

不需要额外下载 crates.io 源码（除非你主动刷新 vendor）。

## 后续更新流程（升级依赖时）

1. 临时注释 `src-tauri/.cargo/config.toml` 中 source 替换（或在可联网环境操作）。
2. 调整 `Cargo.toml` 版本并执行 `cargo update`。
3. 执行 `cargo vendor vendor` 重新生成本地依赖快照。
4. 恢复 `src-tauri/.cargo/config.toml` 配置。
5. 再执行 `cargo check` 验证。

## 风险与边界

- `vendor` 目录体积较大，但换来的是高确定性和可迁移性。
- 这是“工程快照”方案，不等同于长期维护上游 fork。
- 若未来要多人协作或接入 CI，再升级到 `Fork + [patch.crates-io]` 会更优雅。

## 验收标准

- 新机器仅复制项目目录后，可直接在 `src-tauri` 执行 `cargo check` 通过。
- 不再依赖 `~/.cargo/registry/src` 的手工修改内容。
