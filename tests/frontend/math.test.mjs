import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
globalThis.HTMLElement = class {attachShadow() {this.shadowRoot = {};}};
globalThis.customElements = {get() {return true;}};
globalThis.window = {};
const source = await readFile(new URL('../../custom_components/panasonic_cascade/www/heating-curve.js',import.meta.url),'utf8');
const {temperatureAt,HeatingCurveCard,KEYS} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const values = {water_max:42,water_min:35,outdoor_min:-10,outdoor_max:15};
test('heating curve interpolates and clamps at both ends',()=>{
  assert.equal(temperatureAt(-30,values),42);
  assert.equal(temperatureAt(30,values),35);
  assert.equal(temperatureAt(-10,values),42);
  assert.equal(temperatureAt(15,values),35);
  assert.equal(temperatureAt(0,values),39.2);
  assert.equal(temperatureAt(0,{...values,water_max:35}),35);
});
test('invalid, missing or reversed endpoints never draw a misleading line',()=>{
  for (const changes of [{outdoor_min:15},{outdoor_min:20},{water_min:50},{water_max:NaN},{water_max:undefined}]) assert.equal(temperatureAt(0,{...values,...changes}),null);
});
function card() {
  const c=new HeatingCurveCard(); c.setConfig({entities:Object.fromEntries(KEYS.map(k=>[k,'number.'+k]))});
  c._render=()=>{}; c._t={saved:'saved',failed:'failed'};
  c._hass={states:Object.fromEntries(KEYS.map(k=>['number.'+k,{state:String(values[k]),attributes:{}}]))}; return c;
}
test('preview is local; only changed defaults are sent, with negative outdoor values',async()=>{
  const c=card(),calls=[];
  c._hass.callService=async(d,s,data)=>{calls.push([d,s,data]);c._hass.states[data.entity_id].state=String(data.value);};
  c._draft.outdoor_min='-12'; assert.equal(c._values().values.outdoor_min,-12);assert.equal(calls.length,0);
  await c._apply(); assert.deepEqual(calls,[['number','set_value',{entity_id:'number.outdoor_min',value:-12}]]); assert.deepEqual(c._draft,{});
});
test('invalid/offline input performs no writes; failed request retains draft',async()=>{
  const c=card();let calls=0;c._hass.callService=async()=>{calls++;throw Error('offline');};
  for (const value of ['','80','NaN','-1']) {c._draft.water_max=value;await c._apply();}
  assert.equal(calls,0);
  c._draft.water_max='45';c._hass.states['number.outdoor_min'].state='unavailable';await c._apply();assert.equal(calls,0);
  c._hass.states['number.outdoor_min'].state='-10';await c._apply();assert.equal(calls,1);assert.equal(c._error,true);assert.equal(c._draft.water_max,'45');
});
test('read-only sensors cannot send commands, pending defaults clear only on matching state',async()=>{
  const c=card();c._pending.water_max=45;c._draft.water_max='45';c.hass=c._hass;assert.equal(c._draft.water_max,'45');
  c._hass.states['number.water_max'].state='45';c.hass=c._hass;assert.deepEqual(c._pending,{});assert.deepEqual(c._draft,{});
  c._config.entities.water_max='sensor.water_max';c._hass.states['sensor.water_max']={state:'42',attributes:{}};
  c._draft.water_max='45';c._hass.callService=()=>assert.fail('read-only');await c._apply();
});
