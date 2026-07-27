# AstroView 1.9.0 — Multi-Frame Moving Target Detection

Release date: **2026-07-27**

AstroView 1.9.0 adds a bounded, reviewable workflow for finding obvious linear moving targets in loaded FITS sequences.

## Highlights

- Added a **Moving Targets** dock for sequences containing at least five equal-sized frames. Analyze the full frame or capture a one-shot cross-frame ROI with right-drag.
- Added a validated pipeline combining per-frame SEP extraction, robust stellar translation, registered temporal-median subtraction, static-source masking, constant-velocity track association, and recovery against original SEP centroids.
- Added per-frame red-circle overlays that follow playback and all eight image orientations. The results table shows hits, current position, velocity, speed, and fit RMS; long-form CSV export writes one row per target and frame.
- Added FITS timestamp support with an explicit fixed-cadence fallback. Header times must be finite, unique, strictly increasing, and semantically consistent across the sequence.

## Safety and performance

- SEP-heavy analysis runs in a cancellable spawn subprocess using a file-backed float32 ROI stack. Stale results are rejected by request, context, and dataset identity.
- Windows frozen-child DLL search handles remain alive for the process lifetime, and subprocesses are reaped before temporary memory-mapped data is removed.
- Pure-translation registration rejects too few stellar matches, excessive residual RMS, and reflected border areas outside the common real-pixel footprint.
- Frame, ROI, stack-memory, per-frame and total source, difference-candidate, seed, raw-track, unique-track, and output-track budgets bound worst-case work. Large-radius spatial searches scan actual candidates instead of empty grid cells.

## Validation

- The complete source test suite passes: **407 tests**.
- The validated 15-frame 851363 sequence reproduces the handoff baseline on a 2000 x 2000 ROI: **5 tracks**, **2850 static sources**, difference hits of **13/13/14/15/15**, and SEP centroid recovery in **15/15 frames for every target**.

## Compatibility notes

- Detection is intentionally tuned for obvious, approximately constant-velocity targets after a pure stellar translation. Slow, curved, accelerating, crowded-field, rotated, or scale-changing sequences may be rejected or remain incomplete.
- Velocities are reported in pixels per second. When reliable per-frame FITS times are unavailable, set the sequence cadence explicitly.
- Pixel-space results do not establish astronomical identity; standard WCS is still required for sky-coordinate interpretation.

## Assets

- `AstroView_Setup_1.9.0.exe` — Windows x64 installer
- `SHA256SUMS.txt` — SHA-256 verification manifest

The Windows installer is **not Authenticode-signed**, so Windows SmartScreen may display a warning. Verify the installer against `SHA256SUMS.txt` downloaded from this release before running it.

---

# AstroView 1.9.0 — 多帧动目标检测

发布日期：**2026-07-27**

AstroView 1.9.0 新增了一个受资源预算保护、结果可审查的多帧线性动目标检测流程。

## 重点更新

- 新增**动目标检测**面板，用于至少 5 帧尺寸相同的已加载序列。可分析全幅，也可右键拖拽一次捕获跨帧 ROI。
- 新增经过验证的处理链：逐帧 SEP、恒星场稳健平移配准、配准后时间中值差分、静态源掩膜、恒速轨迹关联，以及回到原始 SEP 星表恢复质心。
- 新增随播放和八种图像方向同步更新的逐帧红圈。结果表显示命中帧、当前位置、速度分量、总速度和拟合 RMS；长表 CSV 按目标和帧各输出一行。
- 新增 FITS 时间戳与显式固定帧间隔支持。Header 时间必须有限、唯一、按当前序列严格递增，并在所有帧中保持一致的时间语义。

## 安全与性能

- SEP 密集分析在可取消的 spawn 子进程中运行，并使用文件映射的 float32 ROI 栈；过期结果会按请求、上下文和数据集身份被拒绝。
- Windows 冻结子进程会在整个进程生命周期内保持 DLL 搜索句柄，并在删除临时内存映射数据前确认子进程已回收。
- 纯平移配准会拒绝恒星匹配过少、残差 RMS 过高，以及所有帧共同真实像素范围之外的反射填充边界。
- 对帧数、ROI、栈内存、逐帧/总源数、差分候选、seed、原始轨迹、唯一轨迹和输出轨迹实施预算；大半径空间搜索仅遍历真实候选，不扫描海量空网格。

## 验证结果

- 完整源码测试通过：**407 项测试**。
- 已验证的 851363 序列在 15 帧、2000 x 2000 ROI 上复现交接基线：**5 条轨迹**、**2850 个静态源**、差分命中数 **13/13/14/15/15**，且每个目标均恢复 **15/15 帧 SEP 质心**。

## 兼容性说明

- 当前检测针对纯恒星平移配准后明显且近似恒速的目标。慢目标、曲线或加速目标、拥挤星场，以及存在旋转或尺度变化的序列可能被拒绝或检测不完整。
- 速度单位为像素/秒。缺少可靠逐帧 FITS 时间时，请明确设置序列帧间隔。
- 像素空间结果不能确认天体身份；转换为天球坐标仍需要标准 WCS。

## 附件

- `AstroView_Setup_1.9.0.exe` — Windows x64 安装包
- `SHA256SUMS.txt` — SHA-256 校验清单

Windows 安装包**尚未进行 Authenticode 数字签名**，因此 Windows SmartScreen 可能显示警告。运行前请使用本 Release 下载的 `SHA256SUMS.txt` 核验安装包。
