# geopackage-crs-and-schema-validator
This is a Python script designed to inspect, validate, and generate plain-text reports for GeoPackage feature-layer schemas. It specifically checks datasets against the EPSG:4683 (PRS92) coordinate reference system and performs deep geometric coordinate checks. Additionally, the code reads SQLite databases, parses Well-Known Binary (WKB) geometry structures, and screens for structural discrepancies or out-of-bounds geographic data. Ultimately, the utility outputs PASS or FAIL results to help analysts ensure spatial data files meet precise attribute and spatial standards.

Requirements: Python 3.9+, standard library only.

This was created to automate the initial validation when receiving geopackages as part of the Philippine Mines & Geosciences Bureau (MGB) compliance requirements.

A schema for one of the required geopackages is hard-coded and used as basis for comparison.

To use:

Place the script and geopackage file on the same directory and replace the variable values under the CONFIGURATION section (lines 25 to 37).
