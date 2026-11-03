"""Organise generated cards without discarding energy history or personal cards."""
from copy import deepcopy
from .const import DOMAIN
from .labels import display_label

MARKER = '{# Panasonic Cascade at-a-glance v1 #}'

LEGACY_SOURCE_NOTE = '**Rechnerische Zuordnung für alle Wärmepumpen.** PV/Netz/Batterie werden anteilig aus dem Haus-Strommix zugeordnet; keine getrennte Herkunftsmessung am WP-Anschluss. Batterieherkunft bleibt unbekannt. Zählung ab Einrichtung; Messlücken werden ausgelassen.'
SOURCE_NOTE = '**Rechnerische Zuordnung nach konfigurierter Zählergrenze.** Bei Messkaskade versorgt nur der Überschuss des Hauszweigs die WP; der übrige WP-Bedarf kommt aus dem Netz. Gemischter PV-/Batterieexport wird anteilig geschätzt. Herkunft wird ab Umstellung neu erfasst; alte Herkunftsreihen sind ausgeschlossen. WP-Gesamtverbrauch stammt unabhängig davon aus den Panasonic-Zählerstatistiken.'



def bind_dashboard_paths(config, url_path):
    """Use the actual dashboard URL for links; never hardcode the installation path."""
    for v in config.get('views',[]):
        if v.get('path','').startswith('energy-') and v.get('back_path')=='energy':
            v['back_path']='/'+url_path+'/energy'
        for c in walk(v):
            if c.get('title')=='Energie-Zeiträume' and c.get('type')=='grid':
                for button in c.get('cards',[]):
                    action=button.get('tap_action',{})
                    if action.get('navigation_path','').startswith('energy-'):
                        action['navigation_path']='/'+url_path+'/'+action['navigation_path']
            if MARKER in c.get('content',''):
                for path in ('energy','settings','pv-buffer'):
                    c['content']=c['content'].replace(']('+path+')','](/'+url_path+'/'+path+')')
    return config


def walk(container):
    yield container
    for key in ('cards', 'sections'):
        for child in container.get(key, []):
            if isinstance(child, dict):
                yield from walk(child)


def cards(view):
    return view.get('cards', []) + [c for s in view.get('sections', []) for c in s.get('cards', [])]


def source_balance(records, owner):
    periods = {}
    for e in records:
        if e.config_entry_id == owner and '|energy_source:' in e.unique_id:
            source, period = e.unique_id.rsplit('|energy_source:', 1)[1].split(':')
            periods.setdefault(period, {})[source] = e.entity_id
    return periods


def energy_table(periods, consumption=None):
    consumption = consumption or {}
    content = MARKER + '\n**Rechnerische Zuordnung · kWh**\n\n| Zeitraum | WP gesamt | PV | Netz | Batterie | Zugeordnet | Differenz* |\n|---|---:|---:|---:|---:|---:|---:|\n'
    for period, label in [('day','Heute'),('week','Woche'),('month','Monat'),('year','Jahr'),('total','Seit Umstellung')]:
        ids = [periods.get(period, {}).get(k) for k in ('pv','grid','battery')]
        if not all(ids):
            continue
        content += '{% set values = [' + ','.join("states('"+i+"') | float(none)" for i in ids) + '] -%}\n'
        meter = consumption.get(period)
        content += '{% set meter = ' + ("states('"+meter+"') | float(none)" if meter else 'none') + ' -%}\n'
        content += '| ' + label + ' | {{ meter | round(2) if meter is not none else "—" }} | {% for v in values %}{{ v | round(2) if v is not none else "—" }} | {% endfor %}{{ values | sum | round(2) if none not in values else "—" }} | {{ ((meter - values | sum) | round(2)) if meter is not none and none not in values else "—" }} |\n'
    content += '\n**Erfasste Zuordnungszeit:** '
    for period,label in [('day','Heute'),('week','Woche'),('month','Monat'),('year','Jahr')]:
        source = periods.get(period,{}).get('pv')
        if source:
            content += label + " {{ (state_attr('"+source+"','observed_seconds') | float(0) / 3600) | round(2) }} h · "
    first = periods.get('day',{}).get('pv')
    if first:
        content += "\n\n{% if state_attr('"+first+"','measurement_issue') %}**Messhinweis:** {{ state_attr('"+first+"','measurement_issue') }}{% endif %}\n"
    content += '\n*Positive Differenz: noch nicht zugeordnet / Messlücken; negative Differenz kann durch nachlaufende Zählerstatistiken entstehen. Zählerstatistiken und Leistungsintegration haben unterschiedliche Auflösung. Herkunft wird erst ab Umstellung neu erfasst; keine rückwirkend erfundenen Anteile.\n'
    return {'type':'markdown', 'title':'Stromherkunft · Bilanz', 'content':content}


def organise_dashboard(config, registry, owners=None):
    result = deepcopy(config)
    overview = next((v for v in result.get('views', []) if v.get('path') == 'overview'), None)
    if overview is None or overview.get('panel') or overview.get('type') == 'panel' or not hasattr(registry,'entities'):
        return result
    if owners is None:
        ids = {r if isinstance(r, str) else r.get('entity') for v in result['views'] for c in walk(v)
               if isinstance(c.get('entities'), list) for r in c['entities'] if isinstance(r, (str, dict))}
        owners = {e.config_entry_id for i in ids if (e := registry.entities.get(i)) and e.platform == DOMAIN}
    records = [e for e in registry.entities.values() if e.platform == DOMAIN and e.config_entry_id in owners
               and not getattr(e,'disabled',False) and not getattr(e,'hidden',False)]
    if not records:
        return result

    def matching(suffix):
        return sorted((e for e in records if e.unique_id.endswith(suffix)), key=lambda e:e.entity_id)

    def rows(items):
        return [{'entity':e.entity_id, 'name':display_label(e.name or e.original_name or e.entity_id)} for e in items]

    def view(path, title, icon):
        found = next((v for v in result['views'] if v.get('path') == path), None)
        if found is None:
            found = {'path':path, 'title':title, 'icon':icon, 'cards':[]}
            result['views'].append(found)
        return found

    def append(destination, card):
        # Retain the existing graph's configured time range and other options.
        if any(c.get('type') == card.get('type') and c.get('title') == card.get('title') for c in cards(destination)):
            return
        if destination.get('type') == 'sections':
            destination.setdefault('sections', []).append({'type':'grid', 'cards':[card]})
        else:
            destination.setdefault('cards', []).append(card)

    managed = {'Steuerung':'settings', 'Leistung':'energy', 'Momentanverbrauch':'energy', 'COP':'energy',
               'Aktuelle Temperaturen':'temperatures', 'Temperaturverlauf':'temperatures',
               'Leistungsverlauf':'runtime', 'Betriebszustand':'details', 'Alarme':'alarms',
               'PV-Pufferladung · Freigabe (24 h)':'pv-buffer'}
    names = {'settings':('Steuerung','mdi:tune'), 'energy':('Energie','mdi:lightning-bolt'),
             'temperatures':('Temperaturen','mdi:thermometer'), 'runtime':('Laufzeiten & Taktung','mdi:chart-timeline-variant'),
             'details':('Diagnose','mdi:format-list-bulleted'), 'alarms':('Alarme','mdi:alert-circle-outline'),
             'pv-buffer':('PV-Pufferladung','mdi:solar-power-variant')}
    # Move old overview content; four compact summaries replace its wall of data.
    for card in cards(overview):
        if MARKER in card.get('content',''):
            continue
        if card.get('title') in ('Momentanes Schalten','Gesamtverbrauch der Kaskade','Pufferfreigabe','Fehler'):
            continue
        title = card.get('title') or card.get('card',{}).get('title','')
        if title.startswith(('☀️ PV-Pufferladung aktiv','⚠️ PV-Pufferladung')):
            continue  # The compact buffer card also exposes restore/conflict states.
        ids = card.get('entities', {})
        ids = list(ids.values()) if isinstance(ids,dict) else [r if isinstance(r,str) else r.get('entity') for r in ids]
        owned = bool(ids) and all(i in registry.entities and registry.entities[i].platform == DOMAIN for i in ids)
        # Configured temperature/PV inputs belong to the installation but may use ESPHome/Huawei.
        if title == 'PV-Pufferladung · Freigabe (24 h)' and any(i in registry.entities and registry.entities[i].platform==DOMAIN for i in ids):
            owned = True
        destination = 'settings' if card.get('type') == 'custom:panasonic-cascade-heating-curve' and owned else managed.get(title) if owned else None
        if destination:
            if title=='Betriebszustand':continue  # Complete device states already live in Diagnose.
            if title=='Alarme' and any(c.get('title')=='Alarme und Verlauf' for v in result['views'] if v.get('path')=='alarms' for c in cards(v)):continue
            def entity_ids(c):
                return {r if isinstance(r,str) else r.get('entity') for r in c.get('entities',[]) if isinstance(r,(str,dict))}
            if title=='Leistungsverlauf' and card.get('hours_to_show')==12 and any(c.get('title')=='Leistung während des Betriebs' and entity_ids(c)==entity_ids(card) for v in result['views'] if v.get('path')=='runtime' for c in cards(v)):
                continue  # Same generated power series already has its 24-hour operating graph.
            append(view(destination,*names[destination]),card)
        else:
            append(view('personal','Eigene Karten','mdi:card-multiple-outline'),card)

    running = matching('|power_running') or matching('|isRunning')
    overview_cards = [{'type':'entities','title':'Momentanes Schalten','show_header_toggle':False,
                       'entities':rows(running)}] if running else []
    if not running:
        overview_cards.append({'type':'markdown','title':'Momentanes Schalten','content':MARKER+'\nKein Betriebsstatus verfügbar.'})
    consumed = matching('|summary:consumedPower|curVal')
    content = MARKER+'\n'
    for e in consumed:
        content += "{% set value = states('"+e.entity_id+"') | float(none) %}{% set unit = state_attr('"+e.entity_id+"','unit_of_measurement') %}\n"
        content += '**Aktuell:** {{ ((value / 1000 if unit == "W" else value) | round(2)) if value is not none and unit in ["W","kW"] else "—" }} kW\n\n'
    consumption = {owner:{e.unique_id.rsplit('|consumption:',1)[1]:e.entity_id for e in records
                         if e.config_entry_id==owner and '|consumption:' in e.unique_id} for owner in owners}
    for owner in sorted(owners):
        meter = consumption[owner].get('day')
        if meter:
            content += "**Heute · WP-Zähler:** {{ states('"+meter+"') | float(none) | round(2) if is_number(states('"+meter+"')) else '—' }} kWh (Zählerstatistik)\n\n"
        ids = [source_balance(records,owner).get('day',{}).get(k) for k in ('pv','grid','battery')]
        if all(ids):
            content += '{% set values = [' + ','.join("states('"+i+"') | float(none)" for i in ids) + '] %}\n'
            content += '**Davon zugeordnet (Teilaufzeichnung):** {{ values | sum | round(2) if none not in values else "—" }} kWh (Zuordnung)\n\n'
            content += '{% set attributed = values | sum if none not in values else none %}\n'
            content += '| Herkunft | Heute zugeordnet | Anteil* |\n| :--- | ---: | ---: |\n'
            for label,index in (('Netz',1),('PV',0),('Batterie',2)):
                content += '| '+label+' | {{ values['+str(index)+'] | round(2) if values['+str(index)+'] is not none else "—" }} kWh | {{ (values['+str(index)+'] / attributed * 100) | round(1) if attributed is not none and attributed > 0 else "—" }} % |\n'
            content += '\n*Anteile an der zugeordneten Energie, nicht am gesamten Tagesverbrauch.*\n\n'
            if meter:
                content += "{% set measured = states('"+meter+"') | float(none) %}"
                content += '**Differenz zum WP-Zähler:** {{ (measured - attributed) | round(2) if measured is not none and attributed is not none else "—" }} kWh\n\n'
                content += 'Positive Differenz: noch nicht zugeordnet; negative Differenz ist durch zeitversetzte Zählerstatistik möglich.\n\n'
            content += "**Messabdeckung der Zuordnung:** {{ ((state_attr('"+ids[0]+"','observed_seconds') | float(0)) / 3600) | round(2) }} h · seit {{ state_attr('"+ids[0]+"','recording_started') | timestamp_custom('%d.%m. %H:%M', true, '—') }}\n\n"
    if not consumed:
        content += 'Keine Gesamtleistungsmessung verfügbar.\n'
    content += '[Energie und Stromherkunft](energy)'
    overview_cards.append({'type':'markdown','title':'Gesamtverbrauch der Kaskade','content':content})
    content = MARKER+'\n'
    for e in matching('|pv_buffer_charge'):
        q = "'"+e.entity_id+"'"
        content += '{{ "**PV-LADUNG AKTIV**" if state_attr('+q+',"phase") == "charging" else "**" ~ states('+q+') ~ "**" }}\n\n'
        content += 'Puffer-Soll: {{ state_attr('+q+',"buffer_target") | round(1) if state_attr('+q+',"buffer_target") is number else "—" }} °C · Anhebung: {{ state_attr('+q+',"effective_offset") | round(1) if state_attr('+q+',"effective_offset") is number else "—" }} Grad\n\n'
        content += '{% if state_attr('+q+',"adaptive_configured") %}Adaptive PV-Automatik bis {{ state_attr('+q+',"temperature_limit") }} °C\n\n{% endif %}'
        content += '{% set reason = state_attr('+q+',"reason") or "" %}{{ {"No PV production":"Kein PV-Ertrag", "Battery is discharging":"Batterie entlädt", "Waiting for PV surplus after battery reserve":"Wartet auf PV-Überschuss nach Batteriereserve", "Automatic restart cooldown is active":"Wiederanlaufsperre aktiv"}.get(reason, reason) }}\n\n'
    content += '[PV-Verlauf](pv-buffer) · [Steuerung](settings)'
    overview_cards.append({'type':'markdown','title':'Pufferfreigabe','content':content})
    error_rows = rows(matching('|summary:activeAlarms|curVal') + matching('|isInAlarm'))
    overview_cards.append({'type':'entities','title':'Fehler','show_header_toggle':False,'entities':error_rows} if error_rows else
                          {'type':'markdown','title':'Fehler','content':MARKER+'\nKein Alarmstatus verfügbar.'})
    overview.update(title='At-a-glance', icon='mdi:view-dashboard-outline', type='sections', max_columns=2,
                    sections=[{'type':'grid','cards':overview_cards[:2]},{'type':'grid','cards':overview_cards[2:]}])
    overview.pop('cards',None)

    for v in result['views']:
        if v.get('path')=='details':v['title']='Diagnose'
        if v.get('path')=='settings':v['title']='Steuerung'
        # Exact duplicates only; graph periods, time ranges and custom options matter.
        seen = []
        for container in [v]+v.get('sections',[]):
            kept=[]
            for card in container.get('cards',[]):
                if card in seen:continue
                seen.append(card);kept.append(card)
            if 'cards' in container:container['cards']=kept
    energy = next((v for v in result['views'] if v.get('path')=='energy'),None)
    if energy:
        for card in walk(energy):
            if card.get('type') == 'markdown' and card.get('content') == LEGACY_SOURCE_NOTE:
                card['content'] = SOURCE_NOTE
        has_instant = any(c.get('title')=='Momentanverbrauch' for c in cards(energy))
        for container in [energy]+energy.get('sections',[]):
            if 'cards' not in container:continue
            container['cards'] = [c for c in container.get('cards',[]) if c.get('title') != 'Energiezähler – Verlauf' and
                not (has_instant and c.get('title')=='Leistung') and
                not (c.get('type') in ('entities','entity-filter') and c.get('title','').startswith('WP · Stromherkunft · ') and
                     c['title'].rsplit(' · ',1)[-1] in ('Heute','Diese Woche','Dieser Monat','Dieses Jahr','Seit Einrichtung'))]
        for owner in sorted(owners):
            periods = source_balance(records,owner)
            if periods:
                table=energy_table(periods,consumption.get(owner))
                # Refresh only our marked table on subsequent migrations.
                existing=next((c for c in cards(energy) if c.get('title')==table['title'] and MARKER in c.get('content','')),None)
                if existing is not None:existing.update(table)
                else:append(energy,table)
        for container in [energy]+energy.get('sections',[]):
            for i,c in enumerate(container.get('cards',[])):
                if c.get('type')=='entities' and c.get('title','').startswith('WP · Stromherkunft · Aktuell'):
                    container['cards'][i]={'type':'entity-filter','title':c['title'],'entities':c['entities'],
                        'conditions':[{'condition':'state','state_not':['unknown','unavailable']}],
                        'show_empty':False,'card':{k:v for k,v in c.items() if k!='entities'}}
        periods = [('hour','Stündlich'),('day','Täglich'),('week','Wöchentlich'),('month','Monatlich'),('year','Jährlich')]
        navigation = []
        for period, label in periods:
            selected = []
            for container in [energy]+energy.get('sections',[]):
                if 'cards' not in container:continue
                kept=[]
                for card in container.get('cards',[]):
                    if card.get('type')=='statistics-graph' and card.get('period')==period and (
                        card.get('title','').startswith(('Verbrauch von Elektrizität','WP · Stromherkunft')) or card.get('title')=='Energie pro Tag'):
                        selected.append(card)
                    else:kept.append(card)
                container['cards']=kept
            destination=next((v for v in result['views'] if v.get('path')=='energy-'+period),None)
            if selected or destination is not None:
                destination=view('energy-'+period,'Energie · '+label,'mdi:chart-bar')
                destination['subview']=True
                destination.setdefault('back_path','energy')
                for card in selected:
                    # During migration the merge may already have created a
                    # default subview. Prefer the existing main-view graph's
                    # customised range/options over that new default.
                    prior=next((c for c in cards(destination) if c.get('type')==card.get('type') and c.get('title')==card.get('title')),None)
                    if prior is not None:prior.clear();prior.update(deepcopy(card))
                    else:append(destination,card)
                navigation.append({'type':'button','name':label,'icon':'mdi:chart-bar',
                                   'tap_action':{'action':'navigate','navigation_path':'energy-'+period}})
        if navigation:
            existing=next((c for c in cards(energy) if c.get('type')=='grid' and c.get('title')=='Energie-Zeiträume'),None)
            nav={'type':'grid','title':'Energie-Zeiträume','columns':3,'square':False,'cards':navigation}
            if existing is not None:existing.update(nav)
            else:
                if energy.get('type')=='sections':energy.setdefault('sections',[]).insert(0,{'type':'grid','cards':[nav]})
                else:energy.setdefault('cards',[]).insert(0,nav)
    runtime=next((v for v in result['views'] if v.get('path')=='runtime'),None)
    if runtime and any('Panasonic Cascade daily-start table' in c.get('content','') for c in cards(runtime)):
        for container in [runtime]+runtime.get('sections',[]):
            if 'cards' in container:
                container['cards']=[c for c in container.get('cards',[]) if c.get('title') not in ('Einschaltungen heute','Wärmepumpen – Betriebszustand','Betriebsstunden – Verlauf')]
    personal=next((v for v in result['views'] if v.get('path')=='personal'),None)
    if personal and energy:
        copies=[c for c in cards(energy) if c.get('title')=='Momentanverbrauch']
        for container in [personal]+personal.get('sections',[]):
            if 'cards' in container:container['cards']=[c for c in container['cards'] if c not in copies]
        if not cards(personal) and not personal.get('badges'):
            result['views'].remove(personal)
    order=['overview','energy','runtime','temperatures','pv-buffer','settings','alarms','personal','details']
    result['views'].sort(key=lambda v:order.index(v.get('path')) if v.get('path') in order else len(order))
    return result
