from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass(slots=True)
class SourceRecord:
    """Single source record for table and CSV output."""

    source_id: int
    x: float
    y: float
    ra: str = "-"
    dec: str = "-"
    flux: float = 0.0
    peak: float = 0.0
    snr: float = 0.0
    a: float = 0.0
    b: float = 0.0
    theta: float = 0.0
    flag: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceCatalog:
    """Structured source-catalog container skeleton.

    Ownership contract:
    - Produced by `SEPService`.
    - Consumed by `ImageCanvas`, `SourceTableDock`, and CSV export flow.
    """

    records: list[SourceRecord] = field(default_factory=list)

    COLUMN_NAMES = (
        "ID",
        "X",
        "Y",
        "RA",
        "Dec",
        "Flux",
        "Peak",
        "SNR",
        "A",
        "B",
        "Theta",
        "Flag",
    )

    @classmethod
    def from_sep_objects(
        cls,
        objects: Any,
        *,
        x_offset: int = 0,
        y_offset: int = 0,
        wcs: Any = None,
    ) -> "SourceCatalog":
        """Build a catalog from SEP output objects.

        Expected caller: `SEPService.extract()`.
        """

        records: list[SourceRecord] = []
        n = len(objects["x"])
        for i in range(n):
            abs_x = float(objects["x"][i]) + x_offset
            abs_y = float(objects["y"][i]) + y_offset

            ra_str = "-"
            dec_str = "-"
            if wcs is not None:
                try:
                    sky = wcs.pixel_to_world(abs_x, abs_y)
                    ra_str = f"{sky.ra.deg:.6f}"
                    dec_str = f"{sky.dec.deg:.6f}"
                except Exception:
                    pass

            records.append(SourceRecord(
                source_id=i + 1,
                x=round(abs_x, 2),
                y=round(abs_y, 2),
                ra=ra_str,
                dec=dec_str,
                flux=round(float(objects["flux"][i]), 2),
                peak=round(float(objects["peak"][i]), 2),
                a=round(float(objects["a"][i]), 3),
                b=round(float(objects["b"][i]), 3),
                theta=round(float(objects["theta"][i]), 4),
                flag=int(objects["flag"][i]),
            ))
        return cls(records=records)

    def __len__(self) -> int:
        """Return the number of records in the catalog."""

        return len(self.records)

    def __getitem__(self, index: int) -> SourceRecord:
        """Return a record by row index."""

        return self.records[index]

    def __iter__(self) -> Iterator[SourceRecord]:
        """Iterate over all source records."""

        return iter(self.records)

    def append(self, record: SourceRecord) -> None:
        """Append a single source record."""

        self.records.append(record)

    def get(self, index: int) -> SourceRecord | None:
        """Return a record by row index, or `None` if out of range."""

        if 0 <= index < len(self.records):
            return self.records[index]
        return None

    def clear(self) -> None:
        """Remove all source records."""

        self.records.clear()

    def to_rows(self) -> list[dict[str, Any]]:
        """Convert the catalog into table/CSV row dictionaries.

        Expected caller: `SourceTableDock.populate()`.
        """

        return [
            {
                "ID": r.source_id,
                "X": r.x,
                "Y": r.y,
                "RA": r.ra,
                "Dec": r.dec,
                "Flux": r.flux,
                "Peak": r.peak,
                "SNR": round(r.snr, 2),
                "A": r.a,
                "B": r.b,
                "Theta": r.theta,
                "Flag": r.flag,
            }
            for r in self.records
        ]

    def to_csv(self, path: str) -> None:
        """Export the catalog to CSV.

        Expected caller: `MainWindow.export_catalog()`.
        """

        import csv

        rows = self.to_rows()
        if not rows:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(self.COLUMN_NAMES))
            writer.writeheader()
            writer.writerows(rows)
