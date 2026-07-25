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

### 测量工作台
- 每次右键拖选 ROI 后显示有限值/无效值像素数、最小值、最大值、均值、中位数、标准差和总和
- 带可配置背景环的圆形孔径测光
- 显示扣除背景后的净流量、稳健背景 RMS、不确定度、信噪比、质心、FWHM 和峰值
- 单击图像可设置孔径中心，ROI 与孔径范围会保留为画布叠加层
- 自动排除 NaN/Inf，并使用可配置像素预算限制采样区域

### WCS 与 Gaia DR3
- 对包含天球 WCS 的图像绘制带六十进制标签的 RA/Dec 投影网格
- 通过固定的 ESA HTTPS TAP 服务执行可取消的 Gaia DR3 锥形检索；使用此功能需要联网
- 可配置查询半径、最大返回数量和 G 星等暗限
- 图像范围内的 Gaia 源会同时显示为可选择的画布叠加与表格行
- 网格几何、星表响应大小、返回行数、查询半径和查询时长均受预算限制

### DS9 Region 交换
- 导入和导出 DS9 `.reg` 文件，不执行命令，也不加载外部资源
- 支持 `image`、`physical`、`fk5`、`icrs` 坐标系以及圆、矩形、椭圆、多边形和点；`physical` Region 的像素值显示时按图像坐标处理
- 提供 Region 表格、显隐开关、导入警告摘要，以及随图像方向变换的画布叠加；解析结果会为 API 调用方保留逐行诊断
- 可将 AstroView 当前 ROI 或测光孔径捕获到活动 Region 文档
- 解析与序列化均限制文件大小、行数、Region 数、顶点数、属性数和数值范围

### 图像比较
- 从已加载帧中选择任意两帧作为 A 和 B
- 支持并排、定时闪烁和 A−B 差分
- 相同尺寸图像可直接逐像素比较；也可将具有可靠二维 WCS 的图像受限地用最近邻方式对齐到帧 A 网格
- A/B 显示渲染复用同一显示区间，便于公平比较亮度差异
- 比较准备在可取消的后台 worker 中执行，并会拒绝过期结果

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
- 测量、图像比较、WCS 网格、Gaia 响应和 DS9 Region 交换分别执行专项资源预算
- Gaia 查询与比较渲染在 GUI 线程之外运行，并忽略已取消或过期的结果
- WCS 网格按需生成、限制复杂度并缓存复用
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

### Windows 发布安装包

请从 [GitHub Releases 页面](https://github.com/carryons6/fitson/releases) 下载
`AstroView_Setup_1.8.0.exe` 与 `SHA256SUMS.txt`。Windows 安装包**尚未进行
Authenticode 数字签名**，因此 Windows SmartScreen 可能显示警告。运行前请使用
Release 中的校验清单核验安装包。

## 项目结构

- **`core/`** — 领域逻辑层（不依赖 Qt）
  - `fits_data.py` — FITS 加载、WCS、像素采样
  - `fits_service.py` — 渲染管线（拉伸/区间/归一化）
  - `measurement_service.py` — 受限 ROI 统计与孔径测光
  - `wcs_grid.py` — 受限 RA/Dec 网格投影
  - `catalog_service.py` — 经校验的 Gaia DR3 TAP 查询与响应解析
  - `ds9_regions.py` — 安全 DS9 Region 解析与序列化
  - `image_comparison.py` — 受限像素/WCS 比较与差分输出
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
  - `measurement_dock.py` — ROI 统计与孔径测光面板
  - `catalog_overlay_dock.py` — WCS 网格与 Gaia 查询面板
  - `ds9_region_dock.py` — DS9 Region 导入、导出与文档面板
  - `comparison_dock.py` — 帧 A/B 比较与闪烁控制面板
  - `header_dialog.py` — FITS Header 查看对话框
  - `status_bar.py` — 光标/缩放/帧状态显示

`MainWindow` 是唯一的协调器 — 视图模块通过信号和 setter 通信，不直接调用服务；服务模块返回领域对象，不操作界面组件。


## 开发说明

- 项目的初始构思与整体架构由 GPT-5.4 协助梳理。
- 框架代码实现以及大部分功能开发随后由 Claude Opus 4.6 完成。
- 其余实现细节、兼容性修复、打包工作与后续打磨则由 GPT-5.4 完成。
- 最近由 GPT-5.4 完成的工作还包括 Windows 打包稳定性修复：定位打包后启动失败问题，恢复 `astropy` 运行所需的 `pydoc` 依赖，将 PyInstaller 的 bootstrap 入口收回仓库内，并验证重建后的 `AstroView.exe` 可以正常启动。
