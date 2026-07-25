# AstroView 1.7.5 — Security and Reliability Hardening

AstroView 1.7.5 hardens untrusted FITS handling, background-task lifecycle management, Windows packaging, and the release supply chain.

## Highlights

- Added pre-decode limits of 8192² pixels, 512 MiB decoded data, and 4096 frames, with explicit library overrides for trusted data.
- Rejected whole-file gzip/ZIP/bzip2/xz/LZW wrappers before decompression while retaining bounded FITS tile-compression support.
- Prevented stale load, render, background, SEP, and update callbacks from mutating newer UI state.
- Coalesced FITS loading, frame rendering, and background computation into bounded single-flight workers and removed unsafe `QThread.terminate()` shutdown paths.
- Improved malformed-HDU errors, all-NaN/Inf rendering, preview recovery, source-cutout background retries, and Windows mmap cleanup.
- Hardened release builds with immutable GitHub Actions, a complete URL+SHA Conda lock, verified Miniforge/Inno Setup downloads, tag/version checks, frozen-app smoke tests, and SHA-256 manifests.
- Changed the installer to offer an optional per-user **Open with** entry without replacing the user's default FITS application.

## Compatibility note

FITS tile compression (`CompImageHDU`) remains supported. Whole-file gzip/ZIP/bzip2/xz/LZW files must be safely decompressed before opening them in AstroView.

## Assets

- `AstroView_Setup_1.7.5.exe` — Windows x64 installer
- `SHA256SUMS.txt` — SHA-256 verification manifest

The Windows installer is not Authenticode-signed, so Windows SmartScreen may display a warning.

---

# AstroView 1.7.5 — 安全与稳定性加固

AstroView 1.7.5 对不受信任的 FITS 文件处理、后台任务生命周期、Windows 打包及发布供应链进行了系统加固。

## 重点更新

- 增加 8192² 像素、512 MiB 解码数据和 4096 帧的预解码限制；核心 API 处理可信数据时可显式调整。
- 在解压前拒绝整文件 gzip/ZIP/bzip2/xz/LZW 外层压缩，同时继续支持受限的 FITS 分块压缩。
- 防止过期的加载、渲染、背景、SEP 和更新检查回调修改较新的界面状态。
- 将 FITS 加载、帧渲染和背景计算合并为有界 single-flight worker，并移除不安全的 `QThread.terminate()` 退出路径。
- 改进异常 HDU 错误、全 NaN/Inf 渲染、预览失败恢复、源切图背景重试及 Windows mmap 清理。
- 通过固定 GitHub Actions、完整 URL+SHA Conda 锁、Miniforge/Inno Setup 下载哈希校验、标签/版本检查、冻结程序 smoke test 和 SHA-256 清单加固发布链。
- 安装程序仅提供可选的当前用户 **打开方式** 注册，不再替换用户现有的 FITS 默认应用。

## 兼容性说明

FITS 内部分块压缩（`CompImageHDU`）仍受支持。整文件 gzip/ZIP/bzip2/xz/LZW 文件需要先安全解压，再使用 AstroView 打开。

## 附件

- `AstroView_Setup_1.7.5.exe` — Windows x64 安装包
- `SHA256SUMS.txt` — SHA-256 校验清单

安装包尚未进行 Authenticode 数字签名，因此 Windows SmartScreen 可能显示警告。
