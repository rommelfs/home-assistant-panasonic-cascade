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
        'Floor - Site Info':'Anlage', 'Zone Group':'',
        'Consumed electrical power':'Anlage · Strom', 'Generated thermal power':'Anlage · Wärme',
        'Water Temperature - Inlet':'Rücklauf', 'Water Temperature - Outlet':'Vorlauf',
        'Water Temperature - Setpoint':'Solltemperatur', 'Outdoor Air Temperature':'Außen',
        'Water Temp - Zone 1 Cool Setpoint':'Zone 1 · Kühlen Soll',
        'Water Temp - Zone 1 Heat Setpoint':'Zone 1 · Heizen Soll',
        'Water Temp - Zone 2 Cool Setpoint':'Zone 2 · Kühlen Soll',
        'Water Temp - Zone 2 Heat Setpoint':'Zone 2 · Heizen Soll',
        'Water Temp - Actual Value':'Puffertemperatur', 'Water Temp - Zone 1':'Zone 1 · Wasser',
        'Water Temp - Zone 2':'Zone 2 · Wasser', 'Δt Buffer Tank':'Puffer ΔT',
        'Standardwert':'', 'Buffer':'Puffer', 'Quiet mode request':'Anforderung',
        'Quiet mode':'Leisemodus', 'Smart Grid Ready':'SG Ready',

        'Betriebsstunden · Maximum':'Betriebsstunden max.', 'Betriebsstunden · Minimum':'Betriebsstunden min.',
        'Energy Consumption':'Stromzähler', 'Energy Generation':'Wärmezähler',
    }
    result = ' · '.join(dict.fromkeys(parts))
    for old,new in replacements.items():result = result.replace(old,new)
    return ' · '.join(p.strip() for p in result.split(' · ') if p.strip())
