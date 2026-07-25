# AstroView 1.8.0 — Measurement and Interoperability

Release date: **2026-07-25**

AstroView 1.8.0 extends the fast FITS-viewing workflow with lightweight scientific measurement, sky-catalog context, DS9 Region interchange, and bounded two-frame comparison.

## Highlights

- Added a **Measurement Workbench** for NaN-safe ROI statistics and circular-aperture photometry with annulus background subtraction, robust RMS, net flux, uncertainty, SNR, centroid, FWHM, and peak measurements.
- Added a projected **RA/Dec grid** and cancellable **Gaia DR3** cone search. Radius, result count, and faint G-magnitude limit are configurable; in-frame results appear in both an overlay and a selectable table. Gaia queries require an internet connection.
- Added **DS9 Region** import/export and overlays for `image`, `physical`, `fk5`, and `icrs` coordinates with circle, box, ellipse, polygon, and point shapes. Physical-region pixel values are displayed as image coordinates, and current AstroView ROI and aperture selections can be captured as regions.
- Added **Image Comparison** with frame A/B selection, side-by-side, blink, and A-minus-B difference modes. Direct comparison requires equal image shapes; an optional bounded nearest-neighbour path aligns images with validated 2D WCS onto frame A's grid.

## Safety and performance

- Measurements, WCS grids, DS9 parsing/serialization, catalog responses, and comparison outputs all have explicit resource budgets and reject malformed, non-finite, oversized, or unsupported inputs with readable diagnostics.
- Gaia queries use the fixed ESA HTTPS TAP endpoint, validated numeric-only ADQL, bounded radius and row counts, a 2 MiB response limit, strict CSV parsing, a total timeout, and responsive cancellation.
- Gaia queries and comparison rendering run away from the GUI thread. Cancelled or stale results are ignored, A/B rendering shares one display interval, and WCS grids are bounded and cached.
- Windows release verification now performs staged cold- and warm-start frozen-app smoke tests, cleans up the full smoke-test process tree on timeout, and keeps manual workflow runs as build-only preflights.

## Compatibility notes

- WCS image alignment is intentionally limited to nearest-neighbour resampling on frame A's grid; it is not a general-purpose reprojection or calibration pipeline.
- DS9 interchange supports the coordinate systems and shapes listed above. AstroView does not apply DS9 detector-section transforms to `physical` coordinates; their pixel values are displayed as image coordinates. Unsupported declarations are diagnosed or skipped rather than interpreted implicitly.
- FITS tile compression (`CompImageHDU`) remains supported. Whole-file gzip/ZIP/bzip2/xz/LZW files must be safely decompressed before opening them in AstroView.

## Assets

- `AstroView_Setup_1.8.0.exe` — Windows x64 installer
- `SHA256SUMS.txt` — SHA-256 verification manifest

The Windows installer is **not Authenticode-signed**, so Windows SmartScreen may display a warning. Verify the installer against `SHA256SUMS.txt` downloaded from this release before running it.

---

# AstroView 1.8.0 — 测量与互操作

发布日期：**2026-07-25**

AstroView 1.8.0 在快速查看 FITS 的基础上，增加了轻量科学测量、星表环境信息、DS9 Region 交换以及受资源预算保护的双帧比较。

## 重点更新

- 新增**测量工作台**：提供 NaN 安全的 ROI 统计与圆形孔径测光，包括背景环扣除、稳健 RMS、净流量、不确定度、信噪比、质心、FWHM 和峰值测量。
- 新增投影后的 **RA/Dec 网格**与可取消的 **Gaia DR3** 锥形检索。可设置查询半径、返回数量和 G 星等暗限；图像范围内的结果会同时显示在画布叠加层与可选择表格中。Gaia 查询需要联网。
- 新增 **DS9 Region** 导入、导出与叠加，支持 `image`、`physical`、`fk5`、`icrs` 坐标系以及圆、矩形、椭圆、多边形和点；`physical` Region 的像素值显示时按图像坐标处理，还可将 AstroView 当前 ROI 与测光孔径捕获为 Region。
- 新增**图像比较**：可选择帧 A/B，并使用并排、闪烁或 A−B 差分模式。直接比较要求图像尺寸相同；对于具有可靠二维 WCS 的图像，可选择受限的最近邻对齐，将帧 B 映射到帧 A 网格。

## 安全与性能

- 测量、WCS 网格、DS9 解析/序列化、星表响应和图像比较输出均具有明确资源预算；异常、非有限、超限或不支持的输入会返回可读诊断。
- Gaia 查询仅使用固定的 ESA HTTPS TAP 端点，并采用纯数值校验后的 ADQL、受限半径与行数、2 MiB 响应上限、严格 CSV 解析、总超时和可响应取消机制。
- Gaia 查询与比较渲染在 GUI 线程之外运行；已取消或过期的结果会被忽略，A/B 渲染复用同一显示区间，WCS 网格则受到数量限制并会缓存复用。
- Windows 发布验证现在会分阶段执行冻结程序冷启动与热启动 smoke test，超时后清理完整 smoke-test 进程树，并确保手动工作流只进行预构建而不会发布。

## 兼容性说明

- WCS 图像对齐有意限制为帧 A 网格上的最近邻采样，并非通用重投影或数据定标管线。
- DS9 交换仅支持上面列出的坐标系与形状。AstroView 不会对 `physical` 坐标应用 DS9 探测器分区变换，而是将其像素值按图像坐标显示；不支持的声明会产生诊断或被跳过，不会被隐式解释。
- FITS 内部分块压缩（`CompImageHDU`）仍受支持。整文件 gzip/ZIP/bzip2/xz/LZW 需要先安全解压，再使用 AstroView 打开。

## 附件

- `AstroView_Setup_1.8.0.exe` — Windows x64 安装包
- `SHA256SUMS.txt` — SHA-256 校验清单

Windows 安装包**尚未进行 Authenticode 数字签名**，因此 Windows SmartScreen 可能显示警告。运行前请使用本 Release 下载的 `SHA256SUMS.txt` 核验安装包。
