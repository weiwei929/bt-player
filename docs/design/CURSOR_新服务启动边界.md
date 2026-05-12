# Cursor / 后续会话：新服务启动边界

> 用途：给新轻量 PureSource / Playlist 服务"插旗"，防止会话又默认打开 `/root/BT-player` 旧 Rust 实验树。

## 事实源（勿混看）

| 角色 | 路径 / 说明 |
|------|-------------|
| 文档与路线讨论事实源 | `D:\workspace\media\bt-player-new`（本仓库） |
| 旧 Rust 实验树（冻结） | `/root/BT-player`（仅历史/实验，**不迁移、不续开发**） |
| 关系 | **不默认同步**；新代码**不**写在旧树里。 |

## 新服务目标

- 资源提纯（intake、元数据、状态）
- **PotPlayer 播放列表后端**（`.m3u8` 为**路由清单**，不要求全库 HLS）

## 不做（冻结项）

- 扩展旧 **Rust / Tauri** 播放栈
- 自研 **Web 播放器** 或浏览器 `<video>` 全量调参
- **全量 HLS / fMP4** 化
- **ffmpeg relay** 作为主出口链路

（ffmpeg 仅允许未来"按需"：faststart / remux / 特殊转码，且不作为默认路径。）

## 第一版 HTTP 接口（最小集）

```text
POST /intake
GET  /resources
GET  /playlists/potplayer/default.m3u8
GET  /playlists/potplayer/recent.m3u8
```

后续再扩展 `movies` / `debug`、准入规则细节等，**不**回到旧 Rust 仓库实现。

## 推荐技术栈（二选一即可）

- **Python + FastAPI**，或
- **Node + TypeScript**

## 给 Cursor 的操作约束

- **不要**在 `/root/BT-player` 上继续 `cargo build` / `cargo check` 或补 Rust playlist。
- **不要**迁移该树中的 `potplaylist.rs` 等到本仓库。
- 新实现：**新开仓库或新目录**（如 `puresource-playlist` / `media-router`），以本文档为边界起点。

## 与 Caddy / 现网的关系（备忘）

- 公网路径 `/playlists/*` 应由反代指向**新服务**（或过渡期指向占位实现），**不要**交给前端静态 `file_server` 吞掉。
- 与现网 BT 缓存、鉴权、密钥等集成方式：**单独设计**，不在本文档展开。
