from __future__ import annotations

from typing import Any

from PySide6.QtCore import QLocale, QSettings, QTranslator

LANGUAGE_KEY = "ui/language"
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "zh_CN")
LANGUAGE_LABELS = {
    "en": "English",
    "zh_CN": "简体中文",
}

_installed_translator: QTranslator | None = None
_installed_locale = DEFAULT_LOCALE

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh_CN": {
        "Language": "语言",
        "Language change will take effect after restart.": "语言切换将在重启后生效。",
        "File": "文件",
        "View": "视图",
        "Tools": "工具",
        "Help": "帮助",
        "Recent Files": "最近文件",
        "No Recent Files": "暂无最近文件",
        "Theme": "主题",
        "Dark": "深色",
        "Light": "浅色",
        "Main Toolbar": "主工具栏",
        "Stretch:": "拉伸：",
        "Interval:": "区间：",
        "Preview:": "预览：",
        "Magnifier:": "放大镜：",
        "Dock / Float": "停靠 / 浮动",
        "Dock to Main Window": "停靠回主窗口",
        "Float": "浮动",
        "Close": "关闭",
        "Frame Layout": "多帧布局",
        "Image Orientation": "图像方向",
        "Open": "打开",
        "Export CSV": "导出 CSV",
        "Export Image...": "导出图像...",
        "Export Raw Image...": "导出原始图像...",
        "Show Header": "显示 Header",
        "Append Frames...": "追加帧...",
        "Close File": "关闭文件",
        "Reopen Last Session": "重新打开上次会话",
        "Quit": "退出",
        "Fit": "适应窗口",
        "Zoom In": "放大",
        "Zoom Out": "缩小",
        "Reset Workspace Layout": "重置工作区布局",
        "Smooth Rendering": "平滑渲染",
        "Cycle View Mode": "切换视图模式",
        "Magnifier": "放大镜",
        "Original (Identity)": "原始 (Identity)",
        "Horizontal Flip": "水平翻转",
        "Vertical Flip": "垂直翻转",
        "Rotate 180°": "旋转 180°",
        "Transpose": "转置",
        "Rotate 90° CW": "旋转 90° CW",
        "Rotate 90° CCW": "旋转 90° CCW",
        "Anti-diagonal Transpose": "反对角转置",
        "Previous Frame": "上一帧",
        "Next Frame": "下一帧",
        "Single Frame View": "单帧显示",
        "Tiled Frames": "多帧平铺",
        "Vertical Frames": "多帧竖排",
        "SEP Extract": "SEP 提取",
        "Rerun SEP Extract": "重新运行 SEP 提取",
        "Markers": "标记",
        "Target Info Fields...": "目标信息字段...",
        "Check for Updates...": "检查更新...",
        "Reopen Session": "重新打开会话",
        "No previous session is available yet.": "当前还没有可重新打开的会话。",
        "Open FITS File(s)": "打开 FITS 文件",
        "Append FITS Frame(s)": "追加 FITS 帧",
        "FITS Files (*.fits *.fit *.fts);;All Files (*)": "FITS 文件 (*.fits *.fit *.fts);;所有文件 (*)",
        "Computing...": "计算中...",
        "Checking for updates...": "正在检查更新...",
        "Calculating background...": "正在计算背景...",
        "Update Available": "发现新版本",
        "A newer version ({latest}) is available.\nCurrent version: {current}\n\nOpen the releases page now?": "发现新版本 ({latest})。\n当前版本：{current}\n\n现在打开发布页面吗？",
        "Check for Updates": "检查更新",
        "Update Check Failed": "检查更新失败",
        "Unable to check for updates.": "无法检查更新。",
        "unknown": "未知",
        "Original Image": "原始图像",
        "Background (BKG)": "背景图 (BKG)",
        "Residual (Original - Background)": "原图 - 背景 (Residual)",
        "No image loaded": "未加载图像",
        "View: {label}": "显示：{label}",
        "Layout: {label}": "布局：{label}",
        "Loading FITS files...": "正在加载 FITS 文件...",
        "Loading FITS {loaded}/{total}: {filename}": "正在加载 FITS {loaded}/{total}: {filename}",
        "Loading FITS {loaded}/{total}...": "正在加载 FITS {loaded}/{total}...",
        "Cancelling FITS load...": "正在取消 FITS 加载...",
        "Cancelling SEP extraction...": "正在取消 SEP 提取...",
        "Error": "错误",
        "Append failed": "追加失败",
        "Open failed": "打开失败",
        "No FITS files were loaded.": "没有加载任何 FITS 文件。",
        "Loaded {success}/{total} FITS files ({failed} failed).": "已加载 {success}/{total} 个 FITS 文件（{failed} 个失败）。",
        "Loaded {count} FITS file.": "已加载 {count} 个 FITS 文件。",
        "Loaded {count} FITS files.": "已加载 {count} 个 FITS 文件。",
        "Drop one or more FITS files (.fits, .fit, .fts).": "请拖入一个或多个 FITS 文件（.fits、.fit、.fts）。",
        "Current source results are outdated; rerun SEP to refresh them.": "当前源结果已过期；请重新运行 SEP 以刷新。",
        "Controls how aggressively AstroView renders preview stages before the full frame.": "控制 AstroView 在完整渲染前预览阶段的渲染积极程度。",
        "No FITS image is currently loaded.": "当前未加载 FITS 图像。",
        "No FITS image loaded.": "当前未加载 FITS 图像。",
        "Results outdated. Press Ctrl+R to rerun SEP.": "结果已过期。按 Ctrl+R 重新运行 SEP。",
        "Rendering Composite View": "正在渲染复合视图",
        "Render failed": "渲染失败",
        "Visible frame previews are shown while the remaining frames finish rendering.": "剩余帧完成渲染前，先显示可见帧预览。",
        "SEP extraction is unavailable while frames are shown in a composite layout.": "复合布局显示多帧时无法运行 SEP 提取。",
        "SEP extraction is running in the background.": "SEP 提取正在后台运行。",
        "SEP extraction is unavailable until a FITS image is loaded.": "加载 FITS 图像后才能运行 SEP 提取。",
        "No Image Loaded": "未加载图像",
        "Drop FITS files here or press Ctrl+O.\nWheel to zoom, drag to pan, and right-drag a ROI to run SEP.": "将 FITS 文件拖到这里，或按 Ctrl+O 打开。\n滚轮缩放、拖动平移，右键拖拽 ROI 以运行 SEP。",
        "Rendering Full Frame": "正在渲染完整帧",
        "Rendering Preview": "正在渲染预览",
        "Preview shown while the full-resolution render finishes.": "完整分辨率渲染完成前先显示预览。",
        "Preparing the first visible render for this frame.": "正在准备此帧的首个可见渲染。",
        "No Sources": "无目标源",
        "Run SEP on a ROI to populate source overlays and the source table.": "在 ROI 上运行 SEP 以填充源覆盖层和源表。",
        "Extracting Sources": "正在提取源",
        "SEP is running in the background for the selected region.": "SEP 正在后台处理所选区域。",
        "No Header": "无 Header",
        "Open a FITS file before viewing header cards.": "查看 Header 前请先打开 FITS 文件。",
        "SEP Unavailable": "SEP 不可用",
        "SEP": "SEP",
        "Selected ROI is empty.": "所选 ROI 为空。",
        "Estimating SEP source count on {width}x{height} ROI...": "正在估算 {width}x{height} ROI 中的 SEP 源数量...",
        "Running SEP extraction on {width}x{height} ROI...": "正在对 {width}x{height} ROI 运行 SEP 提取...",
        "SEP extraction is already running.": "SEP 提取已在运行。",
        "crowded ": "拥挤",
        "SEP: {crowded_hint}field — {count} sources at {sigma}σ ({density}/Mpx), ~{expected} expected at {user_sigma}σ. Continue?": "SEP：在 {sigma}σ 下{crowded_hint}区域检测到 {count} 个源（{density}/Mpx），按 {user_sigma}σ 预计约 {expected} 个。是否继续？",
        "Extracted {count} source from ROI {width}x{height}.": "已从 ROI {width}x{height} 中提取 {count} 个源。",
        "Extracted {count} sources from ROI {width}x{height}.": "已从 ROI {width}x{height} 中提取 {count} 个源。",
        "SEP extraction failed": "SEP 提取失败",
        "SEP extraction cancelled.": "SEP 提取已取消。",
        "No WCS available for coordinate conversion.": "没有可用于坐标转换的 WCS。",
        "WCS conversion failed: {detail}": "WCS 转换失败：{detail}",
        "Export": "导出",
        "No source catalog to export.": "没有可导出的源目录。",
        "Export Catalog": "导出目录",
        "CSV Files (*.csv);;All Files (*)": "CSV 文件 (*.csv);;所有文件 (*)",
        "Exported {count} sources to {path}": "已导出 {count} 个源到 {path}",
        "Export failed": "导出失败",
        "PNG Image (*.png);;PDF Document (*.pdf);;Encapsulated PostScript (*.eps);;FITS Image (*.fits *.fit);;All Files (*)": "PNG 图像 (*.png);;PDF 文档 (*.pdf);;EPS 文档 (*.eps);;FITS 图像 (*.fits *.fit);;所有文件 (*)",
        "Export Image": "导出图像",
        "Export Raw Image": "导出原始图像",
        "Unsupported format: {fmt}": "不支持的格式：{fmt}",
        "Exported image to {path}": "已将图像导出到 {path}",
        "Canvas is not available.": "画布不可用。",
        "No image is currently displayed on the canvas.": "画布上当前没有显示图像。",
        "No FITS data available for the current frame.": "当前帧没有可用的 FITS 数据。",
        "Composite layout does not support direct ROI selection. Switch back to Single Frame View before running SEP.": "复合布局下无法直接框选 ROI。请切回单帧显示后再运行 SEP。",
        "SEP settings changed. Current source results are outdated until rerun.": "SEP 设置已更改。重新运行前，当前源结果已过期。",
        "Cancel": "取消",
        "Continue": "继续",
        "Details": "详情",
        "Pixel: (-, -)": "像素：(-, -)",
        "Value: -": "值：-",
        "RA/Dec: - / -": "RA/Dec：- / -",
        "Zoom: 100%": "缩放：100%",
        "Pixel: ({x}, {y})": "像素：({x}, {y})",
        "Value: {value}": "值：{value}",
        "RA/Dec: {ra} / {dec}": "RA/Dec：{ra} / {dec}",
        "Zoom: {percent}%": "缩放：{percent}%",
        "Frame: {current}/{total}": "帧：{current}/{total}",
        "Source Table": "源表",
        "View:": "视图：",
        "Filter sources or use field:value": "筛选源，或使用 field:value",
        "Field": "字段",
        "Value": "值",
        "Details": "详情",
        "Cutout": "切图",
        "Selected source fields and metrics.": "显示当前所选源的字段和指标。",
        "Source cutout preview and view mode.": "源切图预览与视图模式。",
        "Intensity": "强度",
        "Background": "背景",
        "Residual": "残差",
        "Connected Region": "连通区域",
        "Double-click the cutout to recenter the selected source.": "双击切图可将视图重新居中到当前所选源。",
        "No sources match the current filter.": "当前筛选条件下没有匹配的源。",
        "Showing {shown} / {total} sources": "显示 {shown} / {total} 个源",
        "No source selected": "未选择源",
        "Choose a row to preview its cutout.": "选择一行以预览其切图。",
        "Imported Markers": "导入标记",
        "Radius:": "半径：",
        "Line width:": "线宽：",
        "Choose...": "选择...",
        "Color:": "颜色：",
        "Detected Sources (ROI)": "检测到的源 (ROI)",
        "Add Coordinate": "添加坐标",
        "Pixel (x, y)": "像素 (x, y)",
        "WCS (ra, dec)": "WCS (ra, dec)",
        "Type:": "类型：",
        "X:": "X：",
        "Y:": "Y：",
        "Add": "添加",
        "Add && Apply": "添加并应用",
        "Batch (one per line: x, y):": "批量输入（每行一个：x, y）：",
        "# Pixel: x, y\n512, 512\n100.5, 200.3\n# WCS: ra, dec (degrees)\nw 180.0, 45.0\nw 179.5, 44.8": "# 像素：x, y\n512, 512\n100.5, 200.3\n# WCS：ra, dec（度）\nw 180.0, 45.0\nw 179.5, 44.8",
        "Apply": "应用",
        "Clear": "清空",
        "Line {line_number}: expected two comma-separated values.": "第 {line_number} 行：需要两个以逗号分隔的值。",
        "Line {line_number}: values must be numeric.": "第 {line_number} 行：值必须是数字。",
        "No valid coordinates found.": "未找到有效坐标。",
        "{count} marker(s). Skipped {errors} invalid line(s): {lines}": "{count} 个标记。已跳过 {errors} 行无效输入：{lines}",
        "{count} marker(s)": "{count} 个标记",
        "Cleared.": "已清空。",
        "RA (deg):": "RA (deg)：",
        "Dec (deg):": "Dec (deg)：",
        "Marker Color": "标记颜色",
        "Source Overlay Color": "源覆盖层颜色",
        "Frame Player": "帧播放器",
        "No frames loaded.": "未加载帧。",
        "Frame:": "帧：",
        "FPS:": "FPS：",
        "Play": "播放",
        "Pause": "暂停",
        "Loop": "循环",
        "Bounce": "往返",
        "{count} frame(s) loaded.": "已加载 {count} 帧。",
        "Waiting for preview...": "正在等待预览...",
        "Rendering full frame...": "正在渲染完整帧...",
        "Histogram": "直方图",
        "No histogram": "无直方图",
        "Range: -": "范围：-",
        "Low:": "低：",
        "High:": "高：",
        "Apply Manual Range": "应用手动范围",
        "Use Auto Interval": "使用自动区间",
        "Range: {low:.6f} .. {high:.6f}": "范围：{low:.6f} .. {high:.6f}",
        "Manual range applied.": "已应用手动范围。",
        "High must be greater than low.": "高值必须大于低值。",
        "FITS Header": "FITS Header",
        "Case sensitive": "区分大小写",
        "Search header cards": "搜索 Header 卡片",
        "Matches: {count}": "匹配：{count}",
        " (No matches)": "（无匹配）",
        "Lines: {count}": "行数：{count}",
        "SEP Parameters": "SEP 参数",
        "Reset Defaults": "恢复默认值",
        "Detection threshold": "检测阈值",
        "Detection threshold in background RMS units.": "以背景 RMS 为单位的检测阈值。",
        "Min area": "最小面积",
        "Minimum number of pixels required for detection.": "检测所需的最小像素数量。",
        "Deblend thresholds": "去混叠阈值数",
        "Number of thresholds used during deblending.": "去混叠时使用的阈值数量。",
        "Deblend contrast": "去混叠对比度",
        "Minimum contrast ratio for deblending.": "去混叠的最小对比度比值。",
        "Clean": "清理",
        "Enable SEP cleaning pass.": "启用 SEP 清理步骤。",
        "Background box size": "背景 box 大小",
        "SEP background mesh box size (bw=bh).": "SEP 背景网格 box 大小 (bw=bh)。",
        "Background filter size": "背景滤波大小",
        "SEP background filter size (fw=fh).": "SEP 背景滤波大小 (fw=fh)。",
        "Clean param": "清理参数",
        "Cleaning aggressiveness parameter.": "清理强度参数。",
        "Target Info Fields": "目标信息字段",
        "Choose which fields should be shown for right-drag target extraction results.": "选择右键拖拽目标提取结果中需要显示的字段。",
        "Select at least one field.": "至少选择一个字段。",
        "OK": "确定",
        "No published release or tag information is available yet.": "当前还没有可用的发布或标签信息。",
        "A newer version ({version}) is available.": "发现新版本 ({version})。",
        "You are running the latest version ({version}).": "当前已是最新版本 ({version})。",
        "HDU:": "HDU\uff1a",
        "Scope:": "\u8303\u56f4\uff1a",
        "Regex": "\u6b63\u5219",
        "Previous": "\u4e0a\u4e00\u6761",
        "Next": "\u4e0b\u4e00\u6761",
        "Structured": "\u7ed3\u6784\u5316",
        "Raw": "\u539f\u59cb\u6587\u672c",
        "Any": "\u4efb\u610f",
        "Key": "\u5173\u952e\u5b57",
        "Comment": "\u6ce8\u91ca",
        "Match {current}/{total}": "\u5339\u914d {current}/{total}",
        "Copy Key": "\u590d\u5236\u5173\u952e\u5b57",
        "Copy Value": "\u590d\u5236\u503c",
        "Copy Card": "\u590d\u5236\u6574\u6761\u5361\u7247",
        "Copy All Matching": "\u590d\u5236\u5168\u90e8\u5339\u914d\u9879",
        "HDU {index}: {name}": "HDU {index}: {name}",
        "Bits per pixel for the primary data array.": "\u4e3b\u6570\u636e\u6570\u7ec4\u6bcf\u4e2a\u50cf\u7d20\u7684\u4f4d\u6570\u3002",
        "Linear scaling factor applied to stored pixel values.": "\u5e94\u7528\u5230\u5b58\u50a8\u50cf\u7d20\u503c\u7684\u7ebf\u6027\u7f29\u653e\u56e0\u5b50\u3002",
        "Zero-point offset applied to stored pixel values.": "\u5e94\u7528\u5230\u5b58\u50a8\u50cf\u7d20\u503c\u7684\u96f6\u70b9\u504f\u79fb\u3002",
        "Observation start date and time.": "\u89c2\u6d4b\u5f00\u59cb\u7684\u65e5\u671f\u548c\u65f6\u95f4\u3002",
        "Logical end of the FITS header block.": "FITS header \u5757\u7684\u903b\u8f91\u7ed3\u675f\u6807\u8bb0\u3002",
        "Reference equinox for celestial coordinates.": "\u5929\u7403\u5750\u6807\u53c2\u8003\u7684\u5206\u70b9\u5e74\u4ee3\u3002",
        "Exposure time for the observation, usually in seconds.": "\u8be5\u6b21\u89c2\u6d4b\u7684\u66dd\u5149\u65f6\u95f4\uff0c\u901a\u5e38\u4ee5\u79d2\u4e3a\u5355\u4f4d\u3002",
        "Optical filter used for the exposure.": "\u8be5\u6b21\u66dd\u5149\u4f7f\u7528\u7684\u5149\u5b66\u6ee4\u955c\u3002",
        "Detector gain, typically electrons per ADU.": "\u63a2\u6d4b\u5668\u589e\u76ca\uff0c\u901a\u5e38\u4ee5\u6bcf ADU \u5bf9\u5e94\u7684\u7535\u5b50\u6570\u8868\u793a\u3002",
        "Instrument or camera used to acquire the data.": "\u83b7\u53d6\u8be5\u6570\u636e\u4f7f\u7528\u7684\u4eea\u5668\u6216\u76f8\u673a\u3002",
        "Number of data axes in the image.": "\u56fe\u50cf\u4e2d\u6570\u636e\u8f74\u7684\u6570\u91cf\u3002",
        "Target name or field identifier.": "\u76ee\u6807\u540d\u79f0\u6216\u89c6\u573a\u6807\u8bc6\u3002",
        "Detector read noise, usually in electrons.": "\u63a2\u6d4b\u5668\u8bfb\u51fa\u566a\u58f0\uff0c\u901a\u5e38\u4ee5\u7535\u5b50\u4e3a\u5355\u4f4d\u3002",
        "Marks the file as conforming to the FITS standard.": "\u6807\u8bb0\u8be5\u6587\u4ef6\u7b26\u5408 FITS \u6807\u51c6\u3002",
        "Telescope used to acquire the data.": "\u83b7\u53d6\u8be5\u6570\u636e\u4f7f\u7528\u7684\u671b\u8fdc\u955c\u3002",
        "Coordinate increment per pixel along an axis.": "\u6cbf\u8be5\u8f74\u6bcf\u4e2a\u50cf\u7d20\u5bf9\u5e94\u7684\u5750\u6807\u589e\u91cf\u3002",
        "Reference pixel coordinate for an axis.": "\u8be5\u8f74\u7684\u53c2\u8003\u50cf\u7d20\u5750\u6807\u3002",
        "World-coordinate value at the reference pixel.": "\u53c2\u8003\u50cf\u7d20\u5904\u7684\u4e16\u754c\u5750\u6807\u503c\u3002",
        "Coordinate type and projection for an axis.": "\u8be5\u8f74\u7684\u5750\u6807\u7c7b\u578b\u4e0e\u6295\u5f71\u65b9\u5f0f\u3002",
        "Length of a data axis in pixels.": "\u6570\u636e\u8f74\u7684\u50cf\u7d20\u957f\u5ea6\u3002",
    }
}


def normalize_locale(locale: str | None) -> str:
    if not locale:
        return DEFAULT_LOCALE
    text = str(locale).strip().replace("-", "_")
    if text.lower().startswith("zh"):
        return "zh_CN"
    if text.lower().startswith("en"):
        return "en"
    return DEFAULT_LOCALE


def available_locales() -> tuple[str, ...]:
    return SUPPORTED_LOCALES


def language_display_name(locale: str) -> str:
    return LANGUAGE_LABELS.get(normalize_locale(locale), LANGUAGE_LABELS[DEFAULT_LOCALE])


def system_locale() -> str:
    locale = QLocale.system()
    candidates = [locale.name(), *locale.uiLanguages()]
    for candidate in candidates:
        normalized = normalize_locale(candidate)
        if normalized == "zh_CN":
            return normalized
        if normalized == "en":
            return normalized
    return DEFAULT_LOCALE


def load_preferred_language(settings: QSettings | None = None) -> str:
    settings = settings or QSettings("AstroView", "AstroView")
    stored = settings.value(LANGUAGE_KEY, "", type=str)
    if not stored:
        return system_locale()
    return normalize_locale(stored)


def save_preferred_language(locale: str, settings: QSettings | None = None) -> str:
    settings = settings or QSettings("AstroView", "AstroView")
    normalized = normalize_locale(locale)
    settings.setValue(LANGUAGE_KEY, normalized)
    return normalized


class AstroViewTranslator(QTranslator):
    def __init__(self, locale: str) -> None:
        super().__init__()
        self.locale = normalize_locale(locale)

    def translate(
        self,
        context: str,
        source_text: str,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        del context, disambiguation, n
        if not source_text:
            return ""
        if self.locale == DEFAULT_LOCALE:
            return source_text
        return _TRANSLATIONS.get(self.locale, {}).get(source_text, source_text)


def install_translator(app: Any, locale: str | None = None, settings: QSettings | None = None) -> str:
    global _installed_locale, _installed_translator

    if _installed_translator is not None:
        app.removeTranslator(_installed_translator)
        _installed_translator = None

    resolved = normalize_locale(locale) if locale is not None else load_preferred_language(settings)
    if resolved != DEFAULT_LOCALE:
        translator = AstroViewTranslator(resolved)
        app.installTranslator(translator)
        _installed_translator = translator

    _installed_locale = resolved
    try:
        app.setProperty("astroview.ui_language", resolved)
    except Exception:
        pass
    return resolved


def current_language(app: Any | None = None) -> str:
    if app is not None:
        try:
            value = app.property("astroview.ui_language")
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return normalize_locale(value)
    return _installed_locale


__all__ = [
    "LANGUAGE_KEY",
    "available_locales",
    "current_language",
    "install_translator",
    "language_display_name",
    "load_preferred_language",
    "normalize_locale",
    "save_preferred_language",
    "system_locale",
]
