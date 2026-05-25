#!/bin/bash
# ============================================================
# BreatheESG — Day 1 setup script
# Run this once from the folder where you want the project.
# ============================================================
set -e

PROJECT="breathe_esg"

echo "── 1. Create project folder ────────────────────────────"
mkdir -p $PROJECT && cd $PROJECT

echo "── 2. Python virtual environment ───────────────────────"
python3 -m venv .venv
source .venv/bin/activate

echo "── 3. Install dependencies ──────────────────────────────"
pip install --upgrade pip
pip install \
  Django==4.2.13 \
  djangorestframework==3.15.1 \
  djangorestframework-simplejwt==5.3.1 \
  django-cors-headers==4.3.1 \
  psycopg2-binary==2.9.9 \
  python-decouple==3.8 \
  Pillow==10.3.0 \
  gunicorn==22.0.0 \
  whitenoise==6.7.0

pip freeze > requirements.txt

echo "── 4. Copy scaffold files into this folder ──────────────"
# At this point: copy the downloaded scaffold files here.
# (config/, apps/, manage.py, Procfile, runtime.txt, .env.example)
echo "    → Paste scaffold files now, then press Enter to continue."
read -r

echo "── 5. Set up .env ───────────────────────────────────────"
cp .env.example .env
# Generate a real secret key and write it into .env
SECRET=$(python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")
sed -i "s|replace-me-with-a-long-random-string|$SECRET|g" .env
echo "    → Secret key written to .env"

echo "── 6. Run migrations ────────────────────────────────────"
python manage.py makemigrations tenants ingestion normalization audit review
python manage.py migrate

echo "── 7. Create superuser ──────────────────────────────────"
echo "    → Creating admin user (username: admin, password: breathe123)"
python manage.py shell -c "
from apps.tenants.models import Tenant, User
t, _ = Tenant.objects.get_or_create(
    slug='demo-client',
    defaults=dict(name='Demo Client Ltd', country_code='IN')
)
if not User.objects.filter(username='admin').exists():
    u = User.objects.create_superuser('admin', 'admin@breatheesg.com', 'breathe123')
    u.tenant = t
    u.role = 'admin'
    u.save()
    print('  Superuser created.')
else:
    print('  Superuser already exists.')
"

echo "── 8. Seed emission factors ─────────────────────────────"
python manage.py shell -c "
from apps.normalization.models import EmissionFactor
factors = [
    # DEFRA 2023 — https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2023
    dict(fuel_type='diesel',       unit='L',     kg_co2e_per_unit=2.68890, source='DEFRA 2023', valid_from_year=2023),
    dict(fuel_type='lpg',          unit='KG',    kg_co2e_per_unit=2.93300, source='DEFRA 2023', valid_from_year=2023),
    dict(fuel_type='heating_oil',  unit='L',     kg_co2e_per_unit=2.54050, source='DEFRA 2023', valid_from_year=2023),
    dict(fuel_type='electricity',  unit='kWh',   kg_co2e_per_unit=0.23314, source='DEFRA 2023', valid_from_year=2023),
    dict(fuel_type='flight_eco',   unit='km',    kg_co2e_per_unit=0.25500, source='DEFRA 2023', valid_from_year=2023),
    dict(fuel_type='flight_bus',   unit='km',    kg_co2e_per_unit=0.61480, source='DEFRA 2023', valid_from_year=2023),
    dict(fuel_type='hotel',        unit='night', kg_co2e_per_unit=19.9000, source='DEFRA 2023', valid_from_year=2023),
    dict(fuel_type='car',          unit='km',    kg_co2e_per_unit=0.17050, source='DEFRA 2023', valid_from_year=2023),
    dict(fuel_type='train',        unit='km',    kg_co2e_per_unit=0.03549, source='DEFRA 2023', valid_from_year=2023),
]
created = 0
for f in factors:
    _, c = EmissionFactor.objects.get_or_create(
        fuel_type=f['fuel_type'], valid_from_year=f['valid_from_year'], defaults=f)
    if c: created += 1
print(f'  {created} emission factors seeded.')
"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Setup complete."
echo "  Run:  source .venv/bin/activate"
echo "        python manage.py runserver"
echo "  API:  http://localhost:8000/api/auth/login/"
echo "  Admin:http://localhost:8000/admin/  (admin / breathe123)"
echo "════════════════════════════════════════════════════════"
