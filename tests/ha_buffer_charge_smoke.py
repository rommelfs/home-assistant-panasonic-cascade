"""Real HA setup/service/reload check; controller and device writes are simulated."""
import asyncio,pathlib,tempfile,shutil,sys,json
from types import MappingProxyType
from unittest.mock import AsyncMock,Mock,patch
from homeassistant.core import HomeAssistant
from homeassistant import bootstrap,loader
from homeassistant.config_entries import ConfigEntry,ConfigEntryState

async def main():
 root=pathlib.Path(tempfile.mkdtemp(prefix='panasonic-charge-smoke-'))
 shutil.copytree(pathlib.Path(__file__).resolve().parents[1]/'custom_components',root/'custom_components',ignore=shutil.ignore_patterns('__pycache__'))
 sys.path.insert(0,str(root))
 hass=HomeAssistant(str(root));hass.config.skip_pip=True;loader.async_setup(hass)
 await bootstrap.async_from_config_dict({'homeassistant':{'latitude':0,'longitude':0,'elevation':0,'unit_system':'metric','time_zone':'Europe/Berlin'},'logger':{'default':'error'}},hass)
 import custom_components.panasonic_cascade as integration
 from custom_components.panasonic_cascade.zinc import Number,Ref,MARKER
 row={'id':Ref('p:demo:r:offset'),'siteRef':Ref('p:demo:r:site'),'bufferModelId':'_equip:buffer_point:tBufferTank','kind':'Number','unit':'°C','point':MARKER,'writable':MARKER,'actions':'pointSetDef($self,$val)','curStatus':'ok','curVal':Number(2,'°C'),'writeDef':Number(2,'°C')}
 writes=[]
 class Client:
  url='https://controller.invalid';project='demo'
  def __init__(self,*_):pass
  async def snapshot(self,*_):return {'p:demo:r:offset':dict(row),'p:demo:r:mode':{'id':Ref('p:demo:r:mode'),'bufferModelId':'_equip:buffer_point:bufferMode','curStatus':'ok','curVal':'Heat'}}
  async def read_point(self,ident,*_):return {'bufferModelId':'_equip:buffer_point:bufferMode','curStatus':'ok','curVal':'Heat'} if ident=='p:demo:r:mode' else dict(row)
  async def set_default(self,point,target):
   writes.append(target);row.update(curVal=Number(target,'°C'),writeDef=Number(target,'°C'))
 opts={'enable_controls':True,'pv_charge_enabled':True,'pv_charge_confirmed':True,'pv_charge_auto':False}
 for key,n,u in [('export',2500,'W'),('battery',0,'W'),('pv',6000,'W'),('temperature',40,'°C')]:
  opts[f'pv_charge_{key}_sensor']='sensor.test_'+key
  hass.states.async_set('sensor.test_'+key,str(n),{'unit_of_measurement':u})
 entry=ConfigEntry(version=1,minor_version=2,domain='panasonic_cascade',title='Mock cascade',data={'site_id':'p:demo:r:site','project':'demo','url':'https://controller.invalid'},options=opts,source='user',unique_id='mock-cascade',discovery_keys=MappingProxyType({}),subentries_data=[])
 with patch.object(integration,'CascadeClient',Client),patch.object(integration,'async_setup_frontend',AsyncMock()),patch.object(integration,'async_apply_dhw_visibility',AsyncMock()):
  await hass.config_entries.async_add(entry)
  await hass.async_block_till_done()
  assert entry.state==ConfigEntryState.LOADED,entry.state
  states=[(s.entity_id,s.state) for s in hass.states.async_all() if s.entity_id.startswith(('number.','button.')) or 'pv_pufferladung' in s.entity_id]
  print('ENTRY_LOADED',states)
  assert len([x for x in states if x[0].startswith('number.')])==1,states
  manager=entry.runtime_data.buffer_charge;manager.stable_since=manager.clock()-121
  await hass.services.async_call('panasonic_cascade','start_buffer_charge',{'entry_id':entry.entry_id,'offset':7,'duration_minutes':1},blocking=True)
  await hass.async_block_till_done()
  print('ACTIVE_STATUS',manager.status,manager.lease)
  assert writes==[7]
  assert any(s.state=='on' for s in hass.states.async_all('binary_sensor') if 'pv_pufferladung' in s.entity_id)
  saved=json.loads((root/'.storage'/f'panasonic_cascade.buffer_charge.{entry.entry_id}').read_text())
  assert saved['data']['lease']['baseline']==2
  # Reload restores a nonexpired lease, then does not resume it.
  await hass.config_entries.async_reload(entry.entry_id);await hass.async_block_till_done()
  assert writes==[7,2],writes
  assert any(s.state=='off' for s in hass.states.async_all('binary_sensor') if 'pv_pufferladung' in s.entity_id)
  assert entry.runtime_data.buffer_charge.lease is None
  # Explicit sensorless test, through real HA services; automatic start remains off.
  hass.config_entries.async_update_entry(entry,options={**dict(entry.options),
    'pv_charge_test_without_temperature':True,'pv_charge_temperature_sensor':''})
  await hass.async_block_till_done()
  hass.states.async_remove('sensor.test_temperature')
  manager=entry.runtime_data.buffer_charge;manager.stable_since=manager.clock()-121
  await hass.services.async_call('panasonic_cascade','start_buffer_charge',
    {'entry_id':entry.entry_id,'offset':10,'duration_minutes':120},blocking=True)
  assert writes==[7,2,4],writes
  assert manager.lease['temperature_unmonitored_test'] is True
  assert 0 < manager.lease['expires']-manager.clock() <= 300
  await hass.async_block_till_done()
  assert any(s.state=='Ladetest ohne Temperaturüberwachung' for s in hass.states.async_all('sensor'))
  await hass.services.async_call('panasonic_cascade','stop_buffer_charge',{'entry_id':entry.entry_id},blocking=True)
  assert writes==[7,2,4,2],writes
  assert await hass.config_entries.async_unload(entry.entry_id)
  await hass.async_stop(force=True)
  print('SERVICE_START_RELOAD_RESTORE_AND_UNLOAD_OK',writes)
asyncio.run(main())
