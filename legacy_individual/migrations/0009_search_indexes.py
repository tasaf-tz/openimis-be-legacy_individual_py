from django.db import migrations

INDEXES = [
    ("legacy_ind_first_name_trgm", "legacy_individual_legacyindividual",
     "USING gin (UPPER((first_name)::text) gin_trgm_ops)"),
    ("legacy_ind_last_name_trgm", "legacy_individual_legacyindividual",
     "USING gin (UPPER((last_name)::text) gin_trgm_ops)"),
    ("legacy_group_code_prefix", "legacy_individual_legacygroup",
     "USING btree (UPPER((code)::text) text_pattern_ops)"),
    ("legacy_group_phone", "legacy_individual_legacygroup",
     "USING btree ((\"Json_ext\" -> 'phone_no'))"),
]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("legacy_individual", "0008_legacygroupindividual_role_questionnaire_values"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ] + [
        migrations.RunSQL(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} {definition};',
            reverse_sql=f"DROP INDEX CONCURRENTLY IF EXISTS {name};",
        )
        for name, table, definition in INDEXES
    ]
