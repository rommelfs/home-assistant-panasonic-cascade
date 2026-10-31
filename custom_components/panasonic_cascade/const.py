"""Integration constants."""
DOMAIN = "panasonic_cascade"
PLATFORMS = ["sensor", "binary_sensor", "switch", "number", "select", "button"]
DEFAULT_PROJECT = "pSmartEdge"
# Only regular UI controls, never emergency overrides or sterilization triggers.
BOOL_CONTROLS = {"sgReady", "stopRun"}
ENUM_CONTROLS = {"quietModeRequest", "bufferMode", "zone1Zone2OnOffSetpoint"}
# Direct setpoints use conservative limits; heating-curve limits match captured metadata.
NUMBER_CONTROLS = {
    # Buffer-only offset, deliberately narrower than possible controller ranges.
    "tBufferTank": (0, 10),
    "zone1WaterTemperatureHotSetpoint": (20, 55),
    "zone1WaterTemperatureColdSetpoint": (5, 25),
    "tankWaterTempSpBeforeSgReady": (40, 60),
    "compensationCurveHeatZone1MaxTemperature": (20, 75),
    "compensationCurveHeatZone1MinTemperature": (20, 75),
    "compensationCurveHeatZone1OutdoorAirMaxTemperature": (-20, 15),
    "compensationCurveHeatZone1OutdoorAirMinTemperature": (-20, 15),
}
STATUS_FIELDS = ("isConnected", "isOn", "isRunning", "isInAlarm", "isAvailableBuffer", "isAvailableTank", "run", "isEnabled", "isRunningBuffer", "isRunningTank", "runRequestBuffer")
COUNT_FIELDS = ("runningUnitsAmount", "requiredUnitsAmount", "availableUnitsAmount", "configuredUnitsAmount", "runningUnitsAmountHot", "runningUnitsAmountCold", "numberOfZones")

CONFIG_FIELDS = {'oduModel': 'Außengeräte-Modell',
 'iduModel': 'Innengeräte-Modell',
 'modelSeriesSelection': 'Modellserie',
 'outdoorType': 'Außengerätetyp',
 'capacityRank': 'Nennleistung',
 'loopsControlType': 'Regelung der Kreise',
 'waterTempSpOffsetHeat': 'Heizen – Sollwertverschiebung',
 'waterTempSpOffsetCool': 'Kühlen – Sollwertverschiebung',
 'pidConstProportionale': 'Kaskade – PID-Proportionalanteil',
 'pidConstIntegral': 'Kaskade – PID-Integralanteil',
 'stagingDelayUp': 'Kaskade – Zuschaltverzögerung',
 'stagingDelayDown': 'Kaskade – Abschaltverzögerung',
 'minNumberRunningUnits': 'Kaskade – Mindestanzahl Geräte',
 'maxNumberRunningUnits': 'Kaskade – Höchstanzahl Geräte',
 'targetTimeHot': 'Heizen – Zielzeit',
 'targetTimeCold': 'Kühlen – Zielzeit',
 'deltaTempToStartHot': 'Heizen – Einschaltdifferenz',
 'deltaTempToStartCold': 'Kühlen – Einschaltdifferenz',
 'deltaTempToStartAllHot': 'Heizen – Differenz für alle Geräte',
 'deltaTempToStartAllCold': 'Kühlen – Differenz für alle Geräte'}
