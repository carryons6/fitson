from __future__ import annotations

import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.ds9_regions import (
    DS9Attribute,
    DS9Region,
    DS9RegionDocument,
    DS9RegionError,
    DS9RegionIOError,
    DS9RegionLimitError,
    DS9RegionLimits,
    DS9RegionSyntaxError,
    parse_ds9_regions,
    read_ds9_region_file,
    serialize_ds9_regions,
    write_ds9_region_file,
)


class TestDS9RegionParsing(unittest.TestCase):
    def test_parses_supported_pixel_shapes_and_common_attributes(self) -> None:
        document = parse_ds9_regions(
            """# Region file format: DS9 version 4.1
global color=green width=2 font={helvetica 10 normal roman}
image
circle(10,20,3) # color=#ff00aa text={star # 1} tag={science}
box(30,40,8,6,45)
-ellipse(50,60,4,2,10)
polygon(1,2,3,4,5,6)
point(7,8) # point=cross 9 label={target}
physical; box(100,200,20,30)
"""
        )

        self.assertEqual(document.diagnostics, ())
        self.assertEqual(len(document.regions), 6)
        self.assertEqual(document.global_attributes[0], DS9Attribute("color", "green"))
        self.assertEqual(document.global_attributes[2].value, "helvetica 10 normal roman")
        circle = document.regions[0]
        self.assertEqual(circle.coordinate_system, "image")
        self.assertEqual(circle.shape, "circle")
        self.assertEqual(circle.parameters, (10.0, 20.0, 3.0))
        self.assertEqual(circle.color, "#ff00aa")
        self.assertEqual(circle.label, "star # 1")
        self.assertEqual(circle.attribute_values("tag"), ("science",))
        self.assertFalse(document.regions[2].include)
        self.assertEqual(document.regions[-1].coordinate_system, "physical")
        self.assertEqual(document.regions[-1].parameters, (100.0, 200.0, 20.0, 30.0))

    def test_parses_fk5_icrs_sexagesimal_and_angular_units(self) -> None:
        document = parse_ds9_regions(
            """fk5
circle(12:00:00,-30:00:00,30\")
icrs; ellipse(15d,20d,2',30\",1.5707963267948966r)
"""
        )

        self.assertEqual(document.diagnostics, ())
        circle, ellipse = document.regions
        self.assertEqual(circle.parameters[:2], (180.0, -30.0))
        self.assertAlmostEqual(circle.parameters[2], 30.0 / 3600.0)
        self.assertEqual(ellipse.coordinate_system, "icrs")
        self.assertAlmostEqual(ellipse.parameters[2], 2.0 / 60.0)
        self.assertAlmostEqual(ellipse.parameters[3], 30.0 / 3600.0)
        self.assertAlmostEqual(ellipse.parameters[4], 90.0)

    def test_angular_quote_units_do_not_hide_trailing_attributes(self) -> None:
        document = parse_ds9_regions(
            """global color= #00ff00 width=2
fk5; circle(12:00:00,-30:00:00,30\") # text={thirty arcseconds}
icrs; ellipse(180,20,2',30\",45) # color=#abcdef label={quoted sizes}
"""
        )

        self.assertEqual(document.diagnostics, ())
        self.assertEqual(document.global_attributes[0], DS9Attribute("color", "#00ff00"))
        self.assertEqual(document.regions[0].label, "thirty arcseconds")
        self.assertEqual(document.regions[1].label, "quoted sizes")
        self.assertEqual(document.regions[1].color, "#abcdef")

    def test_unsupported_system_and_dangerous_attributes_are_skipped(self) -> None:
        document = parse_ds9_regions(
            """image
circle(1,2,3) # color=red command={run malware} callback={file:///tmp/x} text={safe}
galactic
point(10,20)
image
point(30,40)
"""
        )

        self.assertEqual(len(document.regions), 2)
        self.assertEqual(document.regions[0].label, "safe")
        self.assertEqual(
            tuple(item.name for item in document.regions[0].attributes),
            ("color", "text"),
        )
        codes = [item.code for item in document.diagnostics]
        self.assertEqual(codes.count("unsupported-attribute"), 2)
        self.assertIn("unsupported-coordinate-system", codes)
        self.assertIn("shape-in-unsupported-system", codes)

    def test_malformed_and_non_finite_records_have_line_diagnostics(self) -> None:
        source = """image
circle(1,2)
box(1,2,3,4,not-a-number)
circle(1e9999,2,3)
polygon(1,2,3,4)
point(5,6)
"""
        document = parse_ds9_regions(source)

        self.assertEqual(len(document.regions), 1)
        self.assertEqual(document.regions[0].shape, "point")
        self.assertEqual(
            [item.code for item in document.diagnostics],
            ["invalid-arity", "invalid-number", "non-finite-number", "invalid-arity"],
        )
        self.assertEqual([item.line for item in document.diagnostics], [2, 3, 4, 5])
        with self.assertRaises(DS9RegionSyntaxError) as raised:
            parse_ds9_regions(source, strict=True)
        self.assertEqual(len(raised.exception.diagnostics), 4)

    def test_coordinate_ranges_and_zero_sizes_are_rejected(self) -> None:
        document = parse_ds9_regions(
            """fk5
point(361,0)
point(10,-91)
circle(10,20,0\")
image
box(1,2,-3,4)
"""
        )

        self.assertEqual(document.regions, ())
        self.assertEqual(
            [item.code for item in document.diagnostics],
            [
                "coordinate-out-of-range",
                "coordinate-out-of-range",
                "size-out-of-range",
                "size-out-of-range",
            ],
        )

    def test_duplicate_tags_and_brace_escapes_are_preserved(self) -> None:
        document = parse_ds9_regions(
            r"image; point(1,2) # tag={one} tag={two} text={a \{brace\} and \\ slash}"
        )

        region = document.regions[0]
        self.assertEqual(region.attribute_values("tag"), ("one", "two"))
        self.assertEqual(region.label, r"a {brace} and \ slash")

    def test_unknown_coordinate_declaration_cannot_reuse_previous_system(self) -> None:
        document = parse_ds9_regions(
            "image\npoint(1,2)\nmade_up_system\npoint(3,4)\nimage\npoint(5,6)\n"
        )

        self.assertEqual(
            [region.parameters for region in document.regions],
            [(1.0, 2.0), (5.0, 6.0)],
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in document.diagnostics],
            ["invalid-statement", "shape-in-unsupported-system"],
        )

    def test_unsafe_control_and_directional_text_is_rejected(self) -> None:
        for source in (
            "image\npoint(1,2)\x00",
            "image\npoint(1,2) # text={safe\u202eevil}",
            "image\npoint(1,2)\ud800",
        ):
            with self.subTest(source=repr(source)):
                with self.assertRaises(DS9RegionError):
                    parse_ds9_regions(source)

        with self.assertRaises(ValueError):
            DS9Attribute("text", "safe\u202eevil")


class TestDS9RegionRoundTrip(unittest.TestCase):
    def test_round_trip_preserves_normalized_regions_and_attributes(self) -> None:
        original = DS9RegionDocument(
            global_attributes=(
                DS9Attribute("color", "cyan"),
                DS9Attribute("width", "3"),
            ),
            regions=(
                DS9Region(
                    "image",
                    "circle",
                    (10.25, 20.5, 4.0),
                    attributes=(DS9Attribute("text", "pixel target"),),
                ),
                DS9Region("physical", "box", (1.0, 2.0, 3.0, 4.0, -15.0), include=False),
                DS9Region("fk5", "ellipse", (180.0, -20.0, 0.1, 0.05, 32.0)),
                DS9Region(
                    "icrs",
                    "polygon",
                    (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
                    attributes=(DS9Attribute("color", "#123abc"), DS9Attribute("tag", "science")),
                ),
                DS9Region("image", "point", (9.0, 8.0), attributes=(DS9Attribute("point", "diamond 7"),)),
            ),
        )

        encoded = serialize_ds9_regions(original)
        decoded = parse_ds9_regions(encoded, strict=True)

        self.assertEqual(decoded.regions, original.regions)
        self.assertEqual(decoded.global_attributes, original.global_attributes)
        self.assertEqual(decoded.diagnostics, ())
        self.assertTrue(encoded.endswith("\n"))
        self.assertIn("0.10000000000000001d", encoded)

    def test_writer_rejects_unsupported_or_control_attributes(self) -> None:
        with self.assertRaises(ValueError):
            DS9Attribute("text", "line 1\nline 2")

        region = DS9Region(
            "image",
            "point",
            (1.0, 2.0),
            attributes=(DS9Attribute("command", "danger"),),
        )
        with self.assertRaisesRegex(DS9RegionError, "unsupported"):
            serialize_ds9_regions([region])

    def test_writer_stops_consuming_an_unbounded_region_iterable(self) -> None:
        region = DS9Region("image", "point", (1.0, 2.0))

        def endless_regions():
            while True:
                yield region

        with self.assertRaises(DS9RegionLimitError):
            serialize_ds9_regions(
                endless_regions(),
                limits=DS9RegionLimits(max_regions=2),
            )

    def test_region_constructor_bounds_programmatic_iterables(self) -> None:
        def endless_values():
            while True:
                yield 1.0

        def endless_attributes():
            while True:
                yield DS9Attribute("tag", "bounded")

        with self.assertRaises(DS9RegionLimitError):
            DS9Region("image", "point", endless_values())
        with self.assertRaises(DS9RegionLimitError):
            DS9Region("image", "point", (1.0, 2.0), attributes=endless_attributes())

    def test_writer_enforces_total_output_budget(self) -> None:
        regions = tuple(
            DS9Region("image", "point", (float(index), 1.0))
            for index in range(10)
        )

        with self.assertRaises(DS9RegionLimitError):
            serialize_ds9_regions(
                regions,
                limits=DS9RegionLimits(max_input_bytes=80),
            )


class TestDS9RegionBudgets(unittest.TestCase):
    def test_input_bytes_lines_and_line_length_are_bounded(self) -> None:
        with self.assertRaises(DS9RegionLimitError):
            parse_ds9_regions("image\n", limits=DS9RegionLimits(max_input_bytes=5))
        with self.assertRaises(DS9RegionLimitError):
            parse_ds9_regions(
                "image\npoint(1,2)\n",
                limits=DS9RegionLimits(max_lines=1),
            )
        with self.assertRaises(DS9RegionLimitError):
            parse_ds9_regions(
                "image\npoint(1,2)",
                limits=DS9RegionLimits(max_line_chars=8),
            )

    def test_region_polygon_and_total_vertex_budgets_are_bounded(self) -> None:
        with self.assertRaises(DS9RegionLimitError):
            parse_ds9_regions(
                "image\npoint(1,2)\npoint(3,4)\n",
                limits=DS9RegionLimits(max_regions=1),
            )
        with self.assertRaises(DS9RegionLimitError):
            parse_ds9_regions(
                "image\npolygon(1,1,2,2,3,3,4,4)\n",
                limits=DS9RegionLimits(max_vertices_per_polygon=3),
            )
        with self.assertRaises(DS9RegionLimitError):
            parse_ds9_regions(
                "image\npolygon(1,1,2,2,3,3)\npolygon(4,4,5,5,6,6)\n",
                limits=DS9RegionLimits(max_total_vertices=5),
            )

    def test_attribute_and_diagnostic_budgets_are_bounded(self) -> None:
        with self.assertRaises(DS9RegionLimitError):
            parse_ds9_regions(
                "image\npoint(1,2) # color=red width=2\n",
                limits=DS9RegionLimits(max_attributes_per_record=1),
            )
        with self.assertRaises(DS9RegionLimitError):
            parse_ds9_regions(
                "image\nbad one\nbad two\n",
                limits=DS9RegionLimits(max_diagnostics=1),
            )

    def test_extreme_numeric_tokens_and_values_are_rejected(self) -> None:
        with self.assertRaises(DS9RegionLimitError):
            parse_ds9_regions(
                "image\npoint(" + "1" * 20 + ",2)\n",
                limits=DS9RegionLimits(max_numeric_token_chars=10),
            )
        document = parse_ds9_regions(
            "image\npoint(1001,2)\n",
            limits=DS9RegionLimits(max_abs_pixel_value=1000.0),
        )
        self.assertEqual(document.regions, ())
        self.assertEqual(document.diagnostics[0].code, "coordinate-out-of-range")


class TestDS9RegionFiles(unittest.TestCase):
    def test_file_round_trip_and_atomic_overwrite(self) -> None:
        document = DS9RegionDocument(
            regions=(DS9Region("image", "circle", (1.0, 2.0, 3.0)),),
        )
        replacement = DS9RegionDocument(
            regions=(DS9Region("fk5", "point", (180.0, 45.0)),),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "regions.reg"
            write_ds9_region_file(path, document)
            self.assertEqual(read_ds9_region_file(path, strict=True).regions, document.regions)
            with self.assertRaises(FileExistsError):
                write_ds9_region_file(path, replacement)

            write_ds9_region_file(path, replacement, overwrite=True)
            loaded = read_ds9_region_file(path, strict=True)

        self.assertEqual(loaded.regions, replacement.regions)

    def test_file_reader_rejects_missing_directory_invalid_utf8_and_size(self) -> None:
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            with self.assertRaises(FileNotFoundError):
                read_ds9_region_file(directory_path / "missing.reg")
            with self.assertRaises(DS9RegionIOError):
                read_ds9_region_file(directory_path)

            invalid = directory_path / "invalid.reg"
            invalid.write_bytes(b"\xff\xfe\xfa")
            with self.assertRaises(DS9RegionError):
                read_ds9_region_file(invalid)

            large = directory_path / "large.reg"
            large.write_bytes(b"x" * 20)
            with self.assertRaises(DS9RegionLimitError):
                read_ds9_region_file(large, limits=DS9RegionLimits(max_input_bytes=10))

    def test_non_finite_programmatic_regions_are_rejected(self) -> None:
        for value in (math.inf, -math.inf, math.nan):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    DS9Region("image", "point", (value, 1.0))

    def test_programmatic_sky_angles_obey_serialization_numeric_budget(self) -> None:
        region = DS9Region("fk5", "box", (180.0, 45.0, 0.1, 0.2, 2_000.0))

        with self.assertRaises(ValueError):
            serialize_ds9_regions(
                (region,),
                limits=DS9RegionLimits(max_abs_pixel_value=1_000.0),
            )


if __name__ == "__main__":
    unittest.main()
