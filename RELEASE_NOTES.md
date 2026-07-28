# AstroView 1.10.0 — Streamlined Interactions and Release Hardening

Release date: **2026-07-28**

AstroView 1.10.0 makes the common viewing and analysis paths more predictable while strengthening the Windows release pipeline.

## Highlights

- Added an always-visible ROI task selector. A normal right-drag now performs exactly one selected action: **Measure ROI** or **Extract Sources in ROI**.
- Reorganized Tools around scientific tasks and grouped layout switches under **View → Panels**. New workspaces start with a clean canvas instead of reopening inactive docks.
- Added empty-canvas double-click opening and placed append-frame loading beside Open.
- Left-drag panning no longer changes the aperture center. Fit, wheel, button, and restored zoom states now share the real bounded canvas transform and show accurate Fit / 1:1 status.

## Architecture and release integrity

- Moved moving-target request identity, stale-result rejection, and worker/QThread lifecycle management into a focused `MovingTargetController`.
- Added fail-closed scripts that prepare and independently verify the exact 253-package Conda release lock, detect unlocked pip replacements, run Conda file-integrity checks, and execute `pip check`.
- Removed the repository parent from PyInstaller import search paths and disabled unpinned UPX processing so sibling worktrees and machine-specific tools cannot alter CI bundles.
- Consolidated active follow-up work in `TODO_NEXT.md` and removed obsolete implementation handoff documents.

## Validation

- Complete source suite: **429 tests passed**.
- Release lock: **253 hash-pinned Conda packages validated**.
- Windows release workflow still performs the locked build, frozen-executable smoke tests, installer generation, checksum verification, and split-permission Release publishing.

## Compatibility notes

- Ordinary right-drag no longer runs ROI statistics and SEP simultaneously. Choose the desired task from the toolbar; the selection is remembered.
- A one-shot moving-target ROI capture still takes precedence over the ordinary ROI task.
- Existing saved workspace layouts continue to restore. The clean-canvas startup applies when no compatible saved layout exists.

## Assets

- `AstroView_Setup_1.10.0.exe` — Windows x64 installer
- `SHA256SUMS.txt` — SHA-256 verification manifest

The Windows executable and installer are **not Authenticode-signed**, so Windows SmartScreen may display a warning. Verify the installer against the `SHA256SUMS.txt` downloaded from this Release before running it.

---

# AstroView 1.10.0 — 简化交互与发布加固

发布日期：**2026-07-28**

AstroView 1.10.0 让常用查看与分析路径更明确，同时进一步加固 Windows 发布流程。

## 重点更新

- 新增始终可见的 ROI 任务选择器。普通右键拖拽现在只执行一个已选任务：**测量 ROI**或**提取 ROI 内源**。
- 将“工具”菜单按科研任务重组，并把布局开关收拢到**视图 → 面板**。全新工作区默认只显示干净画布，不再展开未使用的 Dock。
- 新增双击空画布打开文件，并把追加帧入口放到“打开”旁。
- 左键拖动平移不再改变孔径中心。适应窗口、滚轮、按钮和恢复视图统一使用真实且有界的画布变换，并准确显示 Fit / 1:1 状态。

## 架构与发布完整性

- 将动目标请求身份、过期结果拒绝和 worker/QThread 生命周期移入专用 `MovingTargetController`。
- 新增默认拒绝不一致状态的发布脚本：准备并独立校验包含 253 个包的精确 Conda 锁，检测未锁定的 pip 替换，执行 Conda 文件完整性检查与 `pip check`。
- 从 PyInstaller 导入路径移除仓库父目录，并关闭未固定版本的 UPX，避免兄弟 worktree 或构建机工具改变 CI 产物。
- 将活动后续工作统一收录到 `TODO_NEXT.md`，删除已过时的实现交接文档。

## 验证结果

- 完整源码测试：**429 项全部通过**。
- 发布锁：**253 个带哈希固定的 Conda 包通过校验**。
- Windows 发布工作流继续执行锁定环境构建、冻结程序 smoke test、安装包生成、校验和验证，以及分离权限的 Release 发布。

## 兼容性说明

- 普通右键拖拽不再同时运行 ROI 统计和 SEP。请从工具栏选择所需任务；程序会记住该选择。
- 一次性动目标 ROI 捕获仍优先于普通 ROI 任务。
- 已保存的兼容工作区布局仍会恢复；没有兼容布局时才使用干净画布启动。

## 附件

- `AstroView_Setup_1.10.0.exe` — Windows x64 安装包
- `SHA256SUMS.txt` — SHA-256 校验清单

Windows 可执行文件和安装包**尚未进行 Authenticode 数字签名**，因此 Windows SmartScreen 可能显示警告。运行前请使用同一 Release 下载的 `SHA256SUMS.txt` 核验安装包。
