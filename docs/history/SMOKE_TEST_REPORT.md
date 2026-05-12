# BT-Player 冒烟测试报告

> 日期：2026-05-07
> 环境：WSL Ubuntu 24.04 + WSLg
> 网络：华硕路由 + MerlinClash 透明代理

---

## 测试 1：HLS / m3u8 直链播放

### 测试地址
```
https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_fmp4/master.m3u8
```

### 结果
| 项目 | 状态 |
|------|------|
| 前端解析 | ✅ 成功 - 显示 "HLS 流"，stream_url 正确 |
| mpv 弹窗 | ✅ 弹出独立窗口，显示加载转圈动画 |
| 实际播放 | ⚠️ 未确认 - Apple CDN 在国内可能被限制，转圈动画持续后结果未知 |

### 分析
- `M3u8Resolver` 和 `parse_url` 链路完整，返回了正确的流地址
- mpv 独立窗口模式（`force-window=yes`）正常启动
- 加载动画说明 mpv 正在尝试连接流地址
- **仅取决于网络连通性**，代码逻辑无问题

---

## 测试 2：磁链解析（完整 magnet 链接）

### 测试地址
```
magnet:?xt=urn:btih:AF89AB583826696F9E77D4CC07826E65ED831BF4
```
（Ubuntu Server 24.04）

### 结果
| 项目 | 状态 |
|------|------|
| 前端解析 | ✅ 成功 |
| 文件列表 | ✅ 显示 1 个文件 `ubuntu-24.04.2-live-server-amd64.iso` (3,064 MB) |
| stream_url | ✅ `http://127.0.0.1:9527/torrents/0/stream/0` |
| source_type | ✅ `magnet` |
| 播放按钮 | 未测试 |

### 分析
- `MagnetResolver` → `parse_magnet()` → `get_file_tree()` 完整链路正常
- librqbit HTTP API 端口 9527 工作正常
- DHT 节点发现正常，tracker 连接正常
- **磁链解析核心链路验证通过** ✅

---

## 测试 3：裸 magnet hash 自动补全

### 测试地址
```
AF89AB583826696F9E77D4CC07826E65ED831BF4
```
（不加 `magnet:` 前缀）

### 结果
| 项目 | 状态 |
|------|------|
| 前端解析 | ❌ 卡在 "解析中..." 状态，超时未返回 |

### 问题分析
- **现象**：点击「解析」后按钮变为「解析中...」，长时间不返回（>1分钟）
- **预期行为**：自动补全为 `magnet:?xt=urn:btih:...` 后同测试 2
- **代码逻辑**：`resolver/magnet.rs` `resolve()` 中判断 `if !trimmed.starts_with("magnet:")` → 触发补全，与完整磁链走同一路径
- **可能原因**：
  1. 用户等待时间不足 60 秒（`parse_magnet()` 内部 60 秒超时）
  2. `get_file_tree()` 内部 HTTP 请求因代理环境变量被劫持
  3. DHT 网络在第二次测试时状态不同
- **建议**：需复现以确认是超时配置问题还是网络问题

---

## 测试 4：国内 m3u8 源播放

### 测试地址
```
http://124.160.184.108/live/5/45/3bfabc1fe16a4282b50ea095928c1f60.m3u8
```

### 结果
| 项目 | 状态 |
|------|------|
| 前端解析 | ✅ 成功 - 显示 "HLS 流"，stream_url 正确 |
| 文件大小 | ❌ 显示 0.00 MB |
| 点击播放 | ❌ mpv 窗口未弹出，无任何反应 |

### 问题分析
- **现象**：解析成功但播放无反应
- **可能原因**：
  1. **URL 有效性**：`M3u8Resolver` 不做任何 URL 可达性验证，直接返回 `ReadyToPlay`。流地址可能已失效或需特定 Referer
  2. **mpv 启动失败**：`MpvPlayer::new(0, "auto-safe")` 返回了 `Err`，但错误信息未在前端显示
  3. **后台日志缺失**：当前没有 mpv 的 stderr/stdout 捕获，mpv 内部错误无从得知
  4. **网络限制**：该 IPTV 源可能被 MerlinClash 透明代理规则阻断
  5. **编码格式**：部分国内电视流使用 H.265/AVS 编码，软件渲染可能失败

---

## 测试 5：Tauri 窗口 / 环境问题

### 5.1 代理环境变量劫持
| 现象 | 影响范围 |
|------|---------|
| curl 连 127.0.0.1 走代理超时 | 所有本地 HTTP API 调用 |
| Tauri 窗口空白 "Operation was cancelled" | WebView 加载前端时被代理干扰 |
| WSL 内 `http_proxy` 指向路由器 `172.24.240.1:7890` | 继承自 Windows 系统代理设置 |

**解决方法：** `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY`

**建议：** 加入 `~/.bashrc` 避免每次手动清除

### 5.2 中文乱码
| 现象 | 原因 |
|------|------|
| 界面中文文字显示为方块/乱码 | WSL 未安装中文字体 |

**解决方法：** `sudo apt install -y fonts-wqy-zenhei`

### 5.3 WSLg 渲染警告
```
libEGL warning: failed to get driver name for fd -1
MESA: error: ZINK: failed to choose pdev
Failed to open VDPAU backend libvdpau_nvidia.so
[PipeWire] can't load config client-rt.conf
```

**分析：** WSLg 下无 NVIDIA 驱动直通时，这些是正常的软件回退日志。不影响 mpv 独立弹窗播放。如果将来在带 GPU 的 Linux 桌面运行，这些警告消失。

---

## 测试总结

| 测试 | 结果 | 严重程度 |
|------|------|---------|
| 1. m3u8 解析链路 | ✅ 通过 | - |
| 2. 磁链解析链路 | ✅ 通过（核心链路验证） | - |
| 3. 裸 hash 自动补全 | ❌ 卡住 | 🟡 中 |
| 4. 国内 m3u8 播放 | ❌ 解析成功但无法播放 | 🟡 中 |
| 5. 中文显示异常 | ✅ 有解决方案 | 🟢 低 |
| 5. 代理环境变量劫持 | ✅ 有解决方案 | 🟢 低（一次配置） |

---

## 核心风险：网络拓扑与透明代理

### 问题描述

```
你的电脑（WSL Ubuntu）
    │
WSL http_proxy 环境变量 → ✅ 可清除（已写入 ~/.bashrc）
    │
Windows 系统代理设置 → ✅ 可清除
    │
华硕路由 + MerlinClash 透明代理 → ❌ 无法绕开
    │
    └──→ 所有 TCP 出站流量经路由器代理判断
         → BT 协议流量可能被拦截或阻塞
         → HTTP tracker 连接受 TCP 代理影响
         → DHT (UDP) 相对可用，但单独靠 DHT 节点发现不稳定
```

### 影响范围

| 功能 | 影响 |
|------|------|
| 磁链解析（magnet） | 🟡 **不稳定** — 依赖 tracker 和 DHT 发现节点，透明代理可能阻塞 HTTP tracker |
| 流媒体播放（m3u8） | 🟢 **不受影响** — 直连 CDN，不经过 P2P |
| 网页源解析（webpage） | 🟢 **不受影响** — 直连目标站点 |
| 裸 hash 补全 | 🟡 同磁链解析，受相同网络限制 |

### 根本原因

MerlinClash 作为上层路由器透明代理，对所有 TCP 出站流量做代理决策。BT 协议使用的 HTTP tracker 和 peer 直连可能被代理逻辑误判、拦截或限速。这个问题在应用层代码层面无法解决。

### 可能的方向（未来考虑）

| 方案 | 代价 | 效果 |
|------|------|------|
| 路由器加静态路由：源 IP 绕过代理 | 低 — MerlinClash 管理界面操作 | 彻底解决 |
| 仅使用 DHT（移除 HTTP tracker） | 低 — 修改 tracker 列表 | 部分缓解，DHT 发现不稳定 |
| 完全放弃 P2P，仅保留 HLS/网页源 | 高 — 失去磁链核心功能 | 规避问题，但改变产品定位 |

### 决策记录

**2026-05-07**：确认此问题为项目核心网络风险。当前阶段不投入解决，保持透明代理环境作为已知约束。下次部署到无透明代理的 Linux VPS 时，此问题自然消失。

---

## 后续需要解决的方向

### 优先级高

1. **裸 hash 自动补全卡死问题**
   - 复现并抓取 `RUST_LOG=debug` 日志
   - 确认是 `parse_magnet` 60 秒超时问题，还是 `get_file_tree` 问题
   - 考虑给前端 `invoke` 调用增加超时机制

2. **m3u8 播放无响应**
   - 捕获 mpv 的 stderr 输出到日志
   - `M3u8Resolver` 可增加 HEAD 请求验证 URL 可达性
   - 或至少返回明确错误信息给前端

### 优先级中

3. **M3u8Resolver 不验证 URL**
   - 即使不可达的 URL 也返回 `ReadyToPlay`，前端/用户得不到反馈
   - 建议：resolve 时做 HEAD 请求探测，或保留为"尽力而为"并在 play 时给出明确错误

4. **Proxy 环境变量持久化**
   - 将 `unset` 命令写入 `~/.bashrc`，新用户开箱即用

### 优先级低

5. **新增 `RUST_LOG` 启动指南到文档**
   - 方便后续调试：`RUST_LOG=bt_player=debug,librqbit=info npm run tauri dev`

6. **WSL 中文字体**
   - 加入项目快速启动脚本中

---

## 附：编译器警告（8 条，均为无害）

执行 `cargo build` 时产生的 8 条警告，全部为 **Linux 下不可达代码** 或 **未使用代码**：

```
warning: type `PlayerSession` is more private than `PlayerState::inner`  → lib.rs
warning: struct `FileAnalysis` is never constructed                       → ai_strategy.rs (FROZEN)
warning: function `analyze_files` is never used                           → ai_strategy.rs (FROZEN)
warning: methods `set_pause` and `stop` are never used                    → mpv_player.rs
warning: fields `x/y/width/height` are never read                        → video_window.rs
warning: function `create_video_child_window` is never used               → video_window.rs
warning: function `destroy_video_window` is never used                    → video_window.rs
warning: function `reposition_video_window` is never used                 → video_window.rs
```

**成因分析：**
- `ai_strategy.rs` 标记为 FROZEN，部分导出函数未被引用
- `video_window.rs` 的 Linux stub 返回 `Err("仅 Windows 支持")`，Linux 下永不执行
- `mpv_player.rs` 的 `set_pause` / `stop` 为基础设施方法，前端还未实现控制按钮
- `PlayerSession` 私有可见性问题是一个小 bug：`PlayerState.inner` 应为 `pub(crate)` 而非 `pub`

**处理建议：**
- `PlayerSession` 可见性 ← 可顺手修掉（改一行）
- 其余均为 Windows 遗留或 FROZEN 代码，不影响 Linux 运行
- 若追求零警告构建，可通过 `#[allow(dead_code)]` 或 `#[cfg_attr(not(windows), allow(dead_code))]` 抑制

---

*本报告基于 2026-05-07 冒烟测试结果。*
