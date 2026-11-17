"""Copy the live RM4 register into the RM4 archive tables; --dry-run writes nothing, --verify-only compares."""
import json

from django.core.management.base import BaseCommand, CommandError

from legacy_individual import rm4_archive


class Command(BaseCommand):
    help = 'Archive the live RM4 register into the Legacy Individual RM4 tables.'

    def add_arguments(self, parser):
        parser.add_argument('--district', help='District code; default all districts.')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--verify-only', action='store_true')
        parser.add_argument('--user', help='Audit user name (default: first core user).')

    def handle(self, *args, **opts):
        from core.models import User
        from location.models import Location

        if opts['verify_only']:
            return self._verify()

        district_id = None
        if opts['district']:
            district = Location.objects.filter(code=opts['district'], type='D', validity_to__isnull=True).first()
            if district is None:
                raise CommandError(f"no district with code {opts['district']}")
            district_id = district.id

        plan = [row for row in rm4_archive.districts() if district_id is None or row[0] == district_id]
        names = dict(Location.objects.filter(id__in=[d for d, _ in plan if d]).values_list('id', 'name'))
        for district, households in plan:
            self.stdout.write(f"  {names.get(district, rm4_archive.UNPLACED)}: {households} live RM4 households")
        if opts['dry_run']:
            self.stdout.write('dry run: nothing written')
            return

        user = (User.objects.filter(username=opts['user']).first() if opts['user']
                else User.objects.order_by('id').first())
        if user is None:
            raise CommandError('no core user for the audit trail')
        totals = rm4_archive.archive(user, district_id=district_id, emit=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(f"copied/refreshed: {totals}"))
        self._verify()

    def _verify(self):
        report = rm4_archive.verify()
        self.stdout.write(json.dumps(report, indent=2))
        if report['ok']:
            self.stdout.write(self.style.SUCCESS('VERIFIED: every live RM4 row is archived and identical'))
        else:
            self.stdout.write(self.style.ERROR('NOT VERIFIED: re-run archive_rm4 before any clear-down'))
