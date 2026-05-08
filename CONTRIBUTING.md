# BT-Player 协同开发规范 (AI-AI Collaboration)

## 1. 角色定义
*   **GitHub Copilot (Gemini 3 Flash)**: **架构师 (Architect)**。
    *   职责：输出 `ARCH.md`、定义 Interface/Trait、进行代码收割审计、性能预判。
*   **Cursor**: **工程实现师 (Engineer)**。
    *   职责：根据设计编写具体的 Rust/React 代码、完善错误处理、编写 UI 逻辑。

## 2. 协作流程 (Workflow)
1.  **指令下达**: 用户将 Copilot 的架构指令发送给 Cursor。
2.  **代码实现**: Cursor 完成代码并提交。**如发现架构设计在物理或库层面不可行，Cursor 必须明确标注「需架构确认」，严禁私自修改底层设计逻辑。**
3.  **代码审计**: 用户将 Cursor 的核心代码逻辑反馈给 Copilot 进行 Review。
4.  **架构更新**: 如遇不可抗力技术变动，Copilot 更新 `ARCH.md`，Cursor 重新对齐。

## 3. 提交准则
*   所有代码必须通过 `cargo clippy` 和 `cargo fmt`（由 Cursor 执行）。
*   FFI 代码必须包裹在 `unsafe` 块中且有明确注释（由 Copilot 审计）。
*   UI 组件必须完全响应式并支持经典桌面布局。

---
*创建日期: 2026-02-14*
