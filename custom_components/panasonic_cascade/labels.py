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


def display_label(label, context=''):
    """Use card context instead of repeating controller hierarchy in every row."""
    text = compact_label(label)
    replacements = {
        'Water Temp - Zone 1 Setpoint Status':'Zone 1 · Soll aktuell',
        'Water Temp - Zone 2 Setpoint Status':'Zone 2 · Soll aktuell',
        'Water Temp - Buffer Setpoint Status':'Puffer · Soll aktuell',
        'Water Temp - Setpoint Control':'Sollregelung',
        'Water Temp - Setpoint Max':'Soll max.', 'Water Temp - Setpoint Status':'Soll aktuell',
        'Compensation Curve - Heat Mode Zone 1':'Zone 1 · Heizkurve',
        'Compensation Curve - Cool Mode':'Kühlkurve',
        'Outdoor Air Temp - Max':'Außen max.', 'Outdoor Air Temp - Min':'Außen min.',
        'Water Temp - Max':'Wasser max.', 'Water Temp - Min':'Wasser min.',
        'Primary Loop':'Primärkreis', 'runningUnitsAmount':'Laufende Geräte',
        'Energy · Cold Water':'Kühlen/WRG', 'Energy · Hot Water':'Heizen',
        'Energy · DHW':'Warmwasser', 'Puffer · Puffer ΔT':'Puffer · ΔT',
        'Puffer · Puffertemperatur':'Puffer · Temperatur',
        'Stromzähler':'Strom', 'Wärmezähler':'Wärme', 'el. Leistung':'Strom',
        'Wärmeleistung':'Wärme', 'Thermal power':'Wärme', 'Mode':'Betriebsart',
        'Enable':'Aktiv', 'Zone1-Zone2 On/Off':'Zone 1/2 · Freigabe',
        'Min. Außentemperatur':'Außen min.', 'Max. Außentemperatur':'Außen max.',
        'Min. Wassertemperatur':'Wasser min.', 'Max. Wassertemperatur':'Wasser max.',
    }
    for old,new in replacements.items():text=text.replace(old,new)
    parts=[p.strip() for p in re.split(r'\s+[–·]\s+|\s+-\s+',text) if p.strip() and p.strip() not in ('Vorgabe','Standardwert','Energy')]
    context=compact_label(context)
    if context=='COP':parts=[p for p in parts if p not in ('COP aktuell','COP')]
    if 'Betriebsstunden' in context:parts=[p for p in parts if p not in ('Verdichterstunden','Betriebsstunden')]
    if context.startswith('Verbrauch von Elektrizität'):parts=[p for p in parts if p!='Strom']
    if 'Leisemodus' in parts:parts=[p for p in parts if p!='Anforderung']
    # A repeated equipment path can occur in older entity registry names.
    pumps=[i for i,p in enumerate(parts) if re.search(r'WP \d+',p)]
    if pumps:parts=parts[pumps[-1]:]
    if parts and re.fullmatch(r'WP \d+',parts[0]) and parts[0] in context:
        parts=parts[1:]
    if len(parts)>=3 and re.fullmatch(r'WP \d+',parts[0]) and parts[1] in ('Heizen','Kühlen/WRG','Warmwasser'):
        parts=[parts[0]+' '+parts[1],*parts[2:]]
    for prefix in ('Puffer','Anlage','Zone 1','Zone 2'):
        if parts and parts[0]==prefix and prefix in context:parts=parts[1:]
    while len(parts)>1 and parts[0] in context and parts[0] in ('Heizkurve','Kühlkurve','Zone 1','Zone 2','Heizen','Kühlen/WRG','Warmwasser'):
        parts=parts[1:]
    if len(parts)>2:
        parts=([parts[0],parts[-1]] if parts[0].startswith('WP ') else parts[-2:])
    return ' · '.join(dict.fromkeys(parts)) or text
