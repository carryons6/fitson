# Bug: ROI 右键 SEP 提取变慢、取消不即时、取消后退出卡死
**日期**: 2026-04-21
**严重程度**: 高
**影响范围**: ROI 右键 SEP 提取 / 状态栏取消 / 应用退出

## 现象

用户在图像上右键框选 ROI 后运行 SEP，出现了三类连锁问题：

1. 提取明显比之前慢，尤其是普通中小 ROI 也会有额外等待。
2. 点击取消后不会立即停下，状态栏会长时间停留在“Cancelling SEP extraction...”。
3. 如果在取消后立刻关闭应用，主窗口会卡住，看起来像死锁。

## 触发改动

这次交互故障是 **2026-04-20 的提交 `d3d0524`** 引入的。该提交标题是：

`Release 1.7.1 structured header viewer, bilingual UI, SEP cancel, startup boost`

真正触发故障的不是某一行孤立修改，而是这次提交里一整组 SEP 重构叠加后的结果：

- `app/main_window.py`
  从“单次直接提取”改成了“先估算源数量，再决定是否正式提取”的双阶段流程。
- `app/sep_extract_worker.py`
  从单纯的 `QThread` worker 改成了 `QThread + multiprocessing.Process`。
- `core/sep_subprocess.py`
  新增子进程执行路径，把真正的 `sep.extract()` 放到新的 Python 解释器里跑。

也就是说，这个故障是 **v1.7.1 中“SEP cancel + crowded-field estimate + subprocess refactor”这组改动共同触发的回归**。

## 根因分析

### 1. 普通 ROI 也被强制走“预估一次 + 正式提取一次”

`app/main_window.py::_start_sep_extract()` 在 `d3d0524` 中被改成：

1. 先运行一次 `estimate_only=True` 的预估提取。
2. 估算密度/总数。
3. 再决定是否继续启动正式提取。

这本来是为了在拥挤星场上给用户一个“是否继续”的提醒，但实现上变成了 **所有 ROI 默认先跑一遍预估**。  
结果是普通 ROI 也要多付出一次背景建模和一次 `sep.extract()` 的成本，直接把右键后的交互延迟抬高了。

### 2. Windows `spawn` 路径把整块 ROI 数据同步复制进子进程

`app/sep_extract_worker.py` 在该提交里把 worker 改成了：

- 主线程准备 ROI 子数组；
- `QThread` 启动；
- `multiprocessing.get_context("spawn")` 启动子进程；
- 把 `self.data_subarray` 作为进程参数传进去；
- 再通过 `multiprocessing.Queue()` 把结果回传回来。

在 Windows 上，`spawn` 不是 fork，意味着 ROI 数组要经过显式序列化/拷贝。  
而 `app/main_window.py::_prepare_sep_run()` 还会先在 UI 线程里做一次：

`np.ascontiguousarray(source_slice, dtype=...)`

于是一次右键 ROI 至少出现了这些成本：

1. UI 线程先拷贝一份 ROI。
2. 创建子进程。
3. 再把 ROI pickling/传输到子进程。
4. 预估阶段先跑一遍。
5. 正式阶段再重复一遍。

这就是为什么问题表现为“提取明显变慢”，而且不是 SEP 算法本身突然变差，而是 **调度和数据传输路径被放大了**。

### 3. 取消只做了 `terminate()`，但退出路径仍然在 UI 线程同步等待清理

`app/sep_extract_worker.py::cancel()` 在 `d3d0524` 中只是把 `_cancelled` 设为 `True`，然后对活着的子进程执行：

`process.terminate()`

但主窗口关闭时，`app/main_window.py::closeEvent()` 会执行：

`self._cancel_active_sep_extract(wait=True)`

而 `_cancel_active_sep_extract(wait=True)` 又会调用：

`thread.wait()`

这意味着：

1. 用户点击取消后，前台只是发出“请停下”的请求。
2. 真正的清理还要等 worker 线程跑完 `finally`。
3. worker `finally` 里又要处理子进程 `join()`、`kill()`、`close()`。
4. 如果用户此时关闭窗口，UI 线程会在 `closeEvent()` 里同步等这个线程退完。

所以“取消后关闭应用卡死”的本质不是 Qt 退出流程本身坏了，而是 **退出路径把一个本来不够快的 SEP 清理过程搬到了 UI 线程上同步等待**。

### 4. `multiprocessing.Queue` 放大了取消阶段的收尾风险

在 `d3d0524` 的实现里，结果回传依赖 `multiprocessing.Queue`。  
对于“大数组作为进程参数 + 子进程中断 + 主线程等待 worker 结束”这个组合，`Queue` 的 feeder / pipe 收尾会让取消阶段更加脆弱，表现出来就是：

- 取消不够即时；
- 退出时等待时间长；
- 某些时机下像“卡死”。

所以这次交互故障不是单一的“取消按钮没接好”，而是：

**双阶段提取 + UI 线程预拷贝 + Windows spawn 大数组传输 + 关闭时同步等待线程退出**

一起叠加后的结果。

## 和旧实现相比，为什么这次才暴露

在 `d3d0524` 之前：

- SEP 路径是单阶段提取，没有默认多跑一次预估。
- 没有新增 `core/sep_subprocess.py` 这条子进程执行链路。
- 取消/关闭虽然也可能等待后台线程，但没有把“Windows spawn 传大 ROI + Queue 回传”的成本一起叠进去。

所以这次不是旧问题简单放大，而是 **v1.7.1 的 SEP 交互重构引入了新的性能和生命周期问题**。

## 涉及文件

- `app/main_window.py`
  `_start_sep_extract`
  `_prepare_sep_run`
  `_launch_sep_worker`
  `_handle_status_bar_cancel_requested`
  `_cancel_active_sep_extract`
  `closeEvent`
- `app/sep_extract_worker.py`
  `_subprocess_entry`
  `cancel`
  `run`
  `_cleanup_process`
- `core/sep_subprocess.py`
  `run_extraction`

## 修复方向

本次修复采用了三条原则：

1. 普通 ROI 不再默认跑预估阶段，只对足够大的 ROI 保留“先估算再确认”的流程。
2. 不在 UI 线程预先做整块 ROI 的连续内存拷贝。
3. 子进程输入改成共享内存传递，减少 Windows `spawn` 的大数组序列化成本，并缩短取消后的清理等待。

## 经验教训

1. “为了支持取消”引入子进程时，不能只看 `cancel()` 是否存在，还要检查 **关闭窗口时谁在等待谁**。
2. Windows `spawn` 对大 `numpy` 数组非常敏感，只要把整块图像数据当进程参数传，就要默认怀疑启动和取消成本。
3. “预估一次再决定是否继续”这种优化如果没有设置门槛，会把所有正常路径都拖慢。
4. 交互型后台任务需要同时评估三条路径：启动延迟、取消延迟、退出延迟；只优化其中一条通常不够。
