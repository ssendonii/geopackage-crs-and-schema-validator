# geopackage-crs-and-schema-validator
This is a read-only GeoPackage feature-layer schema and CRS metadata validator plus coordinate plausibility screening. A PASS / FAIL report in plain text is then provided as part of the output.  Requirements: Python 3.9+, standard library only.

This was created to automate the initial validation when receiving geopackages as part of the Philippine Mines & Geosciences Bureau (MGB) compliance requirements.

A schema for one of the required geopackages is hard-coded and used as basis for comparison.

To use:

Place the script and geopackage file on the same directory and replace the variable values under the CONFIGURATION section (lines 25 to 37).
