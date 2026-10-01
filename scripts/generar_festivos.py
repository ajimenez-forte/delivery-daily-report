"""Genera la migración con los festivos oficiales de Colombia y Costa Rica.

    pip install holidays
    python scripts/generar_festivos.py 2026 2027

Usa la librería `holidays` (https://github.com/vacanza/holidays), que cita las
leyes de cada país. Para Costa Rica solo toma los feriados de pago obligatorio
(categoría "public"). Los de pago no obligatorio (2 de agosto, 31 de agosto y
1 de diciembre) no se cargan: si Forte los da libres, el admin los agrega como
días no hábiles de Forte.
"""
import sys
from pathlib import Path

import holidays

OUT = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "20261001000200_festivos.sql"


def main(years):
    rows = []
    for country in ("CO", "CR"):
        for day, name in sorted(holidays.country_holidays(country, years=years).items()):
            rows.append((country, day.isoformat(), name.replace("'", "''")))
    lines = [
        "-- Daily Delivery · festivos oficiales (generado por scripts/generar_festivos.py, no editar a mano)",
        f"-- Librería holidays {holidays.__version__}. Años: {', '.join(map(str, years))}.",
        "-- Colombia: festivos nacionales. Costa Rica: feriados de pago obligatorio.",
        "",
        "INSERT INTO public.holidays (country, day, name) VALUES",
        ",\n".join(f"    ('{c}', '{d}', '{n}')" for c, d, n in rows),
        "ON CONFLICT (country, day) DO UPDATE SET name = excluded.name;",
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(rows)} festivos en {OUT.name}")


if __name__ == "__main__":
    main([int(y) for y in sys.argv[1:]] or [2026, 2027])
