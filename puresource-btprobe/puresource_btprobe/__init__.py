"""puresource-btprobe — 独立 BT metadata 探测子服务（v0.3 T-2）。

边界（刻意保留，对应架构小结 §2.3.2 红线 + §2 D1 B 方案）：
- 这是一个**独立进程**，不与 puresource-playlist 主服务共享地址空间。
- 仅承担 magnet → 文件树 / peer 数 的探测，不做缓存、不做下载、不做播放路由。
- qBittorrent 凭据通过环境变量注入，永远不出现在 puresource-playlist 主服务里。
- 与主服务的通信是 fire-and-forget + HTTP callback；主服务对本服务无状态依赖。

启动：
    cd /root/bt-player-new/puresource-btprobe
    /path/to/puresource-playlist/.venv/bin/uvicorn \\
        puresource_btprobe.main:app --host 127.0.0.1 --port 8091

或 systemd（unit 留给部署文档）。
"""
