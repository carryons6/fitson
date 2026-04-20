# Header Dialog 排版优化 TODO

目标：提升 `app/header_dialog.py` 里 FITS header 查看器的可读性与可操作性。交给接手 agent 实施，**不要改动 `core/` 与业务逻辑**，所有改动限制在 `app/header_dialog.py` 及其直接相关的 contracts/tests 内。

## 当前状态（基于 `app/header_dialog.py`，163 行）

- 用 `QPlainTextEdit` + 等宽字体 + `NoWrap` 显示**原始文本** header，每行一条 card。
- 顶部：`filter_input` (QLineEdit) + `case_sensitive_checkbox` + `result_label` (匹配数) + `line_count_label` (总行数)。
- 顶部状态栏：`feedback_label`（无 header 时显示）。
- 过滤通过 `HeaderFilterState.query` + 大小写开关实现，纯文本子串匹配；过滤后直接把结果 `setPlainText` 替换整个视图。
- 状态通过 `HeaderFilterState` / `HeaderViewState` / `ViewFeedbackState`（`app/contracts` 里定义）在 `MainWindow` 侧持久化。
- 已经做过 i18n（所有用户可见字符串都被 `self.tr(...)` 包裹）。

### 已知限制

1. **无结构化展示**：`KEY = VALUE / COMMENT` 作为一整行渲染，列不对齐（80 字符 FITS 卡格式虽然固定，但 HIERARCH、CONTINUE、长 COMMENT 会破坏对齐）。
2. **无卡片类型区分**：COMMENT / HISTORY / HIERARCH / CONTINUE / BLANK 与普通 keyword 视觉无差。
3. **多 HDU**：当前 dialog 只接收一段文本，`MainWindow` 只推送 primary HDU 的 header；多 HDU 文件看不到后续 extension header。
4. **过滤即替换**：找不到关键字时直接只剩匹配行，失去上下文；且没有"下一个/上一个"跳转。
5. **不支持 regex** 或按 key/value/comment 分字段匹配。
6. **无复制动作**：无法单独复制 key 或 value；只能靠文本选中。
7. **UI 状态不持久**：列宽、上次选中的 HDU、过滤字段等切换文件后不保留。
8. **无 tooltip/帮助**：标准 FITS keyword（如 `NAXIS`, `BSCALE`, `CTYPE1`）缺少简短说明。

## 推荐方案

改造为**结构化表格视图 + 原始文本视图**的可切换呈现。默认用表格，保留 raw 文本作为 fallback/导出。

- **表格视图**：`QTableView` + 自定义 `QAbstractTableModel`，列：`#` | `Key` | `Value` | `Comment`。
  - 支持列宽用户调整并通过 `QSettings("header_dialog/column_widths")` 持久化。
  - HIERARCH / CONTINUE / COMMENT / HISTORY 行用轻度背景色或前缀 badge 区分（颜色需走 palette，兼容深色主题）。
  - 单元格右键：Copy Key / Copy Value / Copy Card。
  - 双击 Key 跳到对应原始行（在 raw 视图中定位）。
- **Raw 文本视图**：保留现有 `QPlainTextEdit`，作为 Tab 的第二页。
- **多 HDU 切换**：顶部加一个 `QComboBox` 列出 HDU（name + type + shape）。需要在 `MainWindow` 传入 `list[HeaderPayload]`，每个 payload 带 `hdu_index / name / header_text`（**必须**通过新的 contracts 字段，不改 core）。
- **增强搜索**：
  - 增加 `Scope: Key / Value / Comment / Any` 下拉。
  - 可选 `Regex` 勾选。
  - 匹配后**不再删除非匹配行**，改为：表格 filter proxy（`QSortFilterProxyModel`）+ "Next / Prev" 按钮高亮跳转；raw 视图用 `QTextCursor` 高亮所有匹配并支持跳转。
  - `Match {n}/{total}` 而不是只有总数。

## 任务拆分

### 1. Contracts 扩展（非 core）

- [ ] 在 `app/contracts.py`（或 header_dialog 所在层）新增：
  - `HeaderCard(index: int, key: str, value: str, comment: str, kind: Literal["keyword","comment","history","hierarch","continue","blank"])`
  - `HeaderPayload(hdu_index: int, name: str, kind: str, shape: tuple[int,...] | None, cards: list[HeaderCard], raw_text: str)`
  - 扩展 `HeaderFilterState`：`scope: Literal["any","key","value","comment"] = "any"`, `use_regex: bool = False`, `current_match: int = 0`
  - 扩展 `HeaderViewState`：`hdu_index: int = 0`, `available_hdus: list[tuple[int,str]] = []`, `view_mode: Literal["structured","raw"] = "structured"`

### 2. 解析层（视图内部，非 core）

- [ ] 在 `app/header_parser.py` 新建 `parse_header_text(text: str) -> list[HeaderCard]`。
  - 输入为 `astropy.io.fits.Header.tostring()` 拆行后文本（现状就是这种）。
  - 正则切分 `KEY = VALUE / COMMENT`，兼容：COMMENT/HISTORY/HIERARCH(`HIERARCH a b c = v`)/CONTINUE(`CONTINUE '...'`)/BLANK。
  - 对 CONTINUE，向前合并到上一行的 value+comment（保留 raw）。
  - 纯字符串处理，不引入 astropy 依赖（表格展示不需要类型信息）。

### 3. `MainWindow` 侧数据供给

- [ ] 在打开 FITS 时遍历 `HDUList`，生成 `list[HeaderPayload]` 推给 dialog（走已有的 `header_service` / service 层，新增方法返回结构化数据；如果没有 service 则在 `MainWindow` 里就地组装，保持 `core/` 不动）。
- [ ] `show_header` 接受 payload list + 当前 HDU index。

### 4. Dialog 改造

- [ ] 重写 `HeaderDialog.__init__` 布局：
  ```
  [HDU: QComboBox]  [View: Structured | Raw]
  [Search QLineEdit] [Scope] [Case] [Regex] [Prev] [Next]
  [Match 3/42]  [Lines: 128]
  [ QTableView (structured) / QPlainTextEdit (raw) — QStackedWidget 切换 ]
  [feedback_label]
  ```
- [ ] 新建 `HeaderTableModel(QAbstractTableModel)`：列 `Index / Key / Value / Comment`；`data()` 根据 `kind` 返回不同 `BackgroundRole` 颜色；`flags()` 只读可选中。
- [ ] 用 `QSortFilterProxyModel` 子类实现 scope + regex 过滤。
- [ ] Raw 视图复用现有 `QPlainTextEdit`；搜索改用 `QTextCursor` + 高亮 `ExtraSelection`，不再 `setPlainText` 替换内容。
- [ ] 右键菜单：Copy Key / Copy Value / Copy Card / Copy All Matching。
- [ ] Key 单元格 `ToolTip`：内置一张小的标准 keyword 字典（`NAXIS`, `NAXIS1`, `BITPIX`, `BSCALE`, `BZERO`, `CTYPE*`, `CRVAL*`, `CRPIX*`, `CDELT*`, `EQUINOX`, `DATE-OBS`, `EXPTIME`, `OBJECT`, `TELESCOP`, `INSTRUME`, `FILTER`, `GAIN`, `RDNOISE`, ~30 条）。放 `app/fits_keyword_docs.py` 独立文件。

### 5. 状态持久化

- [ ] `QSettings` 存/取：`header_dialog/column_widths`、`header_dialog/view_mode`、`header_dialog/filter/scope`、`header_dialog/filter/case_sensitive`、`header_dialog/filter/use_regex`。
- [ ] 关闭 dialog 时保存，打开时恢复。
- [ ] 文件切换不要清空搜索字段（便于跨文件查同一个 key）——但要重置 `current_match`。

### 6. i18n 对齐

- [ ] 所有新增 UI 字符串走 `self.tr("...")`，英文作为 msgid。
- [ ] 更新 `resources/i18n/astroview_zh_CN.ts`、`astroview_en.ts` 并 `lrelease`（或在 TODO 里标记给 i18n agent 同步）。
- [ ] 注意 `Match {current}/{total}` 这类用 `.format()`，和已有 i18n 风格一致。

### 7. 测试

- [ ] `tests/test_header_dialog.py`（如不存在则创建）：
  - `parse_header_text` 各 card kind 覆盖 + CONTINUE 合并。
  - 过滤：scope=key 时不应匹配 value 内容；regex 正确；case toggle 行为。
  - Next/Prev 循环正确。
  - 多 HDU 切换后 model 刷新、搜索状态保留。
  - 右键复制动作把正确文本送入 clipboard（`QGuiApplication.clipboard()` mock）。
- [ ] 跑 `python -m unittest discover -s tests` 保持全绿；若 `test_main_window_loading.py` 有对 `show_header` 签名的断言需同步更新。

### 8. 文档

- [ ] `CHANGELOG.md` 未发布节添加 `Added: Structured FITS header viewer with per-HDU switcher, scoped/regex search, and copy actions`。
- [ ] 如果改动 `MainWindow` 与 header 交互方式，更新 `README` / `README_CN` 中对应截图或段落（若有）。

## 陷阱与注意

- **CONTINUE 卡**：FITS 标准允许字符串值跨多行，`'...&' CONTINUE '...'` 要合并 value。合并后 raw 视图仍保留原始多行，structured 视图展示合并后的完整 value。
- **HIERARCH**：`HIERARCH ESO DET WIN1 NX = ...`，key 里可能有空格。按 `=` 之前整段做 key，不要 naïve split(" ")。
- **空值**：`KEY     =                      / only a comment` 的 value 是 undefined，展示为空即可，不要写 `None`。
- **80 列限制**：长 comment 会被 astropy 自动折行为 COMMENT 续行。解析时合并续行以提升可读性。
- **性能**：个别 FITS 文件 header 可达几千卡（pipeline 产物）；用 `QAbstractTableModel` + proxy 过滤而不是每次全量 rebuild。
- **深色主题**：不要硬编码颜色；用 `QPalette` + 适度的 alpha 叠加。
- **多语言排版**：中文全角标点与英文半角不一致——`tr()` 由翻译表决定，不要在代码里手动拼中文标点。
- **不要改 `core/`**：parser 放 `app/`，走纯字符串；确实需要结构化时用 astropy 的只在 `core/fits_data.py` 的 load 流程里（当前任务里**不做** core 改动）。
- **线程**：header 解析在 UI 线程同步做即可（几千卡 <10ms）；**不要**为此引入 worker。

## 验收标准

1. 结构化视图列对齐、HIERARCH/COMMENT/HISTORY/CONTINUE 可视化区分清晰。
2. 多 HDU 文件可以在 dialog 内切换 HDU 并看到对应 header。
3. 搜索支持 scope + regex + 上/下一条跳转；不会把非匹配行删除。
4. 右键可复制 key / value / 整条 card。
5. 列宽、视图模式、搜索选项跨会话保留。
6. 原 180+ 个测试全绿，新增测试覆盖 parser 与 filter/regex/scope。
7. 中英两种语言下所有新增文案都正确翻译，无残留硬编码。

## 不在本次任务范围

- FITS header **编辑**（只读视图）。
- 导出 header 为其它格式（保留以后再做）。
- 跨文件 header diff。
- `core/fits_data.py` 的任何改动。
