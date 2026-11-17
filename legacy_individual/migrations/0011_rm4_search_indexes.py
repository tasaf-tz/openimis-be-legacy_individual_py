from django.db import migrations

INDEXES = [
    ("rm4_ind_first_name_trgm", "legacy_individual_rm4individual",
     "USING gin (UPPER((first_name)::text) gin_trgm_ops)"),
    ("rm4_ind_last_name_trgm", "legacy_individual_rm4individual",
     "USING gin (UPPER((last_name)::text) gin_trgm_ops)"),
    ("rm4_ind_external_id", "legacy_individual_rm4individual",
     "USING btree (UPPER(\"Json_ext\" ->> 'external_id') text_pattern_ops)"),
    ("rm4_group_code_prefix", "legacy_individual_rm4group",
     "USING btree (UPPER((code)::text) text_pattern_ops)"),
    ("rm4_group_interview_key", "legacy_individual_rm4group",
     "USING btree ((\"Json_ext\" ->> 'interview_key'))"),
    ("rm4_group_pmt_class", "legacy_individual_rm4group",
     "USING btree ((\"Json_ext\" ->> 'pmt_class_household'))"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("legacy_individual", "0010_rm4_archive"),
    ]

    operations = [
        migrations.RunSQL("CREATE EXTENSION IF NOT EXISTS pg_trgm;", reverse_sql=migrations.RunSQL.noop),
    ] + [
        migrations.RunSQL(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} {definition};",
            reverse_sql=f"DROP INDEX IF EXISTS {name};",
        )
        for name, table, definition in INDEXES
    ]
