# AstroView [English](README.md) | [简体中文](README_CN.md)

基于 PySide6 的桌面端 FITS 天文图像查看器。

## 功能

### 图像显示
- 打开单个或多个 FITS 文件，支持多 HDU 选择
- 拉伸模式：Linear、Log、Asinh、Sqrt
- 区间模式：ZScale、MinMax、99.5%、99%、98%、95%
- 鼠标滚轮缩放，左键拖拽平移
- 适应窗口和原始像素 (100%) 视图切换

### 源提取 (SEP)
- 内置 SEP (Source Extractor Python)
- 支持全图或 ROI（右键拖选区域）源提取
- 可配置提取参数（阈值、最小面积、反混叠等）
- 源椭圆叠加显示，点击高亮
- 源列表表格，支持排序
- 导出源表为 CSV

### 坐标标记
- 在图像上绘制圆形标记
- 支持像素坐标 (x, y) 和 WCS 坐标 (RA, Dec) 输入
- 单坐标添加或批量输入（每行一个）
- 可配置半径、线宽和颜色

### 多帧播放
- 将多个 FITS 文件按顺序组成帧序列
- 支持追加帧到已有序列
- 帧播放器面板：播放/暂停、FPS 调节、循环/往返模式
- 快捷键：`[` 上一帧，`]` 下一帧

### 状态栏
- 实时显示光标下的像素坐标和像素值
- WCS RA/Dec 坐标显示（需图像包含 WCS 信息）
- 当前缩放比例
- 多帧序列的帧计数器

### Header 查看器
- 完整 FITS Header 显示
- 支持关键字搜索过滤

### 性能与安全
- 在解码像素前根据 Header 执行内存与帧数预算
- 必要时将数组与文件映射脱离，确保 Windows 下可安全关闭或覆盖源文件
- 大图区间计算采用子采样（步幅缩减至约 1000x1000）
- 帧懒渲染机制，仅渲染当前可见帧

## 环境要求

- Python 3.10+
- PySide6
- astropy
- numpy
- sep

推荐通过 conda-forge 安装：
```
conda install pyside6 astropy numpy sep
```

`environment.yml` 是便于维护的开发环境约束；Windows 发布构建使用
`environment-win-64.conda.lock`，其中每个直接及传递 Conda 包都固定到具体
URL、build 和 SHA-256。构建脚本会拒绝与锁文件不完全一致的活动环境：

```powershell
conda create -n astroview-release --file environment-win-64.conda.lock
conda activate astroview-release
.\scripts\build_windows.ps1 -CondaLockPath environment-win-64.conda.lock
```

## 使用方式

在仓库根目录运行：

```bash
python -m astroview                     # 启动空白窗口
python -m astroview path/to/image.fits  # 直接打开 FITS 文件
python -m astroview image.fits --hdu 1  # 指定 HDU 打开
```

安装 wheel 或运行 `python -m pip install .` 后，可在任意目录使用
`astroview` 命令启动。

### FITS 资源限制

在 Astropy 实际解码像素前，程序会检查不受信任的 FITS 元数据。桌面加载器默认最多接受
`8192 × 8192` 个总像素、512 MiB 预计解码数据和 4096 帧。使用核心 API 处理可信数据时，
可以显式提高或关闭单项限制。

FITS 内部的分块压缩 (`CompImageHDU`) 仍受支持，并使用相同的解码预算。外层
gzip/ZIP/bzip2/xz/LZW 压缩会在解压前被拒绝；请先在确认展开大小安全后解压。

## 项目结构

- **`core/`** — 领域逻辑层（不依赖 Qt）
  - `fits_data.py` — FITS 加载、WCS、像素采样
  - `fits_service.py` — 渲染管线（拉伸/区间/归一化）
  - `sep_service.py` — SEP 源提取封装
  - `source_catalog.py` — 源表数据模型
  - `contracts.py` — 跨层共享的类型化数据类

- **`app/`** — PySide6 UI 层
  - `main_window.py` — 中心协调器，连接 UI 与服务
  - `canvas.py` — 基于 QGraphicsView 的图像显示与叠加层
  - `sep_panel.py` — SEP 参数表单
  - `source_table.py` — 源表 Dock 面板
  - `marker_dock.py` — 坐标标记输入面板
  - `frame_player_dock.py` — 多帧播放控制面板
  - `header_dialog.py` — FITS Header 查看对话框
  - `status_bar.py` — 光标/缩放/帧状态显示

`MainWindow` 是唯一的协调器 — 视图模块通过信号和 setter 通信，不直接调用服务；服务模块返回领域对象，不操作界面组件。


## 开发说明

- 项目的初始构思与整体架构由 GPT-5.4 协助梳理。
- 框架代码实现以及大部分功能开发随后由 Claude Opus 4.6 完成。
- 其余实现细节、兼容性修复、打包工作与后续打磨则由 GPT-5.4 完成。
- 最近由 GPT-5.4 完成的工作还包括 Windows 打包稳定性修复：定位打包后启动失败问题，恢复 `astropy` 运行所需的 `pydoc` 依赖，将 PyInstaller 的 bootstrap 入口收回仓库内，并验证重建后的 `AstroView.exe` 可以正常启动。
