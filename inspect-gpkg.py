#!/usr/bin/env python3
"""
GeoPackage Schema Inspector and Validator
© OCTOBER 2026 - SUNBEAMGEO ANALYTICS AND INFORMATICS
https://sunbeamgeoanalytics.com

Version: 0.2.3

Read-only GeoPackage feature-layer schema and EPSG:4683 (PRS92)
metadata validation plus coordinate plausibility screening.
Writes PASS and FAIL reports as plain text.

Requirements: Python 3.9+, standard library only.
"""
import os
import re
import sqlite3
import struct
import math
from pathlib import Path

# ============================================================
# 1. CONFIGURATION
# ============================================================
GPKG_FILENAME = "SamplePolygonError_gpkg.gpkg"
EXPORT_TXT = True
TARGET_LAYER = None          # None validates all registered feature layers
CASE_SENSITIVE = True
EXPECTED_EPSG = 4683
EXPECTED_CRS_NAME = "PRS92"
VALIDATE_CRS = True
VALIDATE_COORDINATES = True
# Broad screening bounds, not an official Philippines boundary.
LONGITUDE_MIN, LONGITUDE_MAX = 116.0, 127.0
LATITUDE_MIN, LATITUDE_MAX = 4.0, 22.0
# Prevent unbounded diagnostic output in reports.
MAX_EXAMPLE_ISSUES = 10

# ============================================================
# 2. EXPECTED ATTRIBUTE SCHEMA
# ============================================================
EXPECTED_SCHEMA = {
    "fid":               {"type": "INTEGER",  "length": 0,   "precision": 0},
    "OBJECTID":          {"type": "INTEGER",  "length": 0,   "precision": 0},
    "TenementNumber":    {"type": "TEXT",     "length": 100, "precision": 0},
    "TenementHolder":    {"type": "TEXT",     "length": 100, "precision": 0},
    "Region":            {"type": "TEXT",     "length": 255, "precision": 0},
    "Type":              {"type": "TEXT",     "length": 50,  "precision": 0},
    "created_user":      {"type": "TEXT",     "length": 255, "precision": 0},
    "created_date":      {"type": "DATETIME", "length": 0,   "precision": 0},
    "last_edited_user":  {"type": "TEXT",     "length": 255, "precision": 0},
    "last_edited_date":  {"type": "DATETIME", "length": 0,   "precision": 0},
    "GlobalID":          {"type": "TEXT",     "length": 0,   "precision": 0},
}


def separator(char="=", width=90):
    return char * width


def normalize_name(name):
    return name if CASE_SENSITIVE else name.lower()


def parse_sqlite_type(declared):
    """Return normalized declared type, length, precision."""
    value = (declared or "").strip().upper()
    match = re.fullmatch(
        r"([A-Z0-9_ ]+?)(?:\s*\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\))?",
        value
    )
    if not match:
        return value, 0, 0
    base = match.group(1).strip()
    length = int(match.group(2)) if match.group(2) else 0
    precision = int(match.group(3)) if match.group(3) else 0
    if base in {"INT", "INT8", "BIGINT", "INTEGER64"}:
        base = "INTEGER"
    elif base in {"VARCHAR", "CHARACTER VARYING", "CHAR"}:
        base = "TEXT"
    return base, length, precision


def format_type(field):
    base = field["type"]
    length = field["length"]
    precision = field["precision"]
    if length:
        return f"{base}({length},{precision})" if precision else f"{base}({length})"
    return base


def get_layer_schema(cursor, table_name):
    cursor.execute(
        'SELECT name, type, "notnull", pk FROM pragma_table_info(?)',
        (table_name,)
    )
    columns = cursor.fetchall()
    cursor.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
        (table_name,)
    )
    geometry_names = {row[0] for row in cursor.fetchall()}
    schema = {}
    for name, declared, notnull, pk in columns:
        if name in geometry_names:
            continue
        base, length, precision = parse_sqlite_type(declared)
        schema[name] = {
            "type": base,
            "length": length,
            "precision": precision,
            "nullable": not bool(notnull or pk),
            "primary_key": bool(pk),
            "declared_type": declared,
        }
    return schema


def compare_schemas(actual, expected):
    differences = []
    actual_lookup = {normalize_name(k): k for k in actual}
    expected_lookup = {normalize_name(k): k for k in expected}
    for key, expected_name in expected_lookup.items():
        exp = expected[expected_name]
        if key not in actual_lookup:
            differences.append({
                "field": expected_name, "issue": "MISSING FIELD",
                "actual": "NOT FOUND", "expected": format_type(exp)
            })
            continue
        actual_name = actual_lookup[key]
        got = actual[actual_name]
        if got["type"] != exp["type"]:
            differences.append({
                "field": expected_name, "issue": "DATA TYPE MISMATCH",
                "actual": got["type"], "expected": exp["type"]
            })
        if got["length"] != exp["length"]:
            differences.append({
                "field": expected_name, "issue": "LENGTH MISMATCH",
                "actual": got["length"], "expected": exp["length"]
            })
        if got["precision"] != exp["precision"]:
            differences.append({
                "field": expected_name, "issue": "PRECISION MISMATCH",
                "actual": got["precision"], "expected": exp["precision"]
            })
    for key, actual_name in actual_lookup.items():
        if key not in expected_lookup:
            differences.append({
                "field": actual_name, "issue": "UNEXPECTED FIELD",
                "actual": format_type(actual[actual_name]),
                "expected": "NOT IN TEMPLATE"
            })
    return differences


def validate_layer_crs(cursor, table_name, layer_srs_id):
    """Validate CRS metadata; does not prove coordinate values were transformed."""
    issues = []
    cursor.execute(
        "SELECT column_name, geometry_type_name, srs_id "
        "FROM gpkg_geometry_columns WHERE table_name = ?",
        (table_name,)
    )
    geom = cursor.fetchone()
    geom_srs = geom[2] if geom else None

    cursor.execute(
        "SELECT srs_name, organization, organization_coordsys_id, definition "
        "FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
        (layer_srs_id,)
    )
    crs = cursor.fetchone()
    crs_name, authority, authority_code, definition = (
        crs if crs else (None, None, None, None)
    )
    if layer_srs_id != EXPECTED_EPSG:
        issues.append(
            f"Layer SRS ID mismatch: expected {EXPECTED_EPSG}, found {layer_srs_id}"
        )
    if geom is None:
        issues.append("Geometry column metadata not found.")
    elif geom_srs != EXPECTED_EPSG:
        issues.append(
            f"Geometry SRS ID mismatch: expected {EXPECTED_EPSG}, found {geom_srs}"
        )
    if crs is None:
        issues.append(f"No CRS registry entry for SRS ID {layer_srs_id}.")
    else:
        if str(authority).upper() != "EPSG":
            issues.append(f"CRS authority mismatch: expected EPSG, found {authority}")
        if authority_code != EXPECTED_EPSG:
            issues.append(
                f"CRS authority code mismatch: expected {EXPECTED_EPSG}, "
                f"found {authority_code}"
            )
    return {
        "status": "PASS" if not issues else "FAIL",
        "layer_srs_id": layer_srs_id,
        "geometry_srs_id": geom_srs,
        "geometry_type": geom[1] if geom else "UNKNOWN",
        "crs_name": crs_name,
        "authority": authority,
        "authority_code": authority_code,
        "definition_present": bool(definition and definition.strip()),
        "issues": issues,
    }



# ============================================================
# 5. GEOMETRY COORDINATE PLAUSIBILITY (GPKG + WKB)
# ============================================================
class GeometryDecodeError(ValueError):
    pass


def geometry_coordinates(blob):
    """Yield (x, y) coordinates from GeoPackage standard WKB geometry.

    Supports standard Point, LineString, Polygon, MultiPoint,
    MultiLineString, MultiPolygon and GeometryCollection, including
    ISO/EWKB Z and M coordinate dimensions. Unsupported geometry types
    are reported as failures, not silently accepted.
    """
    if not isinstance(blob, bytes) or len(blob) < 8 or blob[:2] != b"GP":
        raise GeometryDecodeError("Missing or invalid GeoPackage geometry header")
    if blob[2] != 0:
        raise GeometryDecodeError(f"Unsupported GeoPackage binary version {blob[2]}")
    flags = blob[3]
    if flags & 0b11000000:
        raise GeometryDecodeError("Reserved GeoPackage header flags set")
    envelope_code = (flags >> 1) & 7
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope_code not in envelope_sizes:
        raise GeometryDecodeError("Invalid GeoPackage envelope indicator")
    offset = 8 + envelope_sizes[envelope_code]
    if offset >= len(blob):
        raise GeometryDecodeError("Geometry WKB is missing")
    view = memoryview(blob)

    def unpack(fmt, pos, order):
        size = struct.calcsize(fmt)
        if pos + size > len(view):
            raise GeometryDecodeError("Truncated geometry WKB")
        return struct.unpack_from(order + fmt, view, pos)[0], pos + size

    def parse(pos, depth=0):
        if depth > 32:
            raise GeometryDecodeError("Excessively nested geometry")
        endian, pos = unpack("B", pos, "<")
        if endian not in (0, 1):
            raise GeometryDecodeError("Invalid WKB byte order")
        order = "<" if endian == 1 else ">"
        raw_type, pos = unpack("I", pos, order)
        has_z = bool(raw_type & 0x80000000)
        has_m = bool(raw_type & 0x40000000)
        has_srid = bool(raw_type & 0x20000000)
        geom_type = raw_type & 0x1FFFFFFF
        if geom_type >= 3000:
            has_z, has_m, geom_type = True, True, geom_type - 3000
        elif geom_type >= 2000:
            has_m, geom_type = True, geom_type - 2000
        elif geom_type >= 1000:
            has_z, geom_type = True, geom_type - 1000
        if has_srid:
            _, pos = unpack("I", pos, order)
        dimensions = 2 + int(has_z) + int(has_m)

        def points(pos, count):
            if count > (len(view) - pos) // (dimensions * 8):
                raise GeometryDecodeError("Invalid coordinate count or truncated WKB")
            for _ in range(count):
                values = struct.unpack_from(order + "d" * dimensions, view, pos)
                pos += dimensions * 8
                x, y = values[:2]
                if math.isnan(x) and math.isnan(y) and geom_type == 1:
                    continue  # WKB empty point
                yield (x, y)
            return pos

        if geom_type == 1:
            if pos + dimensions * 8 > len(view):
                raise GeometryDecodeError("Truncated WKB point")
            values = struct.unpack_from(order + "d" * dimensions, view, pos)
            pos += dimensions * 8
            if not (math.isnan(values[0]) and math.isnan(values[1])):
                yield values[0], values[1]
        elif geom_type == 2:
            count, pos = unpack("I", pos, order)
            if count > (len(view) - pos) // (dimensions * 8):
                raise GeometryDecodeError("Invalid LineString coordinate count")
            for _ in range(count):
                vals = struct.unpack_from(order + "d" * dimensions, view, pos)
                pos += dimensions * 8
                yield vals[0], vals[1]
        elif geom_type == 3:
            rings, pos = unpack("I", pos, order)
            if rings > (len(view) - pos) // 4:
                raise GeometryDecodeError("Invalid polygon ring count")
            for _ in range(rings):
                count, pos = unpack("I", pos, order)
                if count > (len(view) - pos) // (dimensions * 8):
                    raise GeometryDecodeError("Invalid polygon vertex count")
                for _ in range(count):
                    vals = struct.unpack_from(order + "d" * dimensions, view, pos)
                    pos += dimensions * 8
                    yield vals[0], vals[1]
        elif geom_type in (4, 5, 6, 7):
            count, pos = unpack("I", pos, order)
            if count > (len(view) - pos) // 5:
                raise GeometryDecodeError("Invalid collection member count")
            for _ in range(count):
                # Generator return value supplies updated byte offset.
                nested = parse(pos, depth + 1)
                while True:
                    try:
                        xy = next(nested)
                        yield xy
                    except StopIteration as stop:
                        pos = stop.value
                        break
        else:
            raise GeometryDecodeError(f"Unsupported WKB geometry type {geom_type}")
        return pos

    iterator = parse(offset)
    while True:
        try:
            yield next(iterator)
        except StopIteration as stop:
            if stop.value != len(blob):
                raise GeometryDecodeError("Unexpected trailing bytes in geometry WKB")
            break


def validate_coordinates(cursor, table_name):
    """Inspect all geometry coordinates, not just the bounding-box metadata."""
    result = {
        "status": "PASS", "features": 0, "vertices": 0,
        "empty": 0, "invalid": 0, "outside": 0,
        "longitude_min": None, "longitude_max": None,
        "latitude_min": None, "latitude_max": None,
        "issues": [],
    }
    cursor.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
        (table_name,)
    )
    geometry_row = cursor.fetchone()
    if not geometry_row:
        result["status"] = "FAIL"
        result["issues"].append("No registered geometry column")
        return result
    safe_table = table_name.replace('"', '""')
    safe_column = geometry_row[0].replace('"', '""')
    cursor.execute(f'SELECT "{safe_column}" FROM "{safe_table}"')

    def issue(message):
        if len(result["issues"]) < MAX_EXAMPLE_ISSUES:
            result["issues"].append(message)

    for (blob,) in cursor:
        result["features"] += 1
        index = result["features"]
        if blob is None or blob == b"":
            result["empty"] += 1
            issue(f"Feature #{index}: NULL or empty geometry")
            continue
        found = 0
        try:
            for x, y in geometry_coordinates(blob):
                found += 1
                result["vertices"] += 1
                if not math.isfinite(x) or not math.isfinite(y):
                    result["invalid"] += 1
                    issue(f"Feature #{index}: non-finite coordinate ({x}, {y})")
                    continue
                for key, value in (("longitude", x), ("latitude", y)):
                    lo, hi = key + "_min", key + "_max"
                    result[lo] = value if result[lo] is None else min(result[lo], value)
                    result[hi] = value if result[hi] is None else max(result[hi], value)
                if not (LONGITUDE_MIN <= x <= LONGITUDE_MAX and
                        LATITUDE_MIN <= y <= LATITUDE_MAX):
                    result["outside"] += 1
                    issue(f"Feature #{index}: coordinate outside screening bounds ({x:.7f}, {y:.7f})")
            if found == 0:
                result["empty"] += 1
                issue(f"Feature #{index}: geometry contains no coordinates")
        except (GeometryDecodeError, ValueError, TypeError, struct.error) as error:
            result["invalid"] += 1
            issue(f"Feature #{index}: unreadable geometry ({error})")
    if result["empty"] or result["invalid"] or result["outside"]:
        result["status"] = "FAIL"
    return result


def coordinate_report_lines(result):
    if result is None:
        return ["Coordinate plausibility validation : NOT PERFORMED"]
    def fmt(value):
        return "N/A" if value is None else f"{value:.7f}"
    lines = [
        separator(), "COORDINATE PLAUSIBILITY CHECK", separator(),
        f"Status                  : {result['status']}",
        f"Screening longitude     : {LONGITUDE_MIN} to {LONGITUDE_MAX} degrees E",
        f"Screening latitude      : {LATITUDE_MIN} to {LATITUDE_MAX} degrees N",
        f"Features inspected      : {result['features']}",
        f"Coordinate pairs        : {result['vertices']}",
        f"Longitude range         : {fmt(result['longitude_min'])} to {fmt(result['longitude_max'])}",
        f"Latitude range          : {fmt(result['latitude_min'])} to {fmt(result['latitude_max'])}",
        f"Empty geometries        : {result['empty']}",
        f"Invalid geometries/XY   : {result['invalid']}",
        f"Out-of-bounds vertices  : {result['outside']}",
    ]
    if result["issues"]:
        lines.extend(["", "Examples of issues (limited):"])
        lines.extend(f"- {issue}" for issue in result["issues"])
    lines.extend([
        "", "NOTE: This is a broad geographic plausibility screening only.",
        "It does not establish actual datum transformation accuracy or", 
        "prove that coordinates are expressed in PRS92.",
    ])
    return lines

def schema_lines(title, schema):
    lines = [
        separator(), title, separator(),
        f"{'Field Name':25}{'Data Type':18}{'Length':12}{'Precision':12}",
        separator("-"),
    ]
    for name, field in schema.items():
        lines.append(
            f"{name:25}{field['type']:18}"
            f"{field['length']:<12}{field['precision']:<12}"
        )
    lines.append(f"Total Fields: {len(schema)}")
    return lines


def report_lines(gpkg_path, layer, geometry, features, actual, differences, crs, coordinates):
    schema_pass = not differences
    crs_pass = crs is not None and crs["status"] == "PASS"
    # If CRS validation is disabled, only schema determines PASS.
    coordinate_pass = coordinates is not None and coordinates["status"] == "PASS"
    passed = (schema_pass and (crs_pass if VALIDATE_CRS else True)
              and (coordinate_pass if VALIDATE_COORDINATES else True))
    status = "PASS" if passed else "FAIL"
    lines = [
        separator(),
        "SUNBEAMGEO ANALYTICS AND INFORMATICS",
        "MONITORING STATION GEOPACKAGE VALIDATION REPORT v0.2.3",
        separator(),
        f"GeoPackage           : {gpkg_path.name}",
        f"Layer                : {layer}",
        f"Features             : {features}",
        f"Geometry             : {geometry}",
        f"Expected CRS         : EPSG:{EXPECTED_EPSG} - {EXPECTED_CRS_NAME}",
        f"Actual Layer SRS     : {crs['layer_srs_id'] if crs else 'NOT CHECKED'}",
        f"Actual Geometry SRS  : {crs['geometry_srs_id'] if crs else 'NOT CHECKED'}",
        f"CRS Registry         : {crs['authority'] if crs else 'NOT CHECKED'}:"
        f"{crs['authority_code'] if crs else 'NOT CHECKED'}",
        "",
        separator(),
        f"VALIDATION RESULT: {status}",
        separator(),
        f"Field schema validation : {'PASS' if schema_pass else 'FAIL'}",
        f"CRS metadata validation : "
        f"{crs['status'] if crs else 'NOT PERFORMED'}",
        f"Coordinate plausibility : "
        f"{coordinates['status'] if coordinates else 'NOT PERFORMED'}",
        "",
    ]
    if passed:
        lines.extend([
            "The GeoPackage PASSED the enabled validation checks.",
            "All required fields are present; no unexpected fields were detected.",
            "Declared data types, lengths, and precisions match the template.",
        ])
        if VALIDATE_CRS:
            lines.append(
                f"CRS metadata matches EPSG:{EXPECTED_EPSG} - {EXPECTED_CRS_NAME}."
            )
    else:
        lines.append("The GeoPackage FAILED validation. See differences below.")
    lines.extend(["", *coordinate_report_lines(coordinates)])
    lines.extend(["", *schema_lines("ACTUAL GEOPACKAGE SCHEMA", actual)])
    lines.extend(["", f"Features: {features}"])
    if not passed:
        lines.extend([""] + schema_lines("EXPECTED TEMPLATE SCHEMA", EXPECTED_SCHEMA))
        lines.extend(["", separator(), "FIELD SCHEMA DIFFERENCES", separator()])
        if differences:
            for item in differences:
                lines.extend([
                    f"Field    : {item['field']}",
                    f"Issue    : {item['issue']}",
                    f"Actual   : {item['actual']}",
                    f"Expected : {item['expected']}",
                    "",
                ])
        else:
            lines.append("No field schema differences.")
        lines.extend(["", separator(), "CRS VALIDATION DETAILS", separator()])
        if crs is None:
            lines.append("CRS validation not performed.")
        elif crs["issues"]:
            lines.extend(f"- {issue}" for issue in crs["issues"])
        else:
            lines.append("No CRS metadata differences.")
    lines.extend([
        "",
        "NOTE: CRS validation checks GeoPackage metadata only; it does not",
        "verify that coordinate values were correctly transformed.",
        "",
        separator(),
        "END OF REPORT",
        separator(),
    ])
    return status, "\n".join(lines) + "\n"


def export_report(gpkg_path, layer_name, status, content):
    safe_layer = re.sub(r"[^A-Za-z0-9_-]", "_", layer_name)
    base = f"{gpkg_path.stem}_{safe_layer}"
    output = gpkg_path.with_name(f"{base}_{status}.txt")
    output.write_text(content, encoding="utf-8")
    # Remove a stale report with the opposite status after successful write.
    other = "FAIL" if status == "PASS" else "PASS"
    stale = gpkg_path.with_name(f"{base}_{other}.txt")
    if stale.exists():
        try:
            stale.unlink()
        except OSError as error:
            print(f"WARNING: Could not remove old report {stale.name}: {error}")
    return output


def inspect_geopackage():
    gpkg_path = Path(__file__).resolve().parent / GPKG_FILENAME
    print(separator())
    print("SUNBEAMGEO ANALYTICS AND INFORMATICS")
    print("MONITORING STATION GEOPACKAGE SCHEMA INSPECTOR v0.2.3")
    print(separator())
    print(f"GeoPackage: {gpkg_path}")
    if not gpkg_path.is_file():
        print("ERROR: GeoPackage file not found.")
        return False
    if not os.access(gpkg_path, os.R_OK):
        print("ERROR: GeoPackage file is not readable in this execution context.")
        return False

    uri = gpkg_path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:
        print(f"ERROR: Cannot open GeoPackage: {error}")
        return False

    try:
        cursor = connection.cursor()
        cursor.execute("PRAGMA application_id")
        if cursor.fetchone()[0] != 0x47504B47:
            print("ERROR: Invalid GeoPackage application ID.")
            return False
        cursor.execute(
            "SELECT table_name, data_type, srs_id FROM gpkg_contents "
            "WHERE data_type = 'features' ORDER BY table_name"
        )
        layers = cursor.fetchall()
        if TARGET_LAYER is not None:
            layers = [row for row in layers if row[0] == TARGET_LAYER]
        if not layers:
            print("ERROR: No matching registered feature layers.")
            return False

        all_passed = True
        for table_name, layer_type, srs_id in layers:
            print("\n" + separator("-"))
            print(f"LAYER: {table_name} ({layer_type})")
            actual = get_layer_schema(cursor, table_name)
            differences = compare_schemas(actual, EXPECTED_SCHEMA)
            crs = (
                validate_layer_crs(cursor, table_name, srs_id)
                if VALIDATE_CRS else None
            )
            cursor.execute(
                "SELECT geometry_type_name FROM gpkg_geometry_columns "
                "WHERE table_name = ?", (table_name,)
            )
            geom_row = cursor.fetchone()
            geometry = geom_row[0] if geom_row else "UNKNOWN"
            coordinates = (
                validate_coordinates(cursor, table_name)
                if VALIDATE_COORDINATES else None
            )
            # Table name originates from gpkg_contents, not user SQL.
            escaped_name = table_name.replace('"', '""')
            cursor.execute(f'SELECT COUNT(*) FROM "{escaped_name}"')
            features = cursor.fetchone()[0]
            status, content = report_lines(
                gpkg_path, table_name, geometry, features,
                actual, differences, crs, coordinates
            )
            print(content)
            if EXPORT_TXT:
                output = export_report(gpkg_path, table_name, status, content)
                print(f"Text report: {output}")
            if status != "PASS":
                all_passed = False
        print(f"\nFINAL RESULT: {'PASS' if all_passed else 'FAIL'}")
        return all_passed
    except (sqlite3.Error, OSError) as error:
        print(f"ERROR: {error}")
        return False
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(0 if inspect_geopackage() else 1)
