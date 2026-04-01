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
- 内置 SEP (Source Extractor Python) 作为可选工具
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

### 性能优化
- 内存映射加载 (`memmap=True`)，适用于大文件
- 延迟类型转换，加载时避免不必要的 float32 拷贝
- 大图区间计算采用子采样（步幅缩减至约 1000x1000）
- 帧懒渲染机制，仅渲染当前可见帧

## 环境要求

- Python 3.10+
- PySide6
- astropy
- numpy
- sep（可选，用于源提取）

推荐通过 conda-forge 安装：
```
conda install pyside6 astropy numpy sep
```

## 使用方式

在 `astroview/` 的上级目录运行：

```bash
python -m astroview                     # 启动空白窗口
python -m astroview path/to/image.fits  # 直接打开 FITS 文件
python -m astroview image.fits --hdu 1  # 指定 HDU 打开
```

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

- 项目的初始构思与整体框架由 GPT-5.4 协助梳理。
- 框架代码实现以及大部分功能开发随后由 Claude Opus 4.6 完成。
- 其余实现细节与后续打磨，则由 GPT-5.4 完成。
