# 环境探测报告 (Environment Analysis Report)

## 1. 存储环境 (Storage)
*   **配置情况**: 
    *   **盘符 0**: WD Green 2.5 1000GB (**SSD**)
    *   **盘符 1**: Samsung SSD 970 EVO 500GB (**NVMe SSD**)
*   **分析**: 
    *   你的系统完全由 SSD 构成，其中三星 970 EVO 具有极高的读写吞吐量。
    *   **优化策略**: 我们可以采用更激进的并行 IO 写入策略。SSD 对随机读写不敏感，因此在播放时后台进行多线程数据校验几乎不产生寻道延迟。
    *   **下载路径建议**: 默认下载路径应设在 SSD 上，以支持极速的“边看边预取”内存交换。

## 2. 网络环境 (Connectivity)
*   **物理架构**: 华硕路由器 + 梅林 (Merlin) 固件 + MerlinClash 透明代理。
*   **内部 IP**: `192.168.50.159`
*   **外部展示 IP**: `104.194.88.5` (可能为代理节点 IP)
*   **分析**: 
    *   **代理冲突**: 透明代理环境可能导致 BT 下载流量误走代理通道导致延迟增加。
    *   **优化策略**: 
        1.  **Port-Specific Bypass (端口分流)**: 针对梅林固件 + MerlinClash 环境，**不要**绕过整机 IP（否则会丢失 AI 协作连接）。应在 MerlinClash 的“绕过地址/端口”列表中，将应用固定的 TCP/UDP 端口 `50051` 设为 **Direct (直连)**。
        2.  **uTP & UPnP 激活**: 已在代码层面强制开启 uTP (UDP传输) 和 UPnP。
        3.  **DHT 预热**: 针对梅林环境可能存在的 UDP 握手丢包，在 Rust 端已配置 `ListenerMode::All` 以支持更积极的 Peer 发现。

---

## 3. 对 SPEC 的补充调整 (Optimizations)

### 3.1 磁盘 IO (Optimized for SSD)
*   **Sparse File (稀疏文件)**: 利用 NTFS 对 SSD 的优化，直接创建完整大小的稀疏文件，避免下载过程中频繁动态增加文件大小导致的磁盘开销。
*   **Disk Buffer**: 利用 32GB 内存，设置 256MB 的写缓冲区，减少对 SSD 的写入磨损。

### 3.2 网络连接 (Peer Discovery)
*   **Aggressive Seeding**: 由于 SSD 读写极快，可以增加并发 Peer 连接数（设为 200+），充分压榨 104.194.xx.xx 网段的带宽能力。

---
*检测日期: 2026-02-14*
*执行引擎: Gemini 3 Flash (Preview)*
