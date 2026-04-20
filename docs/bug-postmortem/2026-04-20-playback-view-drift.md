# Bug: 多帧播放时图像向右下角漂移

**日期**: 2026-04-20
**严重程度**: 中
**影响范围**: Image Canvas / Frame Player 多帧播放

## 现象

加载多帧 FITS 文件后启动 Frame Player 连续播放。用户观察到画面中的图像会随播放进行缓慢向**右下方**漂移，像素尺度累计可达数十像素，最终可能把感兴趣区域推出可视窗口。手动切帧不容易察觉，只在高速连续播放多帧时明显可见。

一帧一帧手动按前进键（低频率切帧）时，现象不可见或极难察觉；只有 Frame Player 以较高帧率连续播放时才会累积出肉眼可见的偏移。每帧只漂移不到一个像素，量级类似 0.5 px，但经过几十上百帧就会累加。

## 根因分析

`app/main_window.py::_show_current_frame_image` 每次切帧都会执行这样的"视图状态往返"：

1. 调用 `canvas.capture_view_state()` 把当前的 `scale_factor` 和**归一化视口中心** (`center_x, center_y ∈ [0, 1]`) 采集下来。
2. 调用 `canvas.set_image(new_image)`，内部 `setPixmap` + `_update_scene_rect`。
3. 调用 `canvas.restore_view_state(state)`，内部执行 `resetTransform()` → `scale(s, s)` → `centerOn(scene_pt)`。

这套往返的设计目的是在"新旧帧尺寸不同"的场合保持构图。但对于多帧播放这种**帧尺寸恒定**的常见情形，它是完全多余的——因为 `setPixmap` 传入同尺寸 pixmap 时，`QGraphicsView` 的变换与滚动条位置本来就不变。

问题出在：`QGraphicsView::centerOn(QPointF)` 把浮点场景坐标换算成**整数**的水平/垂直滚动条值时存在取整偏差。实验上 Qt 的舍入方向对正方向偏移会导致实际居中点相对目标点系统性地朝正方向偏 ≤1 px。于是：

- 第 N 帧：`capture_view_state` 读到视口中心 = `C_n`（浮点）。
- `centerOn(C_n)` 实际落到滚动条整数位置，视口中心变成 `C_n + δ`（`δ > 0`，沿 x、y 两个方向都略为正）。
- 第 N+1 帧：`capture_view_state` 读到的中心变成 `C_n + δ`，写回后又加一个 `δ`，累积成 `C_n + 2δ`……

由于场景坐标系的 `+x` 向右、`+y` 向下（Qt 默认），这个正向偏差在屏幕上表现为图像看起来向右下角漂移——其实是视口在场景里向右下移动、图像相对静止，但肉眼感受就是"图像飘走了"。

**为什么之前没发现**：
- 单帧模式下 `_show_current_frame_image` 只在 orientation 切换、布局切换等低频路径上触发一次，累积不够显著。
- 多帧测试多为手动点击下一帧，频率远不及连续播放，每次 δ 可能还被鼠标滚动或窗口尺寸变化抵消。
- 当前单元测试覆盖的是 `capture_view_state` / `restore_view_state` 的一次性语义，没有"连续 N 次往返后视口应回到原位"的回归断言。

## 修复方式

在 `_show_current_frame_image` 里新增一个中间层 `_set_canvas_image_preserving_view(image)`：

- 比较新 `QImage` 与当前 `_pixmap_item.pixmap()` 的尺寸。
- **同尺寸**：直接 `canvas.set_image(image)`，**跳过** capture/restore。`setPixmap` 不会改变变换和滚动条，视口保持原位、零取整偏差。
- **尺寸不同**（orientation 切换、单帧↔多帧布局切换、帧尺寸异构等）：走旧的 `capture_view_state` → `set_image` → `restore_view_state` 路径，保证新构图下的大致构图关系。

这样播放路径下不再每帧都产生 δ，漂移彻底消除；而构图发生变化的低频路径继续沿用旧逻辑，不影响既有行为。

## 涉及文件

- `app/main_window.py::_show_current_frame_image` 与新增的 `_set_canvas_image_preserving_view`（~4102–4145 行）
- `CHANGELOG.md` 在 1.6.0 未发布节新增 Fixed 条目

## 经验教训

1. **"先保存再恢复"的视图状态往返隐含浮点↔整数取整，不是零成本操作**。任何只涉及"像素替换、构图不变"的路径都应该**直接替换像素**，不要经过 `resetTransform` + `scale` + `centerOn` 这种会触发滚动条重新计算的组合。
2. **累积性 bug 要靠连续场景暴露**。单元测试里 "一次 capture + restore 基本等价" 是成立的，但 N 次之后的累积偏差没被覆盖。以后涉及视口/变换的修改可以考虑加一条回归测试：对同尺寸 pixmap 做 K 次 set_image，断言最终 scrollbar 位置与初始一致。
3. **Qt 的 `centerOn(QPointF)` 不是 round-trip safe**：`mapToScene(viewport.center())` → `centerOn(pt)` → `mapToScene(viewport.center())` 不保证回到同一浮点 `pt`，取决于滚动条步长与舍入方向。凡是依赖"读出中心→写回中心"的逻辑都要警惕这一点，要么只在构图确实改变时做，要么用更底层的 `horizontalScrollBar().setValue(int)` 手动控制。
4. **热路径代码对"多余的恢复"要保持警觉**。这次的 capture/restore 是为尺寸变化的边界情况写的，但被无条件套用到了所有切帧路径上。原则上：只在"状态确实会被破坏"的前提下才做保护，否则让 Qt 的默认不变性帮我们免费保留状态。
