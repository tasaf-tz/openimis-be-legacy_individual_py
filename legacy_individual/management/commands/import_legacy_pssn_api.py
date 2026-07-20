import json

from django.core.management.base import BaseCommand, CommandError

from core.models import User
from legacy_individual.services import LegacyApiImportService


class Command(BaseCommand):
    help = "Pull one district from the legacy PSSN API into the legacy_individual tables."

    def add_arguments(self, parser):
        parser.add_argument("--district", required=True, help="District code, e.g. 0703 (a short numeric code like 703 is zero-padded).")
        parser.add_argument("--region", default=None, help="Region code, e.g. 07 (optional, recorded on the batch).")
        parser.add_argument("--paa-name", dest="paa_name", default=None, help="District/PAA display name (optional).")
        parser.add_argument("--user", default="Admin", help="LoginName to attribute the import to (default: Admin).")
        parser.add_argument("--dry-run", action="store_true", help="Fetch + parse only; do not write individuals/groups.")

    def handle(self, *args, **opts):
        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"User '{opts['user']}' not found. Pass --user <LoginName>.")

        self.stdout.write(
            f"Importing district {opts['district']} "
            f"(dry_run={opts['dry_run']}, user={opts['user']})..."
        )

        try:
            result = LegacyApiImportService(user).run(
                opts["district"],
                paa_name=opts.get("paa_name"),
                region_code=opts.get("region"),
                dry_run=opts["dry_run"],
            )
        except Exception as exc:
            raise CommandError(f"Import failed: {exc}")

        stats = result.get("stats") or {}
        self.stdout.write(self.style.SUCCESS(
            f"batch={result.get('batch_id')} status={result.get('status')} "
            f"raw_rows={result.get('raw_rows')} dry_run={result.get('dry_run')}"
        ))
        if result.get("replaces"):
            self.stdout.write(f"superseded prior batch(es): {result['replaces']}")
        self.stdout.write("stats: " + json.dumps(stats, default=str))
