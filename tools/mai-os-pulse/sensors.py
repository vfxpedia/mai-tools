"""Read-only OS sensors, explicit identity mapping, registry freshness guard."""
import sys, time
from metrics import numeric
import psutil

def read_sensors():
    if sys.platform != 'win32':
        rows = []
        try:
            for chip, values in psutil.sensors_temperatures().items():
                for n, item in enumerate(values):
                    label = item.label or f'Temperature {n}'
                    rows.append({'id':f'{chip}/{label}/{n}', 'label':f'{chip} · {label}',
                                 'value':numeric(item.current),'unit':'°C','source':'OS hwmon'})
        except (AttributeError, OSError):
            pass
        return rows
    import winreg
    rows = []
    for hive_name, hive in [('HKCU',winreg.HKEY_CURRENT_USER),('HKLM',winreg.HKEY_LOCAL_MACHINE)]:
        try:
            with winreg.OpenKey(hive, r'SOFTWARE\HWiNFO64\VSB') as key:
                _, count, stamp = winreg.QueryInfoKey(key)
                fresh = time.time() - (stamp / 10_000_000 - 11644473600) < 15
                values = dict(winreg.EnumValue(key, n)[:2] for n in range(count))
                for name, value in values.items():
                    if not name.startswith('ValueRaw'): continue
                    idx = name[len('ValueRaw'):]
                    sensor, label = values.get('Sensor'+idx,''),values.get('Label'+idx,'')
                    # Name-based identity prevents silently reusing a shifted index.
                    identity = f'{hive_name}/{sensor}/{label}'
                    pretty = str(values.get('Value'+idx,''))
                    unit = '°C' if '°C' in pretty else ('W' if pretty.endswith('W') else '')
                    rows.append({'id':identity,'label':f'{sensor} · {label}','value':numeric(value) if fresh else None,
                                 'unit':unit,'source':f'HWiNFO {hive_name}', 'fresh':fresh})
            if rows: break
        except OSError: continue
    return rows

def selected(rows, sensor_id):
    found = [row for row in rows if row['id'] == sensor_id]
    return found[0]['value'] if len(found) == 1 else None
