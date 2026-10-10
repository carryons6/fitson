# AstroView 1.11.0 — Smaller Previews and Reliable Task State

Release date: **2026-10-10**

AstroView 1.11.0 reduces preview texture storage and separates frame state, background tasks and canvas layers while preserving scientific image coordinates.

## Highlights

- Large-image previews now remain at their sampled resolution. The canvas, magnifier and exports retain the original image extent, including cropped edge blocks after flips and transposes.
- Preview and full-resolution images share one resolved brightness mapping. Replacing a preview preserves zoom and pan, and late loading results cannot restore outdated stretch or interval settings.
- Histogram ranges and counts follow the displayed original, background or residual data. Visible histograms refresh when the active render changes, while manual range handles retain their anchored chart extent.
- SEP cancellation feedback finishes correctly when the worker has already stopped, without leaving a permanent cancelling indicator.
- Light and dark theme arrows are packaged resources; startup uses the compact multi-resolution application icon.

## Architecture and compatibility

- `FrameSession` owns each frame's scientific data, display texture and derived caches together.
- File loading, SEP extraction and image comparison use dedicated controllers with shared cancellation, stale-result rejection and worker-retirement rules.
- Pure coordinate transforms and dedicated canvas layers make scientific coordinates independent of preview texture size.
- Existing FITS decoding and scientific-workflow resource limits remain in place. The application continues to use Python, PySide6, Astropy and SEP; this release does not introduce a session-file format or new scientific algorithms.

## Performance scope

A synthetic 4096 × 4096 image displayed with a 1024-pixel preview dimension returns a **1 MiB preview texture instead of 16 MiB**. This compares sampled and expanded preview APIs using the same display mapping. It measures returned texture storage, **not total application memory or process RSS**, and excludes FITS decoding, WCS construction and Qt painting. Real observation sequences still need end-to-end profiling.

## Validation and release integrity

- All **504 source tests** passed in the locked Windows release environment.
- Regression coverage includes queued-result cancellation, delayed thread cleanup, all eight image orientations, odd-sized previews, viewport preservation, exports and render-cache consistency.
- The Windows build verifies the exact Conda release lock, runs source tests and checks the frozen executable before generating the installer. Cold and warm smoke-test timings are recorded as build diagnostics.
- Frozen smoke tests decode the application icon and run the real moving-target subprocess pipeline against a deterministic synthetic sequence, checking the recovered trajectory and worker completion.
- The release workflow verifies that the Git tag matches `VERSION` and checks the installer checksum before publishing. Use the source attached to tag **`v1.11.0`** and the installer and checksum manifest from this same Release.

## Assets

- `AstroView_Setup_1.11.0.exe` — Windows x64 installer
- `SHA256SUMS.txt` — SHA-256 verification manifest for that installer
- Source archives — the `v1.11.0` tag linked by this Release

The Windows executable and installer are **not Authenticode-signed**, so Windows SmartScreen may display a warning. Verify the installer against the `SHA256SUMS.txt` downloaded from this Release before running it.

---

# AstroView 1.11.0 — 更小的预览纹理与可靠的任务状态

发布日期：**2026-10-10**

AstroView 1.11.0 降低预览纹理占用，将帧状态、后台任务与画布叠加层分别管理，同时保留科学图像的原始坐标。

## 重点更新

- 大图预览保持采样后的低分辨率。画布、放大镜和导出仍使用原图尺寸，翻转与转置后也能正确裁剪边缘的采样块。
- 预览和完整图像共用同一组已解析的亮度映射。预览被完整图像替换时保留缩放与平移，延迟到达的加载结果不会恢复旧的拉伸或显示区间设置。
- 直方图范围和计数对应实际显示的原图、背景或残差数据。当前帧渲染结果变化时刷新可见直方图，手动区间拖动仍保持图表范围稳定。
- 修复 SEP worker 已停止后仍永久显示“正在取消”的反馈问题。
- 明暗主题箭头改为随程序打包的资源；启动时使用紧凑的多分辨率应用图标。

## 架构与兼容性

- `FrameSession` 统一持有每帧科学数据、显示纹理和派生缓存。
- 文件加载、SEP 提取与图像比较使用专用控制器，共享取消、过期结果拒绝及 worker 退出规则。
- 独立的坐标变换与画布叠加层使科学坐标不再依赖预览纹理尺寸。
- 保留现有 FITS 解码与科学工作流资源限制。继续使用 Python、PySide6、Astropy 和 SEP；本版不新增会话文件格式或科学算法。

## 性能数据的适用范围

在合成的 4096 × 4096 图像上，将预览最大边长设为 1024 后，返回的预览纹理由 **16 MiB 降至 1 MiB**。这项比较使用同一显示映射，比较保留采样纹理与将其展开为原图大小两种 API。它反映的是返回纹理的存储量，**不是应用总内存或进程 RSS**，也不包含 FITS 解码、WCS 构建或 Qt 绘制。真实观测序列仍需进行端到端性能分析。

## 验证与发布完整性

- 在锁定的 Windows 发布环境中，**504 项源码测试全部通过**。
- 回归测试覆盖排队结果的取消、延迟线程清理、八种图像方向、奇数尺寸预览、视口保持、导出及渲染缓存一致性。
- Windows 构建流程校验精确的 Conda 发布锁，运行源码测试，并在生成安装包前检查冻结程序；冷启动与热启动 smoke test 耗时写入构建诊断。
- 冻结程序 smoke test 实际解码应用图标，并对确定性的合成序列运行真实动目标子进程流程，验证恢复的轨迹与 worker 完成状态。
- 发布工作流检查 Git 标签与 `VERSION` 一致，并在发布前核验安装包校验和。请使用本次 Release 的 **`v1.11.0`** 标签源码，以及同一 Release 的安装包和校验清单。

## 附件

- `AstroView_Setup_1.11.0.exe` — Windows x64 安装包
- `SHA256SUMS.txt` — 对应安装包的 SHA-256 校验清单
- 源码压缩包 — 本次 Release 关联的 `v1.11.0` 标签

Windows 可执行文件和安装包**尚未进行 Authenticode 数字签名**，因此 Windows SmartScreen 可能显示警告。运行前请使用同一 Release 下载的 `SHA256SUMS.txt` 核验安装包。
