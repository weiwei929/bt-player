# PotPlayer 资源馆播放路由手验记录（2026-05-11）

## 结论

**MVP 路由闭环已验证通过。**

当前项目的新定位成立：

> VPS / PureSource 负责资源提纯、缓存治理与播放列表输出；PotPlayer 作为最终稳定播放执行器。

本次手验确认：`bt.mgtv.dev` 输出的 PotPlayer 可订阅 `.m3u8` 播放列表可以被 PotPlayer 添加为专辑，并能正常播放其中的真实 MP4 资源。

---

## 验证对象

| 项 | 内容 |
|----|------|
| PotPlayer 专辑名称 | `BT资源馆` |
| 播放列表 URL | `https://bt.mgtv.dev/playlists/potplayer/default.m3u8` |
| 测试条目 | `Cosmos Laundromat (PotPlayer 手验) [external_ready]` |
| 媒体 URL | `https://bt.mgtv.dev/Cosmos_Laundromat.faststart.mp4` |
| 播放执行器 | PotPlayer |
| 结果 | 列表可读取，条目可显示，视频可正常播放 |

---

## 已验证链路

```text
/opt/puresource-playlist/data/resources.json
  → puresource-playlist 生成 PotPlayer M3U8 路由清单
  → Caddy 公网输出 /playlists/potplayer/default.m3u8
  → PotPlayer 创建“BT资源馆”外部播放列表
  → PotPlayer 读取 #EXTINF 条目
  → PotPlayer 播放真实 MP4
```

该链路说明：系统不需要把所有资源统一转为 HLS，也不需要浏览器 `<video>` 承担主播放体验。VPS 端只要输出成熟播放器可消费的 URL / 播放列表，即可形成可用产品闭环。

---

## 关键判断

1. **播放列表通道成立**
   - PotPlayer 能读取 `https://bt.mgtv.dev/playlists/potplayer/default.m3u8`。
   - `.m3u8` 在这里是播放列表格式，不是 HLS 分片清单。

2. **成熟播放器执行层成立**
   - 同一资源在 PotPlayer 中可以正常播放。
   - 浏览器播放端不再作为当前主路线。

3. **“资源馆”产品形态成立**
   - PotPlayer 专辑可作为用户侧播放入口。
   - `bt.mgtv.dev` / puresource-playlist 可作为远端资源目录与路由后端。

4. **下一阶段应集中到资源提纯**
   - magnet metadata。
   - 文件树与正片识别。
   - 缓存成熟度。
   - 可用源池准入。
   - 自动写入 PotPlayer 播放列表。

---

## 明确冻结项

本次手验后，以下路线继续保持冻结或研究线状态：

- 自研 Web 播放器。
- 浏览器 `<video>` 稳定播放调参。
- 全量 HLS / fMP4 转换。
- ffmpeg relay 作为主出口链路。
- 旧 Rust / Tauri 播放器主线扩展。

---

## 后续建议

短期不要继续扩展播放端。下一步应围绕资源提纯和准入规则推进：

```text
用户提交 magnet / URL
  → PureSource 识别资源类型
  → 获取 metadata / 文件树
  → 识别正片和可播放资产
  → 判断 stable / playable / external_ready
  → 写入 puresource-playlist resources
  → PotPlayer “BT资源馆”自动出现新条目
```

这一节点标志着项目从“播放器工程”正式转为“资源提纯与播放路由系统”。
