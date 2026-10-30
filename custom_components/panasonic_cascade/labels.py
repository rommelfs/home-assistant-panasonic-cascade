"""Compact default labels without changing entity identities or user names."""
import re


def compact_label(label):
    label = re.sub(r'\bHP\s*0*(\d+)\s*(?:[-–]\s*(?:Main|Sub\s*Unit))?', lambda m: f'WP {int(m[1])}', str(label), flags=re.I)
    parts = [p.strip() for p in re.split(r'\s+[–·]\s+|\|', label)]
    parts = [p for p in parts if p and p.casefold() not in ('point group', 'floor', 'site info')]
    replacements = {
        'Kühlen/Wärmerückgewinnung':'Kühlen/WRG',
        'Elektrische Leistung':'el. Leistung', 'Thermische Leistung':'Wärmeleistung',
        'Aufgenommene Energie':'Stromzähler', 'Erzeugte Energie':'Wärmezähler',
        'Compressor Total On Time':'Verdichterstunden',
        'Betriebsstunden · Maximum':'Betriebsstunden max.', 'Betriebsstunden · Minimum':'Betriebsstunden min.',
        'Energy Consumption':'Stromzähler', 'Energy Generation':'Wärmezähler',
    }
    result = ' · '.join(dict.fromkeys(parts))
    for old,new in replacements.items():result = result.replace(old,new)
    return result
