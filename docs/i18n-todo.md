# i18n TODO — 简体中文 / 英文双语支持

目标：让 AstroView 支持 `zh_CN` 与 `en` 两种界面语言，默认跟随系统 locale，并在菜单里提供切换入口。此文档供接手 agent 执行，不要擅自调整现有业务逻辑。

## 背景 & 约束

- 项目是 PySide6 应用，入口 `astroview/main.py`，UI 集中在 `astroview/app/` 下 9 个主要文件。
- 现状：UI 字符串混杂中英文——`app/main_window.py` 里约 38 处中文硬编码（如 `"单帧显示"` / `"多帧平铺"` / `"显示：{...}"` / `"未加载图像"`），其余 app 模块基本是英文。
- 大约有 **116 处** `setText/setToolTip/setTitle/showMessage/QAction(...)` 等调用需要审计（按文件数量：`main_window.py` 57、`status_bar.py` 17、`source_table.py` 12、`marker_dock.py` 10 等）。
- Qt 有成熟的 i18n 机制 (`QTranslator` + `tr()` + `.ts/.qm`)，但纯 Python 项目也可以用 gettext + 运行时切换。**推荐用 Qt 原生方案**，与 PySide6 生态一致，工具链齐备。
- `core/` 层是纯逻辑，不含 UI 字符串，原则上**不要**改 core；如果 core 里返回了面向用户的错误文案，应改成返回结构化错误码，再由 app 层翻译。

## 推荐方案（Qt 原生）

- 统一用 `self.tr("...")` 包裹所有用户可见字符串（`QAction` 的 text、`setToolTip`、`showMessage`、`QMessageBox`、dock title 等）。
- 源语言用**英文**作为 msgid（中文走翻译表）。这样 `.ts` 文件结构清晰，也方便以后扩展更多语言。
- 翻译文件放在 `astroview/resources/i18n/`，命名 `astroview_en.ts` / `astroview_zh_CN.ts`，编译后生成 `.qm`。
- 运行时根据 `QSettings` 保存的 `ui/language` 读取并加载 `QTranslator`；菜单 `View → Language`（或 `设置 → 语言`）可切换，切换后重建主窗口或提示重启。
- 打包：`.qm` 文件通过 `astroview.spec` 的 `datas` 一并打入 PyInstaller 输出。

## 任务拆分

### 1. 准备基础设施

- [ ] 新建 `astroview/app/i18n.py`：封装 `install_translator(app, locale)` 与 `available_locales()`，从 `QSettings` 读写 `ui/language`；默认 `QLocale.system()` 回退英文。
- [ ] `main.py` 在创建 `QApplication` 之后、构造 `MainWindow` 之前调用 `install_translator`。
- [ ] 在 `astroview/resources/i18n/` 下放空的 `astroview_en.ts`、`astroview_zh_CN.ts` 占位文件（`pylupdate6` 会自动填充）。
- [ ] 在 `pyproject.toml` / `environment.yml` 确认 PySide6 自带的 `pylupdate6`、`lrelease` 可用；`scripts/` 下新增 `build_translations.ps1`（或 `.sh`）完成 `pylupdate → lrelease` 流程。

### 2. 字符串改造（按文件，保持业务逻辑不变）

对每个文件，把所有**面向用户可见**的字符串用 `self.tr("English Source")` 包起来（继承自 `QObject`/`QWidget` 的类直接用 `self.tr`；静态上下文用 `QCoreApplication.translate("Context", "...")`）。

中文硬编码要翻译成英文源串，然后在 `.ts` 里给出中文翻译，**不要**把中文当 msgid。

- [ ] `app/main_window.py`
  - [ ] 57 处 `setText/addAction/showMessage/setWindowTitle/QMessageBox` 调用
  - [ ] 约 38 处中文字面量（含 `_FRAME_LAYOUT_LABELS`、`_VIEW_MODE_BADGE`、`"未加载图像"`、`"显示：{...}"`、`"布局：{...}"` 等）
  - [ ] SEP 相关提示："SEP Extract" / "Rerun SEP Extract" / 预估警告 prompt 文案 / "SEP extraction cancelled."
  - [ ] 更新检查：`"Update Available"` / `"Check for Updates"` 等对话框标题与正文
- [ ] `app/status_bar.py`（17 处）：`"Pixel: (-, -)"`、`"Value: -"`、`"RA/Dec: - / -"`、`"Zoom: 100%"`、`"Frame: X/Y"`、`"Cancel"`、`"Continue"`、`"Details"` 等
- [ ] `app/source_table.py`（12 处）
- [ ] `app/marker_dock.py`（10 处）
- [ ] `app/frame_player_dock.py`（5 处）
- [ ] `app/histogram_dock.py`（5 处）
- [ ] `app/header_dialog.py`（6 处）
- [ ] `app/sep_panel.py`（2 处 + dock 内部 label）
- [ ] `app/catalog_field_dialog.py`（2 处）
- [ ] 检查所有 `QDockWidget` 的 window title（一般在 `main_window.py` dock 装配处）
- [ ] 检查 tab 名称、按钮 label、表头文本（注意 `source_table.py` 的 `COLUMN_NAMES` 等常量——它们是列表头也是持久化 key，翻译时要区分 "显示文案" 和 "内部 key"）

### 3. 注意陷阱

- [ ] **标点符号**：中文 UI 推荐全角冒号/省略号；英文用半角。翻译表里按目标语言风格改。
- [ ] **f-string / .format()**：`f"Zoom: {pct:.0f}%"` 不能直接 `tr()`。改成 `self.tr("Zoom: {pct}%").format(pct=...)` 或 `self.tr("Zoom: %1").arg(...)`，二选一，全项目统一。
- [ ] **多数复数**：英文 `"{n} sources"` 和单数需要 `ngettext` 风格。Qt 用 `tr("%n source(s)", "", n)`。SEP 结果 `"Extracted N sources"` 处要处理单复数。
- [ ] **不可翻译的字符串**：文件后缀 `.fits`、SEP 参数键名、日志文案、异常消息（除非要展示给用户）、`QSettings` key——不要包 `tr()`。
- [ ] **持久化字段**：`COLUMN_NAMES`、`_FRAME_LAYOUT_LABELS` 这类既是展示也是 key 的常量，需要拆成 `key`（稳定）+ `display_name`（翻译），否则切换语言后 session 恢复会对不上。
- [ ] **`core/` 错误消息**：如 `"thresh must be positive, got 0"` 这类从 core 抛出的 ValueError，如果 UI 直接 `show_error(str(exc))`，就会把英文裸抛给中文用户。可选做法：core 抛结构化异常，app 层再翻译；或维持英文（开发者向），在 UI 层尽量避免直接透传。本次任务**先保持 core 不动**，仅在 UI 层包装。
- [ ] **动态字符串拼接**：像 `f"Loading FITS {loaded}/{total}: {filename}"` 翻译后语序可能颠倒，用占位符而不要手动拼接。
- [ ] **版本号/路径**：窗口标题里 `"AstroView 1.6.0 - {path}"` 保持英文，只翻译周围的装饰文字。

### 4. 语言切换 UI

- [ ] `View` 菜单或新建 `Settings / 设置` 菜单里加 `Language` 子菜单，列出 `English` / `简体中文`，`QActionGroup` 单选。
- [ ] 切换后：
  - 写回 `QSettings("ui/language")`。
  - 简单方案：弹窗提示 "Language change will take effect after restart"（需要翻译）。
  - 进阶方案：实时切换——调用 `QCoreApplication.installTranslator` + 重建主窗口，或在所有 widget 上 override `changeEvent(LanguageChange)`。**推荐先做简单方案，后续再优化。**

### 5. 翻译文件与构建

- [ ] 跑 `pylupdate6 app/*.py -ts resources/i18n/astroview_zh_CN.ts resources/i18n/astroview_en.ts` 生成初版。
- [ ] 手工在 `.ts` 里填写中文翻译（可以用 `linguist-pyside6` GUI，或直接编辑 XML）。原有的中文硬编码字面量直接填到对应英文 msgid 的译文里。
- [ ] `lrelease` 编译到 `.qm`。
- [ ] `astroview.spec` 的 `datas` 添加 `('resources/i18n/*.qm', 'resources/i18n')`，确保 PyInstaller 打包进去。
- [ ] `scripts/build_translations.ps1` 一键跑 `pylupdate6 + lrelease`，方便后续维护。

### 6. 测试

- [ ] 新增 `tests/test_i18n.py`：
  - 断言 `install_translator(app, "zh_CN")` 之后 `QCoreApplication.translate` 对某几个代表性字符串返回中文。
  - 断言默认（未配置）情况下返回英文 msgid。
- [ ] 手测 clicklist：
  - 菜单栏全部条目 / 所有 Dock 标题 / 状态栏所有 label / SEP 警告 prompt / 打开/保存对话框 / 更新检查三种结果 / 错误对话框
  - 中英切换后分别操作一轮："open FITS → play multi-frame → SEP extract（触发预估警告）→ export → change layout"
- [ ] 跑 `python -m unittest discover -s tests`，确认既有 180 个测试不因字符串变化 regression（当前有测试断言具体文案，如 `"Running SEP extraction..."` / `"Estimating SEP source count..."`，需要同步更新为 `tr()` 后的英文源串）。

### 7. 文档

- [ ] `README.md` / `README_CN.md` 各加一节说明如何切换语言、如何贡献翻译。
- [ ] `CHANGELOG.md` 在未发布节或下一个版本加 `Added: Bilingual UI (English / 简体中文) with runtime switcher`。

## 验收标准

1. 启动后自动根据系统 locale 选语言；`QSettings` 覆盖系统默认；菜单可手动切换。
2. 所有菜单、dock title、状态栏、对话框、SEP 警告、错误提示在两种语言下都正确显示，无残留硬编码中文/英文。
3. `python -m unittest discover -s tests` 全绿。
4. PyInstaller 打包产物在没有 Python 环境的机器上启动后翻译依然生效。
5. 任何一处字符串改动需要走完 `pylupdate6 → 手工翻译 → lrelease` 流程，文档里写清楚。

## 不在本次任务范围

- `core/` 层字符串（ValueError 消息等）暂不改。
- 除中英外的第三种语言。
- 主题 / RTL 支持。
- `CHANGELOG.md` 历史节的翻译。
