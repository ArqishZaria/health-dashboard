"""
Seeds baseline reference data (regions, local councils, portfolios/programs)
and one demo user per role so the system can be explored immediately after
installation.

Usage: python manage.py seed_demo_data
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Region, LocalCouncil, JamatKhana, Portfolio, Program, User


class Command(BaseCommand):
    help = "Seed demo regions, local councils, portfolios/programs and demo users."

    @transaction.atomic
    def handle(self, *args, **options):
        regions_data = {
            "Karachi": ["Karachi Central", "Karachi South", "Karachi East"],
            "Sindh": ["Hyderabad", "Sukkur"],
            "Punjab": ["Lahore", "Rawalpindi"],
        }
        region_objs = {}
        for region_name, councils in regions_data.items():
            region, _ = Region.objects.get_or_create(name=region_name)
            region_objs[region_name] = region
            for council_name in councils:
                lc, _ = LocalCouncil.objects.get_or_create(region=region, name=council_name)
                JamatKhana.objects.get_or_create(local_council=lc, name=f"{council_name} Main Jamatkhana")
        self.stdout.write(self.style.SUCCESS("Regions, local councils and jamatkhanas seeded."))

        portfolios = {
            "Health Screening": ["Cardiac Risk Assessment", "Mental Health (DASS-21)", "Elderly Eye Screening"],
            "Training & Capacity Building": ["Community Health Worker Training", "First Aid Training"],
            "Community Health": ["Awareness Sessions", "Outreach Campaigns"],
        }
        for portfolio_name, programs in portfolios.items():
            portfolio, _ = Portfolio.objects.get_or_create(name=portfolio_name)
            for p in programs:
                Program.objects.get_or_create(portfolio=portfolio, name=p)
        self.stdout.write(self.style.SUCCESS("Portfolios and programs seeded."))

        karachi = region_objs["Karachi"]
        karachi_central = LocalCouncil.objects.get(region=karachi, name="Karachi Central")

        demo_users = [
            dict(username="national_admin", role=User.Role.NATIONAL, password="Passw0rd!123"),
            dict(username="regional_coord", role=User.Role.REGIONAL, region=karachi, password="Passw0rd!123"),
            dict(username="local_officer", role=User.Role.LOCAL, local_council=karachi_central, password="Passw0rd!123"),
            dict(username="data_entry", role=User.Role.DATA_ENTRY, local_council=karachi_central, password="Passw0rd!123"),
        ]
        for u in demo_users:
            password = u.pop("password")
            username = u.pop("username")
            user, created = User.objects.get_or_create(username=username, defaults=u)
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created demo user '{username}' / password: {password}"))
            else:
                self.stdout.write(f"Demo user '{username}' already exists, skipping.")

        self.stdout.write(self.style.SUCCESS("Demo data seeding complete."))
