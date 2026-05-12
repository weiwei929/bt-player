# BT-Player Documentation Index

This directory separates current VPS work from historical local/WSL notes and design-stage exploration.

## Directory Map

- `vps/`: current VPS baseline, deployment notes, and Phase 1 route evaluation.
- `design/`: design discussions, PureSource/Hermes/browser-parser concepts, and implementation guidance drafts.
- `design/cases/`: scenario walkthroughs used to stress-test the design.
- `history/`: old Windows, WSL, Tauri, environment, smoke-test, and cleanup records.

## Current Source Of Truth

The active product line is the VPS version of BT-Player. New implementation decisions should start from:

1. `README.md`
2. `docs/vps/BT-Player VPS Phase 0 验收记录.md`
3. `docs/vps/BT-Player Phase 1 路线论证.md`
4. `deploy/README.md`

Files with `.legacy.md` were copied from the old `D:\workspace\media\BT-player` working area. They are preserved for context and comparison, not as direct instructions for the current repo.

## Historical Boundary

The old Windows/Tauri and WSL local development line is closed. Documents under `history/` can explain past decisions and failures, but should not override the VPS-first direction unless a future review explicitly reopens that path.
