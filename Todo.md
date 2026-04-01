# AstroView Todo

This file tracks interfaces that are defined but not implemented, plus framework pieces that still need to be added.

## Coordinator Layer

- Implement `MainWindow.open_file()`.
- Implement `MainWindow.close_current_file()`.
- Implement `MainWindow.refresh_image()`.
- Implement `MainWindow.sync_catalog_views()`.
- Implement `MainWindow.build_table_rows()`.
- Implement `MainWindow.export_catalog()`.
- Implement `MainWindow.show_header_dialog()`.
- Implement `MainWindow.handle_roi_selected()`.
- Implement `MainWindow.handle_source_clicked()`.
- Implement `MainWindow.update_status_from_cursor()`.

## Core Layer

- Implement `FITSData.load()` using `astropy.io.fits.open(..., memmap=True)`.
- Implement `FITSData.header_as_text()`.
- Implement `FITSData.pixel_to_world()`.
- Implement `FITSData.sample_pixel()`.
- Implement `FITSService.list_image_hdus()`.
- Implement `FITSService.render()`.
- Implement `FITSService.header_text()`.
- Implement `SEPService.validate_params()`.
- Implement `SEPService.extract()`.
- Implement `SourceCatalog.from_sep_objects()`.
- Implement `SourceCatalog.to_rows()`.
- Implement `SourceCatalog.to_csv()`.

## UI Modules

- Add real overlay item registry to `ImageCanvas` for source markers and highlighted source state.
- Add coordinate mapping helpers to `ImageCanvas` for viewport-to-image conversion.
- Add ROI rubber-band framework to `ImageCanvas`.

- Refine empty-state presentation in `SourceTableDock`.

- Refine empty/error-state presentation in `HeaderDialog`.

- Refine disabled-state presentation in `SEPParamsPanel`.

- Refine label formatting rules in `AppStatusBar`.

## Empty, Error, and Disabled States

- Wire `CanvasImageState.feedback` into canvas presentation.
- Wire `CanvasOverlayState.feedback` into overlay presentation.
- Wire `TableViewState.feedback` into source-table presentation.
- Wire `HeaderViewState.feedback` into header-dialog presentation.
- Wire `SEPPanelState.enablement` and `SEPPanelState.feedback` into panel presentation.
- Wire `RenderControlState.disabled_reason` into toolbar control state.
- Define the exact UI wording and visibility rules for `ready`, `empty`, `disabled`, and `error` statuses.

## Application Bootstrap

- ~~Implement `main.py` QApplication creation and shutdown path.~~ Done.
- ~~Call `MainWindow.initialize()` from `main.py`.~~ Done.
- Decide whether startup file open failures surface as dialog, status message, or both.

## Tests

- Replace placeholder tests with interface-level tests for contract objects.
- Add coordinator tests for `MainWindow` state-builder methods.
- Add catalog row-format tests for `SourceCatalog.to_rows()`.
- Add render-request and enablement-state tests for `FITSService` and `MainWindow`.

## Open Questions

- Decide whether MEF/HDU selection lives in the toolbar, open-file dialog flow, or a separate dialog.
- Decide whether `HeaderDialog` is modal or dockable in the first implementation pass.
- Decide whether `SourceTableDock` uses `QTableWidget` or `QTableView` with a custom model.
- Decide whether canvas feedback is drawn inside the scene or overlaid with a separate placeholder widget.
