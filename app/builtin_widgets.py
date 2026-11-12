"""Product policy for Widgets retained in source but withheld from distribution."""

# Keep the implementation and existing user records for future review. Do not
# discover this Widget as built-in or include it in app/SDK resource bundles.
WITHHELD_BUILTIN_WIDGETS = frozenset({'task-records'})
