#!/bin/bash
# The framework package must stay domain-free (no CSV-profiler references). The CSV
# profiler lives in examples/csv_profiler/ and depends on the framework.
# Run by the domain-free CI job and the domain-free pre-commit hook, so both check
# the same pattern.
if grep -rnE --include='*.py' 'csv_profiler|ProfileConfig|computation_module|validate_csv|profile_csv|CSV_UPLOAD' cosmo_ecosystem/; then
    echo "ERROR: domain (CSV-profiler) reference found in cosmo_ecosystem/ — the framework package must stay domain-free."
    exit 1
fi
echo "OK: cosmo_ecosystem/ is domain-free."
