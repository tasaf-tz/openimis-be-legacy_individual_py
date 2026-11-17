"""Remove the archived RM4 rows from the live register; dry run unless --confirm, refused unless verified."""
import json

from django.core.management.base import BaseCommand, CommandError

from legacy_individual import rm4_archive


class Command(BaseCommand):
    help = 'Clear the archived RM4 households, members and their test data from the live register.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Really delete. Without it: dry run.')

    def handle(self, *args, **opts):
        try:
            result = rm4_archive.clear_live(confirm=opts['confirm'], emit=self.stdout.write)
        except rm4_archive.ArchiveNotVerified as error:
            raise CommandError(str(error))
        self.stdout.write(json.dumps(result, indent=2))
        if not opts['confirm']:
            self.stdout.write(self.style.WARNING('DRY RUN: nothing was deleted. Re-run with --confirm.'))
        elif result['live_rm4_households_left']:
            self.stdout.write(self.style.ERROR(f"{result['live_rm4_households_left']} live RM4 households left"))
        else:
            self.stdout.write(self.style.SUCCESS('live register cleared of RM4'))
